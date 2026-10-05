"""build: copy a TF2 mod into the TF3 staging area in TF3's layout.

Wipes the staging mod, so the Model Editor's Bulk Convert must follow.
"""
import collections
import io
import json
import os
import re
import shutil

from PIL import Image

from .common import read, tf3_name, write, write_stamp
from .dds import HEADER_LEN, dds_with_mips
from . import tf2base
from .paths import TF3_BASE, WORKSHOP


def block_end(lines, start):
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0:
            return i
    raise ValueError("unbalanced braces from line %d" % start)


def rebuild_configs(lines):
    """TF3's TF2-compat path wants one railVehicle config per LOD, each
    referring only to nodes that LOD actually has. TF2 shared a single config
    across all LODs, so later LODs get their axles filtered down and their
    index lists cleared (indices are per-LOD, authored against LOD 1)."""
    try:
        ci = next(i for i, l in enumerate(lines)
                  if re.match(r"^\s*configs = \{\s*$", l))
    except StopIteration:
        return lines, 0          # trailers and coaches have no config at all

    li = next(i for i, l in enumerate(lines) if re.match(r"^\s*lods = \{\s*$", l))
    lod_ranges, i = [], li + 1
    while not re.match(r"^\s*\},?\s*$", lines[i]):
        e = block_end(lines, i)
        lod_ranges.append((i, e))
        i = e + 1
    lod_meshes = [set(re.findall(r'mesh = "([^"]+)"', "\n".join(lines[s:e + 1])))
                  for s, e in lod_ranges]

    # count what is already there - some mods ship one config per
    # LOD already, and blindly appending copies leaves a mess
    cfg_ranges, i = [], ci + 1
    while not re.match(r"^\s*\},?\s*$", lines[i]):
        e = block_end(lines, i)
        cfg_ranges.append((i, e))
        i = e + 1
    if len(cfg_ranges) >= len(lod_ranges):
        return lines, len(lod_ranges)

    if not cfg_ranges:
        # `configs = { }` with no entries - the placeholder model a consist
        # points at. TF3 still indexes one config per LOD, so give it empty
        # ones; every field its code reads is simply absent.
        indent = re.match(r"(\s*)", lines[ci]).group(1)
        blank = ["%s\t{ }," % indent] * len(lod_ranges)
        return lines[:ci + 1] + blank + lines[ci + 1:], len(lod_ranges)

    src_cfg = lines[cfg_ranges[0][0]:cfg_ranges[0][1] + 1]
    out = []
    for k in range(len(cfg_ranges), len(lod_ranges)):
        for l in src_cfg:
            m = re.match(r'^(\s*axles = \{)(.*)(\},\s*)$', l)
            if m:
                kept = [x for x in re.findall(r'"([^"]+)"', m.group(2))
                        if x in lod_meshes[k]]
                out.append("%s%s %s" % (m.group(1),
                                        "".join(' "%s",' % x for x in kept),
                                        m.group(3).strip()))
                continue
            m = re.match(r'^(\s*\w*(?:Lights|Parts)\d? = \{).*(\},\s*)$', l)
            if m:
                out.append("%s %s" % (m.group(1), m.group(2).strip()))
                continue
            out.append(l)
    last = cfg_ranges[-1][1]
    return lines[:last + 1] + out + lines[last + 1:], len(lod_ranges)


def rebase_animation(text):
    """TF3 wants a keyframe at time 0; TF2 was happy without one.

    One EMU's door lights switch at the *end* of the closing animation
    (times {2958.33, 3000}), so shifting the times to zero would make the light
    go out the moment the doors start closing. Duplicating the first keyframe
    at time 0 holds the original pose until then - same behaviour, no warning.
    """
    tm = re.search(r'(times = \{\s*)([-0-9.,\s]+?)(\s*\},)', text)
    fm = re.search(r'(transfs = \{\s*)(\{[^}]*\},)', text)
    if not (tm and fm):
        return text, False
    times = [t for t in tm.group(2).replace("\n", " ").split(",") if t.strip()]
    if not times or float(times[0]) == 0:
        return text, False
    text = text[:tm.start(2)] + "0, " + text[tm.start(2):]
    fm = re.search(r'(transfs = \{\s*)(\{[^}]*\},)', text)
    return text[:fm.end(1)] + fm.group(2) + "\n\t\t\t" + text[fm.end(1):], True


NUM = r"\s*(-?[0-9.]+(?:[eE][-+]?\d+)?)\s*"


def inline_transf(text):
    """Evaluate TF2's transf helpers into literal matrices.

    Some TF2 models compute node positions in Lua (one DMU's emitters:
    transf.rotZYXTransl(transf.degToRad(0, 0, 0), vec3.new(9.243, 0.924, 2.6))).
    TF3 has no such helpers for a .mdl - degToRad is nil and the whole model
    fails to load (the editor exits during Bulk Validation). The formulas are
    TF2's own, from res/scripts/transf.lua."""
    import math

    def rot_zyx_transl(m):
        dx, dy, dz, x, y, z = (float(g) for g in m.groups())
        # degToRad(dx, dy, dz) -> vec3(rad dx, rad dy, rad dz); rotZYXTransl
        # reads rot.z as its "x" angle and rot.x as its "z" angle
        sx, sy, sz = (math.sin(math.radians(a)) for a in (dz, dy, dx))
        cx, cy, cz = (math.cos(math.radians(a)) for a in (dz, dy, dx))
        vals = [cy * cz, cy * sz, -sy, 0,
                -cx * sz + sx * sy * cz, cx * cz + sx * sy * sz, sx * cy, 0,
                sx * sz + cx * sy * cz, -sx * cz + cx * sy * sz, cx * cy, 0,
                x, y, z, 1]
        return "{ %s, }" % ", ".join(("%.9g" % (0.0 if abs(n) < 1e-12 else n))
                                     for n in vals)

    text = re.sub(r"transf\.rotZYXTransl\(\s*transf\.degToRad\(%s,%s,%s\)\s*,"
                  r"\s*vec3\.new\(%s,%s,%s\)\s*\)" % ((NUM,) * 6),
                  rot_zyx_transl, text)
    rest = re.findall(r"\b(?:transf|vec3|vec4)\.\w+", text)
    if not rest:
        text = re.sub(r'(?m)^local (?:transf|vec3|vec4) = require "\w+"\r?\n', "", text)
    else:
        print("  WARNING Lua helpers left in model: %s" % sorted(set(rest)))
    return text


def base_equivalent(path):
    """A TF2 base reference that TF3's base still has at the same path (the
    shared emissive materials, e.g. vehicle/train/emissive/train_all_lights.mtl),
    as ::/, or None.

    Not guessed beyond the same path: TF3 moved base vehicles' files into
    msh/ mat/ ani/ folders, and a TF2 .mdl pointed there failed in game - TF3
    had remodelled that vehicle, with other material groups. tf2base copies
    TF2's own files in instead."""
    return "::/" + path if "::/" + path in base_files() else None


def retarget_mdl(text, own_mtl=None, own_msh=None, own_ani=None):
    """TF2 resolves each resource kind against its own res/models/<kind> root;
    TF3 resolves everything against the .mdl's own folder. Keyed on the file
    name so it works whatever sub-tree the mod used.

    A mesh, material or animation the mod does not ship is TF2 base's; it gets
    a ::/ reference to wherever TF3's base keeps it (base_equivalent). Without
    the own_* sets (no build context) everything is taken as the mod's own."""
    def from_base(path, kind, own):
        if own is None or path.lower() in own:
            return None
        return base_equivalent(path)

    def msh(m):
        base = from_base(m.group(1), "msh", own_msh)
        if base:
            return '"%s"' % base
        return '"msh/%s/%s.msh"' % (tf3_name(m.group(2)), tf3_name(m.group(3)))

    text = re.sub(r'"((?:[^"]*/)?([^"/]+)/([^"/]+)\.msh)"', msh, text)

    def mtl(m):
        path, name = m.group(1), tf3_name(m.group(2))
        if own_mtl is None:
            return '"mat/%s.mtl"' % name
        if path.lower() in own_mtl:
            return '"mat/%s"' % own_mtl[path.lower()]
        base = base_equivalent(path)
        if base:
            return '"%s"' % base
        print("  WARNING material not in the mod nor in base: %s" % path)
        return '"mat/%s.mtl"' % name

    text = re.sub(r'"((?:[^"]*/)?([^"/]+)\.mtl)"', mtl, text)
    # animations keep their parent folder too: one mod has DOOR-AFR.ani under
    # both close_doors_right/ and open_doors_right/.
    # leave ::/ and / alone - those are base assets, not ours
    def ani(m):
        base = from_base(m.group(1), "ani", own_ani)
        if base:
            return '"%s"' % base
        return '"ani/%s/%s.ani"' % (tf3_name(m.group(2)), tf3_name(m.group(3)))

    text = re.sub(r'"(?!::/|/)((?:[^"]*?/)?([^"/]+)/([^"/]+)\.ani)"', ani, text)
    return text


def find_borrowed(keys):
    """Locate textures a mod references from a different mod."""
    want, found = set(keys), {}
    if not os.path.isdir(WORKSHOP):
        return found
    for mod in sorted(os.listdir(WORKSHOP)):
        root = os.path.join(WORKSHOP, mod, "res", "textures")
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            parent = tf3_name(os.path.basename(dirpath))
            for fn in files:
                stem, ext = os.path.splitext(fn)
                if ext.lower() not in (".tga", ".dds"):
                    continue
                key = "%s/%s%s" % (parent, tf3_name(stem), ext.lower())
                if key in want and key not in found:
                    found[key] = os.path.join(dirpath, fn)
        if len(found) == len(want):
            break
    return found


# TF2 mods reference the base game's shared dirt/rust/normal textures by their
# TF2 paths. TF3 keeps the same files under vehicle/shared, reachable with ::/.
BASE_TEXTURES = {
    "dirt_albedo": "::/vehicle/shared/mat/tex/dirt_albedo.dds",
    "dirt_normal": "::/vehicle/shared/mat/tex/dirt_normal.dds",
    "rust_albedo": "::/vehicle/shared/mat/tex/rust_albedo.dds",
    "rust_normal": "::/vehicle/shared/mat/tex/rust_normal.dds",
    "default_normal_map": "::/assets/shared/mat/tex/default_normal_map.dds",
}


def tex_key(parent, name):
    """How a texture is keyed and laid out under mat/tex/: "<parent>/<name>",
    or just "<name>" for one with no parent folder (res/textures/x.dds)."""
    name = tf3_name(name)
    return "%s/%s" % (tf3_name(parent), name) if parent else name


def retarget_mtl(text, own=None, borrowed=None):
    """Textures keep their immediate parent folder under mat/tex/ - flattening
    on the file name alone collides when a mod has one texture set per variant
    (one mod has the same cab texture under both of its two livery folders).

    `own` is the set of the mod's own textures, keyed "<parent>/<name>";
    anything not in it is a base game texture and gets a ::/ path."""
    # some TF2 mods ship a sampler with an empty fileName (one coach mod's light
    # material does); carried over it just logs a texture error every load
    text = re.sub(r'(?m)^\t\t[a-z_0-9]+ = \{\n(?:.*\n)*?\t\t\},\n',
                  lambda m: "" if re.search(
                      r'fileName = "(?:[^"]*/)?\.(?:tga|dds)"', m.group(0))
                      else m.group(0), text)

    def ref(m):
        parent, name, ext = m.group(1) or "", m.group(2), m.group(3)
        key = tex_key(parent, name)
        if own is None or key in own:
            return '"tex/%s.%s"' % (key, ext)
        base = BASE_TEXTURES.get(tf3_name(name))
        if base:
            return '"%s"' % base
        # not ours and not base: TF2 let a mod reach into another mod's
        # resources (one EMU uses a sibling mod's roll-sign texture). Record
        # it so build can copy the file in and keep the port self-contained.
        if borrowed is not None:
            borrowed.add("%s.%s" % (key, ext))
        return '"tex/%s.%s"' % (key, ext)

    # group 1 is the folder the file sits in. The leading path is greedy and
    # nested inside the optional group: with a lazy prefix outside it,
    # "LOCO-0/TEX.dds" lost its only folder to the prefix and came out as
    # "/tex.dds" (mods with models/<folder>/ had a level to spare and hid it)
    return re.sub(r'"(?:(?:[^"]*/)?([^"/]+)/)?([^"/]+)\.(tga|dds)"', ref, text)


def unique_node_names(text):
    """Make node names unique within the model.

    TF2 seats (and other groups) name their node by index; the conversion
    turns the index into the node's *name*. Some mods name nearly every
    node "Cube", so `group = 31` became `group = "Cube"` and TF3 seated the
    driver on whichever Cube it found first - out in the open, beside the
    train. TF2 refers to nodes by index only, so renaming is safe."""
    start = text.find("lods = {")
    end = text.find("metadata = {")
    if start < 0 or end < start:
        return text
    seen = collections.Counter()

    def rename(m):
        seen[m.group(2)] += 1
        n = seen[m.group(2)]
        return m.group(0) if n == 1 else '%sname = "%s_%d",' % (m.group(1), m.group(2), n)

    part = re.sub(r'(?m)^(\t+)name = "([^"]*)",', rename, text[start:end])
    return text[:start] + part + text[end:]


BUILD_STRINGS = "build_strings.json"


def lift_strings(v, text, stem):
    """Move non-ASCII _("...") literals out into translation keys.

    The Model Editor's conversion drops every non-ASCII character from the
    strings it writes back: a Japanese name followed by "Class 1000 ..."
    came out as just "1000 Class 1000 ...", so every vehicle named in
    Japanese lost its name and description. A plain ASCII key survives, and `strings` puts the
    original text into strings.json, which is how TF3 wants it anyway."""
    p = os.path.join(v.dst, "_metadata", BUILD_STRINGS)
    table = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    n = [0]

    def sub(m):
        raw = m.group(1)
        if all(ord(c) < 128 for c in raw):
            return m.group(0)
        text_ = re.sub(r'\\\r?\n', "\n", raw)
        text_ = text_.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        n[0] += 1
        key = "%s_%s_%d" % (v.mod_id, re.sub(r"[^a-z0-9_]+", "_", stem.lower()), n[0])
        table[key] = text_
        return '_("%s")' % key

    out = re.sub(r'_\(\s*"((?:[^"\\]|\\.)*)"\s*\)', sub, text, flags=re.S)
    if n[0]:
        write(p, json.dumps(table, indent=4, ensure_ascii=False) + "\n")
    return out


MODEL_MAP = "model_names.json"


def model_names(vehicles):
    """TF2 model path (lowercase, relative to res/models/model) -> .mdl name
    in the flat TF3 folder. One mod has vehicle/train/dmu.mdl and
    vehicle/train/<livery>/dmu.mdl - two liveries, one name - and flattening
    kept only one. The shallowest keeps the plain name, the rest get their
    parent folder in front."""
    out, by_name = {}, collections.defaultdict(list)
    for rel in vehicles:
        by_name[tf3_name(os.path.basename(rel))].append(rel)
    for name, rels in by_name.items():
        rels.sort(key=lambda r: (r.count("/"), r))
        out[rels[0]] = name
        for rel in rels[1:]:
            out[rel] = tf3_name("%s_%s" % (os.path.basename(os.path.dirname(rel)), name))
            print("  same model name %s: %s -> %s" % (name, rel, out[rel]))
    return out


def model_ref(v, ref):
    """A TF2 reference to one of this mod's models -> its TF3 file name."""
    p = os.path.join(v.dst, "_metadata", MODEL_MAP)
    m = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return m.get(ref.lower(), tf3_name(os.path.basename(ref)))


class MaterialNames(dict):
    """TF2 material path (lowercase, relative to res/models/material) ->
    file name under mat/. `.sources` holds the original file for each."""


def material_names(v):
    """Which TF2 materials to bring over, and what to call them.

    Only the ones some model references: one mod ships an fbx_import/ folder
    of the author's leftovers. Names are the file name, flattened - except
    where two referenced files share a name but differ (that same mod has
    one body material under three folders); those keep their parent
    folder in the name. Flattening on the name alone let the leftover win
    and two of its cars came out as checkerboards."""
    root = os.path.join(v.res, "models", "material")
    refs = set()
    for r, _, fs in os.walk(os.path.join(v.res, "models", "model")):
        for f in fs:
            if f.endswith(".mdl"):
                refs.update(x.lower() for x in re.findall(
                    r'"([^"]+\.mtl)"', read(os.path.join(r, f))))
    files = {}
    for r, _, fs in os.walk(root):
        for f in fs:
            if f.endswith(".mtl"):
                rel = os.path.relpath(os.path.join(r, f), root).replace(os.sep, "/")
                if rel.lower() in refs:
                    files[rel.lower()] = os.path.join(r, f)
    by_name = collections.defaultdict(list)
    for rel in files:
        by_name[tf3_name(os.path.basename(rel))].append(rel)
    out = MaterialNames()
    out.sources = files
    for name, rels in by_name.items():
        distinct = len(set(read(files[r]) for r in rels)) > 1
        for rel in rels:
            parent = os.path.basename(os.path.dirname(rel))
            out[rel] = tf3_name("%s_%s" % (parent, name)) if distinct else name
        if distinct:
            print("  %d different materials named %s - kept apart by folder"
                  % (len(rels), name))
    return out


def shipped(src_root):
    """The files under a TF2 resource root, as lowercase paths relative to it
    - the form a .mdl refers to them by."""
    out = set()
    for root, _, files in os.walk(src_root):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), src_root)
            out.add(rel.replace(os.sep, "/").lower())
    return out


def copy_flat(src_root, dst_root, keep_parent=False, exts=None, skip=()):
    """Mirror a TF2 resource tree into one flat (or one-level) TF3 folder.
    `skip` names top-level folders under src_root to leave out."""
    copied, seen = 0, {}
    if not os.path.isdir(src_root):
        return 0, []
    for root, dirs, files in os.walk(src_root):
        if root == src_root:
            dirs[:] = [d for d in dirs if d not in skip]
        for fn in sorted(files):
            if exts and os.path.splitext(fn)[1].lower() not in exts:
                continue
            parts = [tf3_name(fn)]
            # files directly in src_root have no parent folder to keep (several
            # mods put textures straight into res/textures/)
            if keep_parent and root != src_root:
                parts.insert(0, tf3_name(os.path.basename(root)))
            rel = os.path.join(*parts)
            dst = os.path.join(dst_root, rel)
            if rel in seen:
                print("  name clash: %s and %s" % (seen[rel], os.path.join(root, fn)))
            seen[rel] = os.path.join(root, fn)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(root, fn), dst)
            copied += 1
    return copied, sorted(seen)


def cmd_build(v):
    if os.path.exists(v.dst):
        shutil.rmtree(v.dst)
    tmp = tf2base.overlay(v, lambda ref: base_equivalent(ref) is not None)
    try:
        _build(v)
    finally:
        if tmp:
            v._res = None
            shutil.rmtree(tmp, ignore_errors=True)


def _build(v):

    nmsh, _ = copy_flat(os.path.join(v.res, "models", "mesh"),
                        os.path.join(v.veh, "msh"), keep_parent=True)
    nani, _ = copy_flat(os.path.join(v.res, "models", "animation"),
                        os.path.join(v.veh, "ani"), keep_parent=True,
                        exts={".ani"})
    own_msh = shipped(os.path.join(v.res, "models", "mesh"))
    own_ani = shipped(os.path.join(v.res, "models", "animation"))
    rebased = 0
    for root, _, files in os.walk(os.path.join(v.veh, "ani")):
        for fn in files:
            p = os.path.join(root, fn)
            fixed, changed = rebase_animation(read(p))
            if changed:
                write(p, fixed)
                rebased += 1
    # TF2 .tga stay here until convert_textures replaces them; the editor's
    # Bulk Convert needs them present or it drops the samplers.
    # Most mods keep model textures under res/textures/models/, but TF2
    # resolves a material's fileName against res/textures/ itself, and some
    # mods put them straight there (res/textures/<loco>/). Take the whole tree
    # bar the UI icons, which are not model textures.
    ntex, tex_paths = copy_flat(os.path.join(v.res, "textures"),
                                os.path.join(v.veh, "mat", "tex"),
                                keep_parent=True,
                                exts={".tga", ".dds"}, skip=("ui",))
    own = set(os.path.splitext(p.replace(os.sep, "/"))[0] for p in tex_paths)
    # later steps all read mat/; a mod that only rewrites a base vehicle's
    # .mdl ships no materials, so make sure it exists
    os.makedirs(os.path.join(v.veh, "mat"), exist_ok=True)

    nmtl, borrowed = 0, set()
    mtl_map = material_names(v)
    for rel, name in sorted(mtl_map.items()):
        src = mtl_map.sources[rel]
        write(os.path.join(v.veh, "mat", name),
              retarget_mtl(read(src), own, borrowed))
        nmtl += 1
    own_mtl = mtl_map

    # pull in whatever this mod borrowed from another mod, so the port stands
    # on its own rather than depending on a TF2 mod the player will not have
    missing = set()
    if borrowed:
        found = find_borrowed(borrowed)
        for key in sorted(borrowed):
            src = found.get(key)
            dst = os.path.join(v.veh, "mat", "tex", key.replace("/", os.sep))
            if src:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                print("  borrowed %-52s from %s" % (
                    key, os.path.basename(os.path.dirname(os.path.dirname(
                        os.path.dirname(os.path.dirname(src)))))))
            else:
                missing.add(key)

    # res/models/group/*.grp is TF2-only: TF3 rejects the extension and the
    # .mdl inlines the same nodes anyway.

    nmdl = 0
    mdl_root = os.path.join(v.res, "models", "model")
    vehicles = {}
    for root, _, files in os.walk(mdl_root):
        for fn in sorted(f for f in files if f.endswith(".mdl")):
            body = read(os.path.join(root, fn))
            # TF2 consists pointed at an empty placeholder model via
            # groupFileName (`consists` regroups them on a real consist),
            # so it is dead weight - and Bulk Generate crashes on it, because a model with a
            # zero bounding box gives Vulkan a zero-sized render target.
            if 'mesh = "' not in body:
                print("  %-28s skipped (no meshes, unreferenced)" % fn)
                continue
            # not a vehicle: an author's leftover (an fbx_import.mdl),
            # a consist's group head (an empty display model), or the parts
            # some authors keep in model/asset/ under the vehicles' own names.
            # TF3 lists them as nameless entries.
            if "railVehicle" not in body:
                print("  %-28s skipped (no railVehicle - not a vehicle)" % fn)
                continue
            rel = os.path.relpath(os.path.join(root, fn), mdl_root)
            vehicles[rel.replace(os.sep, "/").lower()] = (fn, body)

    model_map = model_names(vehicles)
    for rel, (fn, body) in sorted(vehicles.items()):
        name = model_map[rel]
        body = inline_transf(body)
        body = unique_node_names(body)
        body = lift_strings(v, body, os.path.splitext(name)[0])
        lines, nlods = rebuild_configs(body.split("\n"))
        write(os.path.join(v.veh, name),
              retarget_mdl("\n".join(lines), own_mtl, own_msh, own_ani))
        print("  %-28s -> %-28s lods=%d" % (fn, name, nlods))
        nmdl += 1
    write(os.path.join(v.dst, "_metadata", MODEL_MAP),
          json.dumps(model_map, indent=4, ensure_ascii=False) + "\n")

    nmtl -= drop_unused_materials(v)
    missing = point_at_base(v, missing)
    patch_missing_textures(v, missing)

    write_mod_files(v)
    write_stamp(v)
    print("meshes %d, animations %d (%d rebased), textures %d, materials %d, models %d"
          % (nmsh, nani, rebased, ntex, nmtl, nmdl))
    bad = [os.path.join(r, f) for r, _, fs in os.walk(v.veh) for f in fs
           if f != f.lower()]
    print("paths with uppercase: %d" % len(bad))
    print("staging: %s" % v.dst)


def drop_unused_materials(v):
    """TF2 mods often ship leftover materials no model uses (one locomotive mod has four,
    some pointing at textures that were never shipped). Only .mdl files
    reference materials, so anything they do not name is dead weight - and a
    source of missing-texture noise in validation."""
    used = set()
    for fn in os.listdir(v.veh):
        if fn.endswith(".mdl"):
            used.update(re.findall(r'"mat/([^"]+\.mtl)"',
                                   read(os.path.join(v.veh, fn))))
    mat = os.path.join(v.veh, "mat")
    # a mod that only rewrites a base vehicle's .mdl ships no materials
    if not os.path.isdir(mat):
        return 0
    dropped = sorted(f for f in os.listdir(mat)
                     if f.endswith(".mtl") and f not in used)
    for f in dropped:
        os.remove(os.path.join(mat, f))
    if dropped:
        print("  dropped %d materials no model uses: %s"
              % (len(dropped), ", ".join(dropped)))
    return len(dropped)


_base_index = None

_base_files = None


def base_textures():
    """Every .dds in TF3's base, by lowercase file name -> list of ::/ paths.

    The zips start with Urban Games' own "UG" signature, but only the first
    local header carries it; the central directory is standard, so zipfile
    can list them (it just cannot extract that first entry)."""
    global _base_index, _base_files
    if _base_index is None:
        import zipfile
        _base_index = collections.defaultdict(list)
        _base_files = set()
        for root, _, files in os.walk(TF3_BASE):
            rel = os.path.relpath(root, TF3_BASE).replace("\\", "/")
            rel = "" if rel == "." else rel + "/"
            for f in files:
                if not f.endswith(".zip"):
                    continue
                for n in zipfile.ZipFile(os.path.join(root, f)).namelist():
                    _base_files.add("::/" + rel + n)
                    if n.lower().endswith(".dds"):
                        _base_index[os.path.basename(n).lower()].append(
                            "::/" + rel + n)
    return _base_index


def base_files():
    """Every file path in TF3's base, as ::/ references."""
    base_textures()
    return _base_files


def point_at_base(v, missing):
    """Missing textures that TF3's base has under the same file name.

    TF2 mods reach into TF2's base by its paths (a steam engine's coal is
    "terrain/coal_albedo.dds"); TF3 often keeps the same file somewhere else
    (::/terrain/materials/coal/tex/coal_albedo.dds). With several candidates
    the one whose path contains the TF2 folder name wins, then vehicle/
    assets, then the shortest. Returns what is still missing."""
    if not missing:
        return missing
    idx = base_textures()
    found = {}
    for key in missing:
        parent, _, fn = key.rpartition("/")
        # ::/placeholders/ holds the editor's stand-in art (unknown_texture
        # and friends) - a checkerboard is no better than the stand-ins below
        cands = [c for c in idx.get(os.path.splitext(fn)[0] + ".dds", [])
                 if not c.startswith("::/placeholders/")]
        if not cands:
            continue
        cands = sorted(cands, key=lambda p: (
            not (parent and "/%s/" % parent in p), "/vehicle/" not in p, len(p)))
        found[key] = cands[0]
    if not found:
        return missing
    mat = os.path.join(v.veh, "mat")
    for fn in os.listdir(mat):
        if fn.endswith(".mtl"):
            p = os.path.join(mat, fn)
            txt = read(p)
            new = txt
            for key, path in found.items():
                new = new.replace('"tex/%s"' % key, '"%s"' % path)
            if new != txt:
                write(p, new)
    for key, path in sorted(found.items()):
        print("  from base: %-40s -> %s" % (key, path))
    return set(missing) - set(found)


# A texture referenced by a material but shipped nowhere - not in the mod, not
# in base, not in any installed mod. TF2 drew something in its place, so the
# original looked fine; TF3 reports it as missing. What to put there depends on
# what the sampler does.
FALLBACK_WHITE = "fallback/white"


def patch_missing_textures(v, missing):
    """Point each missing texture at a stand-in suited to its sampler:

    map_emissive  a generated white texture, so the glow colour comes from
                  emissiveScale alone (one mod's lights use "unknown_texture.tga",
                  which exists in neither TF2 nor TF3)
    map_normal    base's flat default normal map

    Anything else is left and reported: an albedo or mga has no neutral
    substitute, and making one up would hide a real gap."""
    if not missing:
        return
    mat = os.path.join(v.veh, "mat")
    fixed, left = collections.Counter(), set()
    need_white = False
    for fn in sorted(f for f in os.listdir(mat) if f.endswith(".mtl")):
        p = os.path.join(mat, fn)
        txt = read(p)

        def block(m):
            nonlocal need_white
            name, body = m.group(1), m.group(0)
            for key in missing:
                ref = '"tex/%s"' % key
                if ref not in body:
                    continue
                if name == "map_emissive":
                    body = body.replace(ref, '"tex/%s.dds"' % FALLBACK_WHITE)
                    need_white = True
                elif name == "map_normal":
                    body = body.replace(
                        ref, '"%s"' % BASE_TEXTURES["default_normal_map"])
                else:
                    left.add("%s: %s %s" % (fn, name, key))
                    continue
                fixed[name] += 1
            return body

        new = re.sub(r'(?ms)^\t\t(\w+) = \{\n.*?^\t\t\},\n', block, txt)
        if new != txt:
            write(p, new)
    if need_white:
        # written as .dds directly: `textures` only converts the mod's own
        # .tga, and this one has no TF2 original
        dst = os.path.join(mat, "tex", FALLBACK_WHITE + ".dds")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # 4x4 is rejected by validation as "too small"; base's own emissive
        # atlas is 128x128
        white = Image.new("RGB", (64, 64), (255, 255, 255))
        levels = [white.resize((64 >> i, 64 >> i)) for i in range(7)]

        def encode_level(level):
            buf = io.BytesIO()
            level.save(buf, format="DDS", pixel_format="DXT1")
            raw = buf.getvalue()
            return raw[:HEADER_LEN], raw[HEADER_LEN:]

        open(dst, "wb").write(dds_with_mips(levels, encode_level))
    for name, n in sorted(fixed.items()):
        print("  missing texture -> stand-in: %s x%d" % (name, n))
    for l in sorted(left):
        print("  MISSING  %s (no stand-in for this sampler)" % l)


def write_mod_files(v):
    c = v.cfg
    mod = {
        "cosmetic": True,
        "dependencies": None,
        "incompatibilities": None,
        "modId": v.mod_id,
        "options": None,
        "params": None,
        "postRunScript": {"fileName": ""},
        "preRunScript": {"fileName": ""},
        "revision": 1,
        "runScript": {"fileName": ""},
        "severityAdd": "None",
        "severityRemove": "None",
    }
    info = {
        "authors": c.get("authors", []),
        "description": c.get("description", ""),
        "name": c["modName"],
        "tags": c.get("tags", ["Vehicle", "Train"]),
        "url": "",
    }
    write(os.path.join(v.dst, "mod.json"), json.dumps(mod, indent=4) + "\n")
    write(os.path.join(v.dst, "_metadata", "modinfo.json"),
          json.dumps(info, indent=4) + "\n")

    # Two images: the gallery falls back to image_00.tga at the mod root
    # (TF2's name), the upload cover must be _metadata/0.png at 1280x720.
    # Without either image the Model Editor leaves the mod out of its list
    # altogether ("Set current mod: " with nothing after it), and then
    # crashes on the Tools tab's Target mod index running past the end.
    # One mod shipped workshop_preview.jpg instead of image_00.tga.
    cover = next((os.path.join(v.src, f) for f in
                  ("image_00.tga", "workshop_preview.jpg", "workshop_preview.png")
                  if os.path.exists(os.path.join(v.src, f))), None)
    if cover:
        im = Image.open(cover).convert("RGB")
    else:
        print("  no cover image in the source - writing a plain one")
        im = Image.new("RGB", (1280, 720), (40, 44, 52))
    if cover and cover.endswith(".tga"):
        shutil.copy2(cover, os.path.join(v.dst, "image_00.tga"))
    else:
        im.save(os.path.join(v.dst, "image_00.tga"))
    w, h = im.size
    side = min(w, int(h * 16 / 9))
    im = im.crop(((w - side) // 2, 0, (w + side) // 2,
                  min(h, int(side * 9 / 16))))
    im.resize((1280, 720), Image.LANCZOS).save(
        os.path.join(v.dst, "_metadata", "0.png"))
