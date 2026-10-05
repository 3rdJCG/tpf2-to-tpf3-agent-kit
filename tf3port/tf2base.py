"""Files a mod takes from TF2 itself - its base game and DLC - copied in.

Some mods ship only a rewritten .mdl and use the meshes, materials and
textures of a vehicle that came with TF2 (one turns a DLC tram into a rail
vehicle). TF3 may have the same vehicle, but remodelled: its meshes have
other names and other material groups, so the TF2 .mdl cannot use them
(the game rejects the model: "Group 'body' has N materials but mesh has N
groups"). The files that fit are TF2's own, so they are taken from the
player's TF2 install, the same way files borrowed from other workshop mods
are, and from then on are converted like the mod's own.

Only on your machine: the files go into staging, which you do not
distribute. Needs TF2 installed (`tf2` in local_settings.json if it is not
found); without it, build warns and the parts are left out by convert.
"""
import os
import re
import shutil
import tempfile
import zipfile

from .paths import TF2

_index = None


def index():
    """lowercase path relative to res/ -> (zip file or None, member or file).

    TF2 keeps its base files in res/models/<kind>.zip (members "mesh/...")
    and res/textures/*.zip plus loose folders; each DLC in
    dlcs/<dlc>/res/*.zip (members "models/...", "textures/...")."""
    global _index
    if _index is not None:
        return _index
    _index = {}
    if not TF2:
        return _index
    roots = [os.path.join(TF2, "res")]
    dlcs = os.path.join(TF2, "dlcs")
    if os.path.isdir(dlcs):
        roots += [os.path.join(dlcs, d, "res") for d in sorted(os.listdir(dlcs))
                  if os.path.isdir(os.path.join(dlcs, d, "res"))]
    for res in roots:
        for d, _, files in os.walk(res):
            rel_dir = os.path.relpath(d, res).replace(os.sep, "/")
            prefix = "" if rel_dir == "." else rel_dir + "/"
            # only model files and textures; audio, maps and the rest are not used
            if prefix and not prefix.startswith(("models/", "textures/")):
                continue
            for fn in files:
                p = os.path.join(d, fn)
                if fn.endswith(".zip"):
                    try:
                        names = zipfile.ZipFile(p).namelist()
                    except zipfile.BadZipFile:
                        continue
                    for n in names:
                        if not n.endswith("/"):
                            _index.setdefault((prefix + n).lower(), (p, n))
                elif prefix:
                    _index.setdefault((prefix + fn).lower(), (None, p))
    return _index


def _extract(key, dst):
    zp, member = index()[key]
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if zp is None:
        shutil.copy2(member, dst)
    else:
        with zipfile.ZipFile(zp) as z, z.open(member) as f, open(dst, "wb") as out:
            shutil.copyfileobj(f, out)


KINDS = {".msh": "mesh", ".mtl": "material", ".ani": "animation"}


def _shipped(res, rel):
    return os.path.exists(os.path.join(res, rel.replace("/", os.sep)))


def overlay(v, in_tf3_base):
    """If the mod's models use TF2 files it does not ship, make a copy of its
    res/ with those added and point v.res at it. `in_tf3_base(path)` says a
    reference already resolves in TF3's base unchanged (shared assets such as
    the emissive materials), which TF3's own version serves better.
    Returns the temporary folder to delete afterwards, or None."""
    res = v.res
    want = set()
    for d, _, files in os.walk(os.path.join(res, "models", "model")):
        for fn in files:
            if not fn.endswith(".mdl"):
                continue
            text = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
            for ref in re.findall(r'"([^":"]+\.(?:msh|mtl|ani))"', text):
                if ref.startswith("/"):
                    continue
                rel = "models/%s/%s" % (KINDS[os.path.splitext(ref)[1]], ref)
                if not _shipped(res, rel) and not in_tf3_base(ref):
                    want.add(rel)
    if not want:
        return None
    if not TF2:
        print("  WARNING %d files come from TF2 itself, which was not found "
              "(set \"tf2\" in local_settings.json)" % len(want))
        return None
    idx = index()
    tmp = tempfile.mkdtemp(prefix="tf2base_")
    merged = os.path.join(tmp, "res")
    shutil.copytree(res, merged)
    got = {"mesh": 0, "material": 0, "animation": 0, "texture": 0}
    missing = []
    textures = set()
    for rel in sorted(want):
        if rel.lower() not in idx:
            missing.append(rel)
            continue
        _extract(rel.lower(), os.path.join(merged, rel))
        kind = rel.split("/")[1]
        got[kind] += 1
        if rel.endswith(".msh") and rel.lower() + ".blob" in idx:
            _extract(rel.lower() + ".blob", os.path.join(merged, rel + ".blob"))
        if rel.endswith(".mtl"):
            text = open(os.path.join(merged, rel), encoding="utf-8", errors="replace").read()
            textures.update(re.findall(r'fileName\s*=\s*"([^":"]+\.(?:dds|tga))"', text))
    for t in sorted(textures):
        rel = "textures/" + t
        if _shipped(merged, rel):
            continue
        if rel.lower() in idx:
            _extract(rel.lower(), os.path.join(merged, rel))
            got["texture"] += 1
    print("  from TF2 itself: %d meshes, %d materials, %d animations, %d textures"
          % (got["mesh"], got["material"], got["animation"], got["texture"]))
    for rel in missing:
        print("  WARNING not in the mod, TF3 or TF2: %s" % rel)
    v._res = merged
    return tmp
