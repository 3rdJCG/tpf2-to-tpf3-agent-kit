"""materials: settle material types and sampler names after conversion."""
import collections
import os
import re

from PIL import Image

from .build import BASE_TEXTURES, tex_key
from .common import FLAT_NORMAL, RETYPEABLE, SOLID, TRANSPARENT, read, write


TEXCOORD_SCALE = """\t\t\ttexcoord_scale = {
\t\t\t\tfragmentProperties = {
\t\t\t\t\t{
\t\t\t\t\t\ttexCoordScale = 1,
\t\t\t\t\t},
\t\t\t\t},
\t\t\t},
"""

# official glass (alco_hh600_glass.mtl) uses the sorted form
ALPHA_TEST = {
    "sorted": """\t\t\talpha_test = {
\t\t\t\tfragmentProperties = {
\t\t\t\t\t{
\t\t\t\t\t\tcutout = false,
\t\t\t\t\t\tdisableDepthAndNormalWrite = true,
\t\t\t\t\t\tsorted = true,
\t\t\t\t\t},
\t\t\t\t},
\t\t\t},
""",
    "cutout": """\t\t\talpha_test = {
\t\t\t\tfragmentProperties = {
\t\t\t\t\t{
\t\t\t\t\t\tcutout = true,
\t\t\t\t\t\tsorted = false,
\t\t\t\t\t},
\t\t\t\t},
\t\t\t},
""",
}

# The _NRML_MAP material types want a normal map even where the TF2 original
# had none. Point those at the base game's flat default rather than generating
# one: a hand-built BC5U file was rejected as "missing texture" even with a
# byte-correct header, and this is one less thing to get wrong.
MAP_NORMAL = """\t\t\tmap_normal = {
\t\t\t\tfragmentSamplers = {
\t\t\t\t\tnormalTex = {
\t\t\t\t\t\tfileName = "%s",
\t\t\t\t\t\tredGreen = true,
\t\t\t\t\t\ttype = "TWOD",
\t\t\t\t\t\twrapS = "REPEAT",
\t\t\t\t\t\twrapT = "REPEAT",
\t\t\t\t\t},
\t\t\t\t},
\t\t\t},
""" % BASE_TEXTURES["default_normal_map"]


def albedo_source(v, txt):
    """The original texture behind a material's albedo. Some TF2 mods ship
    .dds already, so don't assume .tga."""
    m = re.search(r'albedo(?:Opacity)?Tex.*?fileName = "tex/([^"]+?)\.(?:dds|tga)"',
                  txt, re.S)
    if not m:
        return None
    for key, path in texture_sources(v).items():
        if key == m.group(1):
            return path
    return None


# Same samplers as the _NRML_MAP types minus map_normal; base uses both
# (22 PHYSICAL, 31 PHYS_TRANSPARENT across its zips).
FLAT_TYPES = {SOLID: "PHYSICAL", TRANSPARENT: "PHYS_TRANSPARENT"}


def tangentless_materials(v):
    """Materials bound to at least one mesh that has no tangent attribute."""
    out, cache = set(), {}
    for model in v.models():
        txt = read(os.path.join(v.veh, model + ".mdl"))
        for m in re.finditer(r'materials = \{([^}]*)\},\s*\n\s*mesh = "([^"]+)"', txt):
            mesh = m.group(2)
            if mesh not in cache:
                p = os.path.join(v.veh, mesh.replace("/", os.sep))
                if os.path.exists(p):
                    t = read(p)
                    cache[mesh] = "tangent" not in t[t.find("vertexAttr"):]
                else:
                    cache[mesh] = False
            if cache[mesh]:
                out.update(re.findall(r'"mat/([^"]+\.mtl)"', m.group(1)))
    return out


def default_normal_red_green(txt):
    """Base binds its default normal map with redGreen = true, 83 times out
    of 83. One mod's own materials said false (or nothing) next to ours
    saying true, and validation rejects one texture used both ways."""
    d = re.escape(BASE_TEXTURES["default_normal_map"])
    txt = re.sub(r'(normalTex = \{\s*fileName = "%s",\s*)redGreen = false,' % d,
                 r'\1redGreen = true,', txt)
    return re.sub(r'(normalTex = \{\s*fileName = "%s",)(\r?\n\t+)(?=[^\t])(?!redGreen)' % d,
                  r'\1\2redGreen = true,\2', txt)


def settle_alpha_test(v, txt):
    """For a transparent type we keep as it is (TF2's newer
    PHYS_TRANSPARENT_NRML_MAP_CBLEND_DIRT and friends): choose cutout or
    sorted where the conversion left both false.

    Validation rejects two such materials sharing an order ("neither sorted
    nor cutout") - most EMU and DMU bodies
    hit it. Real translucency gets sorted; anything else gets cutout,
    which on an alpha that is all but opaque discards nothing, so the look is
    unchanged. Returns (kind, new text), or None when nothing needs doing."""
    block = re.search(r'(?ms)^\t{3}alpha_test = \{.*?^\t{3}\},\n', txt)
    if not block:
        return None
    body = block.group(0)
    if "cutout = true" in body or "sorted = true" in body:
        return None
    src = albedo_source(v, txt)
    kind = "sorted" if uses_alpha(src) and wants_sorted(src) else "cutout"
    new = body.replace("cutout = false", "cutout = %s" % (
        "true" if kind == "cutout" else "false"))
    new = new.replace("sorted = false", "sorted = %s" % (
        "true" if kind == "sorted" else "false"))
    if new == body:
        return None
    return kind, txt[:block.start()] + new + txt[block.end():]


def uses_alpha(path):
    """Whether an albedo's alpha actually makes part of the surface see-through.

    Not "any pixel below 255": one locomotive's body textures are 99.992% opaque with a
    scatter of slightly-off texels and no fully transparent one - block
    compression noise, not a mask. Treating that as transparent turned the
    whole locomotive body into a cut-out material. The smallest real mask
    seen so far is a DMU's interior texture at 1.5% non-opaque, so 0.1% separates
    the two with room either side."""
    if not path:
        return False
    im = Image.open(path)
    if im.mode not in ("RGBA", "LA", "PA"):
        return False
    hist = im.convert("RGBA").getchannel("A").histogram()[:256]
    return sum(hist[:255]) / (sum(hist) or 1) >= 0.001


def wants_sorted(path):
    """Whether a transparent material needs depth-sorted blending rather than
    an alpha cut-out.

    Both kinds have alpha between 0 and 255, so the mere presence of mid
    values says nothing - a cut-out mask has them along its antialiased edges.
    Two things separate them, measured on the mods ported so far:

        handrail (a DMU)     mid  2.6%, opaque 26.1%  -> cut-out
        interior (a DMU)     mid  0.0%, opaque 98.5%  -> cut-out with a hole
        window   (a DMU)     mid  100%, opaque  0.0%  -> glass
        window   (a loco)    mid  0.0%, opaque  0.0%  -> glass

    A lot of mid values means real translucency. So does having nothing opaque
    at all: a cut-out there would discard the whole surface, which is how
    one locomotive's windows would have vanished."""
    if not path:
        return False
    im = Image.open(path)
    if im.mode not in ("RGBA", "LA", "PA"):
        return False
    hist = im.convert("RGBA").getchannel("A").histogram()[:256]
    total = sum(hist) or 1
    return sum(hist[1:255]) / total > 0.2 or hist[255] / total < 0.05


def texture_sources(v):
    """The mod's own textures, keyed the way the materials reference them:
    "<parent folder>/<name>", lowercased. The parent is kept because a mod with
    one texture set per livery repeats file names across folders.

    The whole of res/textures bar ui/, as in build: some mods keep their textures
    outside res/textures/models/, and looking only there made every material
    look alpha-free - its glass came out opaque."""
    out = {}
    root0 = os.path.join(v.res, "textures")
    for root, dirs, files in os.walk(root0):
        if root == root0:
            dirs[:] = [d for d in dirs if d != "ui"]
        for fn in files:
            stem, ext = os.path.splitext(fn)
            if ext.lower() not in (".tga", ".dds"):
                continue
            parent = "" if root == root0 else os.path.basename(root)
            out[tex_key(parent, stem)] = os.path.join(root, fn)
    return out


def cmd_materials(v):
    tex = os.path.join(v.veh, "mat", "tex")
    os.makedirs(tex, exist_ok=True)
    stale = os.path.join(tex, FLAT_NORMAL)
    if os.path.exists(stale):
        os.remove(stale)        # superseded by the base game's default

    counts = collections.Counter({SOLID: 0, TRANSPARENT: 0})
    flat = tangentless_materials(v)
    for fn in sorted(os.listdir(os.path.join(v.veh, "mat"))):
        if not fn.endswith(".mtl"):
            continue
        p = os.path.join(v.veh, "mat", fn)
        txt = read(p)
        fixed_rg = default_normal_red_green(txt)
        if fixed_rg != txt:
            txt = fixed_rg
            write(p, txt)
        # the material's own type is the last one; earlier matches are the
        # samplers' type = "TWOD"
        matches = list(re.finditer(r'(?m)^(\s*)type = "([A-Z_0-9]+)",\s*$', txt))
        m = matches[-1] if matches else None
        if not m or m.group(2) not in RETYPEABLE:
            kind = settle_alpha_test(v, txt) if m and "TRANSPARENT" in m.group(2) else None
            if kind:
                write(p, kind[1])
                print("  left alone, alpha_test -> %s: %s (%s)" % (kind[0], fn, m.group(2)))
            else:
                print("  left alone: %s (%s)" % (fn, m.group(2) if m else "?"))
            continue

        # TF2's PHYS_TRANSPARENT was used for solid bodywork too, so the type
        # says nothing; only a real alpha channel does
        src = albedo_source(v, txt)
        transparent = uses_alpha(src)
        want = TRANSPARENT if transparent else SOLID
        if fn in flat:
            # the _NRML_MAP types need tangents, and a mesh without them
            # crashes the renderer outright (one DMU's windows killed Bulk
            # Generate with no error at all). Base has the plain types too.
            want = FLAT_TYPES[want]
        txt = txt[:m.start()] + '%stype = "%s",' % (m.group(1), want) + txt[m.end():]

        if transparent:
            txt = txt.replace("map_albedo = ", "map_albedo_opacity = ")
            txt = txt.replace("albedoTex = ", "albedoOpacityTex = ")
            # The editor warns when two transparent materials share an order
            # and are "neither sorted nor cutout" - their draw order is then
            # undefined. Which one a surface needs is in its alpha: only 0 and
            # 255 means a cut-out shape (handrails, grilles), intermediate
            # values mean real glass that has to be depth-sorted.
            kind = "sorted" if wants_sorted(src) else "cutout"
            txt = re.sub(r'(?m)^\t{3}alpha_test = \{.*?^\t{3}\},\n', "", txt,
                         flags=re.S)
            head = re.search(r'(?m)^\t\tparams = \{ ?\n', txt).end()
            txt = txt[:head] + ALPHA_TEST[kind] + txt[head:]
            print("  kept transparent (%s): %s" % (kind, fn))
        else:
            # a solid surface has nothing to cut out, and a leftover alpha_test
            # punches holes in the bodywork
            txt = re.sub(r'(?m)^\t{3}alpha_test = \{.*?^\t{3}\},\n', "", txt,
                         flags=re.S)
            # the solid types bind map_albedo/albedoTex; the transparent
            # family's names bind nothing and fall back to a checkerboard
            txt = txt.replace("map_albedo_opacity = ", "map_albedo = ")
            txt = txt.replace("albedoOpacityTex = ", "albedoTex = ")

        # the conversion drops these on older materials; newer ones already
        # carry them, so only fill in the samplers that are missing them
        def wrap(m):
            block = m.group(0)
            if "wrapS" in block:
                return block
            return re.sub(r'(?m)^(\t{6}type = "TWOD",) *$',
                          '\\1\n\t\t\t\t\t\twrapS = "REPEAT",'
                          '\n\t\t\t\t\t\twrapT = "REPEAT",', block)

        # The editor writes "albedoTex = { " with a trailing space; without
        # the ` *` this never matched an editor-written sampler at all.
        txt = re.sub(r'(?m)^\t{5}\w+ = \{ *\n(?:\t{6}[^\n]*\n)+?\t{5}\}, *\n',
                     wrap, txt)
        if "texcoord_scale" not in txt:
            close = txt.rindex("\t\t},\n\t\ttype = ")
            txt = txt[:close] + TEXCOORD_SCALE + txt[close:]
        # earlier runs pointed at a generated flat normal; move those over too
        txt = txt.replace('"tex/%s"' % FLAT_NORMAL,
                          '"%s"' % BASE_TEXTURES["default_normal_map"])

        # a normal map slot holding the albedo (one sleeper coach binds
        # its albedo to both): one file cannot be BC1 and BC5 at
        # once, and an albedo read as normals is nonsense anyway
        albedo = re.search(r'albedo(?:Opacity)?Tex = \{\s*fileName = "([^"]+)"', txt)
        if albedo:
            txt = re.sub(r'(normalTex = \{\s*fileName = )"%s"' % re.escape(albedo.group(1)),
                         '\\1"%s"' % BASE_TEXTURES["default_normal_map"], txt)
        if fn in flat:
            txt = re.sub(r'(?ms)^\t{3}(?:map_normal|normal_scale) = \{.*?^\t{3}\},\n',
                         "", txt)
        elif "map_normal" not in txt:
            anchor = re.search(r'(?m)^\t{3}map_metal_gloss_ao = \{.*?^\t{3}\},\n',
                               txt, re.S)
            if anchor:
                txt = txt[:anchor.end()] + MAP_NORMAL + txt[anchor.end():]

        write(p, txt)
        counts[want] += 1
    print(", ".join("%s: %d" % kv for kv in sorted(counts.items())))
