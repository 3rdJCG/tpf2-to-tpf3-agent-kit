"""textures: TGA/DDS to the DDS formats TF3 expects, flipped and mipmapped."""
import collections
import io
import os
import re
import struct

from PIL import Image

from .build import tex_key
from .common import read, write
from .dds import DX10_LEN, HEADER_LEN, dds_with_mips, fix_dds_header, pot
from .materials import texture_sources


def formats_from_materials(v):
    """The editor is strict about this and says so: DXT5 only where the alpha
    is the opacity, DXT1 for opaque albedo and for metal/gloss/ao."""
    fmt, mga = {}, set()
    mat = os.path.join(v.veh, "mat")
    for fn in sorted(os.listdir(mat)):
        if not fn.endswith(".mtl"):
            continue
        txt = read(os.path.join(mat, fn))
        for sampler, f in (("albedoOpacityTex", "DXT5"),
                           ("albedoTex", "DXT1"),
                           ("metalGlossAoTex", "DXT1"),
                           ("normalTex", "BC5U")):
            for m in re.finditer(
                    sampler + r'.*?fileName = "tex/([^"]+?)\.(?:dds|tga)"', txt, re.S):
                fmt[m.group(1)] = f
                if sampler == "metalGlossAoTex":
                    mga.add(m.group(1))
    return fmt, mga


def cmd_textures(v):
    tex = os.path.join(v.veh, "mat", "tex")
    # a mod that already ships .dds needs no conversion; only the
    # .tga are ours to rewrite
    sources = {k: p for k, p in texture_sources(v).items()
               if p.lower().endswith(".tga")}

    # clear only what this step owns - the flat normal has no TF2 counterpart
    for root, _, files in os.walk(tex):
        for stale in files:
            stem, ext = os.path.splitext(stale.lower())
            parent = "" if root == tex else os.path.basename(root).lower()
            key = tex_key(parent, stem)
            if ext in (".tga", ".dds") and key in sources:
                os.remove(os.path.join(root, stale))

    fmt, mga = formats_from_materials(v)
    counts = {"DXT1": 0, "DXT5": 0, "BC5U": 0}
    invert = v.cfg.get("invertMgaGreen", True)
    for stem in sorted(sources):
        f = fmt.get(stem, "DXT5")      # unreferenced textures stay alpha-safe
        im = Image.open(sources[stem]).convert("RGBA" if f == "DXT5" else "RGB")
        # TGA is bottom-up (OpenGL), DDS top-down (DirectX); the UVs are TF2's,
        # so without this the model samples the wrong rows of the atlas
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
        if f == "BC5U":
            # flipping the image flips the surface's Y, so the normal's green
            # channel has to flip with it or every bump reads inside-out
            r, g, b = im.split()[:3]
            im = Image.merge("RGB", (r, g.point(lambda x: 255 - x), b))
        elif stem in mga and invert:
            # TF2's green is gloss (0 = matte), TF3 reads roughness
            # (0 = mirror-smooth)
            r, g, b = im.split()[:3]
            im = Image.merge("RGB", (r, g.point(lambda x: 255 - x), b))
        orig = im.size
        w, h = pot(im.size[0]), pot(im.size[1])
        resized = (w, h) != im.size
        if resized:
            # UVs are normalised, so rescaling is safe; cropping would not be
            im = im.resize((w, h), Image.LANCZOS)

        levels, (lw, lh) = [im], im.size
        while lw > 1 or lh > 1:
            lw, lh = max(1, lw // 2), max(1, lh // 2)
            levels.append(im.resize((lw, lh), Image.LANCZOS))

        def encode_level(level, f=f):
            buf = io.BytesIO()
            level.save(buf, format="DDS",
                       pixel_format="BC5" if f == "BC5U" else f)
            raw = buf.getvalue()
            if f != "BC5U":
                return raw[:HEADER_LEN], raw[HEADER_LEN:]
            # Pillow emits BC5 under a DX10 header; the base game uses the
            # legacy BC5U fourCC, with the same block payload
            head = bytearray(raw[:HEADER_LEN])
            head[84:88] = b"BC5U"
            return head, raw[HEADER_LEN + DX10_LEN:]

        dst = os.path.join(tex, stem.replace("/", os.sep) + ".dds")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(dds_with_mips(levels, encode_level))
        counts[f] += 1
        note = "  -> %dx%d (power of two)" % im.size if resized else ""
        print("  %-36s %4dx%-4d %s mips=%-3d%s"
              % (stem, orig[0], orig[1], f, len(levels), note))

    # A mod that already ships .dds still has to match what each sampler
    # wants; the editor is explicit ("please use BC1/DXT1 for opaque
    # textures", "please use BC5/ATI2N for normal maps").
    fixed = collections.Counter()
    for key, want in sorted(fmt.items()):
        if key in sources:
            continue                      # produced from .tga above
        path = os.path.join(tex, key.replace("/", os.sep) + ".dds")
        if not os.path.exists(path):
            continue
        raw = open(path, "rb").read()
        got = raw[84:88].decode("latin1")
        w, h = struct.unpack_from("<I", raw, 16)[0], struct.unpack_from("<I", raw, 12)[0]
        pot_ok = not (w & (w - 1) or h & (h - 1))
        if got == want and pot_ok:
            # still repair the header in place: earlier runs wrote bad fields
            fixed_head = fix_dds_header(raw[:HEADER_LEN], w, h, got)
            if fixed_head != raw[:HEADER_LEN]:
                open(path, "wb").write(fixed_head + raw[HEADER_LEN:])
                fixed[(got, want, "header repaired")] += 1
            continue
        if got == "DX10" and struct.unpack_from("<I", raw, 128)[0] == 83 \
                and want == "BC5U":
            # already BC5, only the header style differs - rewrite it rather
            # than re-encoding and losing quality
            head = bytearray(raw[:HEADER_LEN])
            head[84:88] = b"BC5U"
            open(path, "wb").write(bytes(head) + raw[HEADER_LEN + DX10_LEN:])
            fixed[(got, want, "header")] += 1
            continue
        im = Image.open(path)
        im = im.convert("RGBA" if want == "DXT5" else "RGB")
        if not pot_ok:
            # UVs are normalised, so rescaling is safe
            im = im.resize((pot(w), pot(h)), Image.LANCZOS)
        levels, (lw, lh) = [im], im.size
        while lw > 1 or lh > 1:
            lw, lh = max(1, lw // 2), max(1, lh // 2)
            levels.append(im.resize((lw, lh), Image.LANCZOS))

        def encode_level(level, want=want):
            buf = io.BytesIO()
            level.save(buf, format="DDS",
                       pixel_format="BC5" if want == "BC5U" else want)
            out = buf.getvalue()
            if want != "BC5U":
                return out[:HEADER_LEN], out[HEADER_LEN:]
            head = bytearray(out[:HEADER_LEN])
            head[84:88] = b"BC5U"
            return head, out[HEADER_LEN + DX10_LEN:]

        open(path, "wb").write(dds_with_mips(levels, encode_level))
        fixed[(got, want, "re-encoded")] += 1
    # sweep every .dds, not just the samplers we classify: a mod can bind a
    # texture to one we do not track (one EMU has an emissiveTex) and it
    # still has to be power-of-two with a sane header
    for root, _, files in os.walk(tex):
        for fn in sorted(files):
            if not fn.lower().endswith(".dds"):
                continue
            path = os.path.join(root, fn)
            raw = open(path, "rb").read()
            got = raw[84:88].decode("latin1")
            w = struct.unpack_from("<I", raw, 16)[0]
            h = struct.unpack_from("<I", raw, 12)[0]
            # validation rejects tiny textures ("too small, dimension 4x4" -
            # one EMU's mga.dds); 64 is known to pass
            tiny = min(w, h) < 16
            # and huge ones: "huge dimension 8192x8192" (one DMU's body
            # colour mask); 4096 passes
            huge = max(w, h) > 4096
            if w & (w - 1) or h & (h - 1) or tiny or huge:
                im = Image.open(path).convert(
                    "RGBA" if got in ("DXT5", "DXT3") else "RGB")
                size = (max(64, pot(w)), max(64, pot(h))) if tiny else (pot(w), pot(h))
                if huge:
                    scale = 4096.0 / max(size)
                    size = (max(1, int(size[0] * scale)), max(1, int(size[1] * scale)))
                im = im.resize(size, Image.LANCZOS)
                levels, (lw, lh) = [im], im.size
                while lw > 1 or lh > 1:
                    lw, lh = max(1, lw // 2), max(1, lh // 2)
                    levels.append(im.resize((lw, lh), Image.LANCZOS))

                def encode_level(level, got=got):
                    buf = io.BytesIO()
                    level.save(buf, format="DDS",
                               pixel_format="BC5" if got == "BC5U" else got)
                    out = buf.getvalue()
                    if got != "BC5U":
                        return out[:HEADER_LEN], out[HEADER_LEN:]
                    head = bytearray(out[:HEADER_LEN])
                    head[84:88] = b"BC5U"
                    return head, out[HEADER_LEN + DX10_LEN:]

                open(path, "wb").write(dds_with_mips(levels, encode_level))
                fixed[(got, got, "power of two")] += 1
                continue
            head = fix_dds_header(raw[:HEADER_LEN], w, h, got)
            if head != raw[:HEADER_LEN]:
                open(path, "wb").write(head + raw[HEADER_LEN:])
                fixed[(got, got, "header repaired")] += 1

    for (got, want, how), n in sorted(fixed.items()):
        print("  %-5s -> %-5s  %3d  (%s)" % (got, want, n, how))

    n = 0
    for fn in sorted(os.listdir(os.path.join(v.veh, "mat"))):
        if not fn.endswith(".mtl"):
            continue
        p = os.path.join(v.veh, "mat", fn)
        txt = read(p)
        new = re.sub(r'(fileName = "[^"]+?)\.tga"', r'\1.dds"', txt)
        if new != txt:
            write(p, new)
            n += 1
    print("%s, %d materials retargeted to .dds" % (counts, n))
