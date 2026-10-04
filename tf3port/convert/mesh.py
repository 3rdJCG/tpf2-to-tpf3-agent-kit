"""B-1: TF2 .msh/.blob -> TF3, without the Model Editor.

A mesh is a .msh index plus a .blob of raw arrays. The .msh names each
array's byte range: `vertexAttr.<attr>` for the vertex data, and
`subMeshes[i].indices.<attr>` for each submesh's index lists. TF3 wants the
blob laid out in one canonical order - every vertex array, then each
submesh's index arrays, each group in ATTR_ORDER - with the offsets packed
from 0. The bytes themselves are not touched.

Checked against Bulk Convert on 31 vehicles (port.py compare-convert mesh):
27 already shipped TF3's layout and only get the .msh reformatted; old
Train Fever converter output (in several older mods) put the indices first or
the attributes in another order and gets the blob rearranged.

The editor also drops the TF2 leftovers `matConfigs`, `subMeshes[i].materials`
and `animations` (materials live in the .mdl), so this does too.
"""
import os

from . import luadata

ATTR_ORDER = ("position", "uv0", "normal", "tangent", "uv1")

DROPPED = ("matConfigs", "animations")


class MeshError(ValueError):
    pass


def _ordered(group, where):
    unknown = set(group) - set(ATTR_ORDER)
    if unknown:
        # a new attribute's place in the layout is a guess; stop rather than
        # write a blob the game reads as garbage
        raise MeshError("%s: unknown attribute(s) %s" % (where, ", ".join(sorted(unknown))))
    return [a for a in ATTR_ORDER if a in group]


def convert(msh_text, blob):
    """-> (msh text in the editor's layout, rearranged blob bytes)."""
    data = luadata.parse(msh_text)
    if not isinstance(data, dict) or "vertexAttr" not in data:
        raise MeshError("no vertexAttr")
    out, pos = [], 0

    def take(entry, where):
        nonlocal pos
        count, offset = entry["count"], entry["offset"]
        if offset < 0 or count < 0 or offset + count > len(blob):
            raise MeshError("%s: bytes %d..%d outside a %d-byte blob"
                            % (where, offset, offset + count, len(blob)))
        out.append(blob[offset:offset + count])
        new = dict(entry, offset=pos)
        pos += count
        return new

    attrs = data["vertexAttr"]
    vertex = {a: take(attrs[a], "vertexAttr." + a) for a in _ordered(attrs, "vertexAttr")}
    subs = []
    for n, sub in enumerate(data.get("subMeshes", []), 1):
        where = "subMeshes[%d].indices" % n
        idx = sub.get("indices", {})
        subs.append({"indices": {a: take(idx[a], "%s.%s" % (where, a))
                                 for a in _ordered(idx, where)}})

    result = {k: v for k, v in data.items()
              if k not in DROPPED and k not in ("vertexAttr", "subMeshes")}
    result["vertexAttr"] = vertex
    result["subMeshes"] = subs
    return luadata.dump(result), b"".join(out)


def convert_file(msh_path, out_path=None):
    """Convert msh_path (+ .blob) to out_path (default: in place)."""
    out_path = out_path or msh_path
    with open(msh_path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    with open(msh_path + ".blob", "rb") as f:
        blob = f.read()
    new_text, new_blob = convert(text, blob)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(new_text.encode("utf-8"))
    with open(out_path + ".blob", "wb") as f:
        f.write(new_blob)


def convert_tree(root):
    """Convert every .msh under root in place. -> (converted, [(path, error)])."""
    done, failed = 0, []
    for d, _, files in os.walk(root):
        for fn in sorted(files):
            if not fn.endswith(".msh"):
                continue
            p = os.path.join(d, fn)
            try:
                convert_file(p)
                done += 1
            except (MeshError, luadata.LuaSyntaxError, OSError, KeyError) as e:
                failed.append((p, "%s: %s" % (type(e).__name__, e)))
    return done, failed
