"""B-2: TF2 .mtl -> TF3, without the Model Editor.

A TF2 material is flat: params.<property> = { <field> = value, ... }, with a
texture's settings (fileName, wrapS, ...) directly in its map_* property.
TF3 nests each property by what the shader gets:

    params.<property>.fragmentProperties = { { <field> = value, ... } }
    params.<property>.vertexProperties   = { { ... } }
    params.<property>.fragmentSamplers   = { <samplerName> = { fileName = ..., ... } }

Which properties a type has, and each property's fields, sampler names and
defaults, are data the game ships: base/content/rendering/<type>.mat.lua
(found by its `legacyName`, the TF2 type name) and properties/*.prop.lua in
rendering/properties.zip. They are read from the installed game
(basegame.py). The editor's Bulk Convert applies them like this (checked on
all 718 materials of 31 vehicles, port.py compare-convert material):

- every property of the type is written, TF2 value or default per field;
  a field marked skipIfDefault is left out when it equals its default, and a
  property left with nothing is left out (so `light_receiver`, which TF2 does
  not have, appears with lightMask = 2, isLegacyMaterial = true)
- fields with arrayCount > 1 are padded with the default
  (albedoScales { 1 } -> { 1, 0 })
- TF2 fields the property does not define are dropped
- samplers keep fileName and type, and the other settings only where they
  differ from the editor's defaults (SAMPLER_DEFAULTS); compressionAllowed
  is dropped. A sampler the type has but TF2 lacks gets the placeholder.
- floats are written with 6 significant digits (luadata.g6)
- type stays, `order` stays (0 if absent), `__version = ""` is added
"""
import os

from . import basegame, luadata

# A sampler setting equal to these is not written. Taken from the editor's
# output: TF2 materials spell them out, the converted ones never do.
SAMPLER_DEFAULTS = {
    "wrapS": "CLAMP_TO_EDGE",
    "wrapT": "CLAMP_TO_EDGE",
    "magFilter": "LINEAR",
    "minFilter": "LINEAR_MIPMAP_LINEAR",
    "mipmapAlphaScale": 0,
    "redGreen": False,
    "scaleDownAllowed": True,
}

SAMPLER_DROPPED = ("compressionAllowed",)

# what the editor writes for a sampler the TF2 material does not have
MISSING_SAMPLER = {
    "fileName": "::/placeholders/mat/tex/unknown_texture.dds",
    "type": "TWOD",
    "wrapS": "REPEAT",
    "wrapT": "REPEAT",
}

GROUPS = ("fragmentProperties", "vertexProperties")


class MaterialError(ValueError):
    pass


class Registry(object):
    """Material types and properties from the installed game."""

    def __init__(self):
        self.types = {}
        for fn in basegame.list_dir("rendering"):
            if fn.endswith(".mat.lua"):
                mat = luadata.parse(basegame.read_text("rendering/" + fn))
                if mat.get("legacyName"):
                    self.types[mat["legacyName"]] = mat
        if not self.types:
            raise MaterialError("no material types found under base/content/rendering - is TF3 found? "
                                "(python port.py paths)")
        self._props = {}

    def prop(self, prop_id):
        if prop_id not in self._props:
            zf = basegame.open_zip("rendering/properties.zip")
            self._props[prop_id] = luadata.parse(zf.read(prop_id + ".lua").decode("utf-8-sig"))
        return self._props[prop_id]


_registry = None


def registry():
    global _registry
    if _registry is None:
        _registry = Registry()
    return _registry


def _float(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def _one(kind, value):
    """One element of a field: a number, or a vector for Vec*f."""
    if kind == "Int" and isinstance(value, float) and value.is_integer():
        return int(value)
    if kind == "Float" or kind.startswith("Vec"):
        return [_float(x) for x in value] if isinstance(value, list) else _float(value)
    return value


def _norm(field, value):
    """A TF2 value in the shape the field's type wants; arrays padded to
    arrayCount with the default."""
    kind = field.get("type", "")
    count = field.get("arrayCount", 1)
    if count == 1:
        return _one(kind, value)
    # an array: of numbers for Float, of vectors for Vec*f. A bare element
    # (a number, or one vector) is an array of one.
    is_vector = kind.startswith("Vec")
    # an empty Lua table reads as a dict; here it is an empty array. Taken as
    # one element it came out as colors = { { }, { -1, -1, -1 } } (a DLC
    # tram's TF2 material has colors = { }), and the game rejected the
    # material: "key not found"
    if value == {}:
        value = []
    if not isinstance(value, list) or (is_vector and value and not isinstance(value[0], list)):
        value = [value]
    value = [_one(kind, v) for v in value[:count]]
    return value + [_norm_default(field)] * (count - len(value))


def _norm_default(field):
    return _one(field.get("type", ""), field.get("defaultValue"))


def _same(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        return luadata.g6(a) == luadata.g6(b)
    return a == b


def _fields(defs, src):
    out = {}
    for field in defs:
        name = field["name"]
        default = _norm_default(field)
        if field.get("arrayCount", 1) > 1:
            default_full = [default] * field["arrayCount"]
        else:
            default_full = default
        value = _norm(field, src[name]) if name in src else default_full
        if field.get("skipIfDefault") and _same(value, default_full):
            continue
        out[name] = value
    return out


def _sampler(src):
    if "fileName" not in src:
        return dict(MISSING_SAMPLER)
    out = {}
    for k, v in src.items():
        if k in SAMPLER_DROPPED:
            continue
        if k in SAMPLER_DEFAULTS and _same(v, SAMPLER_DEFAULTS[k]):
            continue
        out[k] = v
    out.setdefault("type", "TWOD")
    return out


def convert_data(tf2, reg=None):
    """A parsed TF2 material -> the TF3 table."""
    reg = reg or registry()
    kind = tf2.get("type")
    mat = reg.types.get(kind)
    if mat is None:
        raise MaterialError("unknown material type %r" % kind)
    src_params = tf2.get("params", {})
    params = {}
    for entry in mat["properties"]:
        name = entry["name"]
        prop = reg.prop(entry["id"])
        src = src_params.get(name, {})
        if not isinstance(src, dict):
            raise MaterialError("params.%s is not a table" % name)
        if any(g in src for g in GROUPS + ("fragmentSamplers",)):
            raise MaterialError("params.%s is already in TF3 form" % name)
        out = {}
        for group in GROUPS:
            fields = _fields(prop.get(group, []), src)
            if fields:
                out[group] = [fields]
        samplers = prop.get("fragmentSamplers", [])
        if len(samplers) > 1:
            raise MaterialError("params.%s: %d samplers - a TF2 map has one" % (name, len(samplers)))
        if samplers:
            out["fragmentSamplers"] = {samplers[0]["name"]: _sampler(src)}
        if out:
            params[name] = out
    return {
        "__version": "",
        "order": tf2.get("order", 0),
        "params": params,
        "type": kind,
    }


def convert(text, reg=None):
    """TF2 .mtl text -> TF3 .mtl text in the editor's layout."""
    return luadata.dump(convert_data(luadata.parse(text), reg), float_fmt=luadata.g6)


def convert_file(path, out_path=None):
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    new = convert(text)
    with open(out_path or path, "wb") as f:
        f.write(new.encode("utf-8"))


def convert_tree(root):
    """Convert every .mtl under root in place. -> (converted, [(path, error)])."""
    done, failed = 0, []
    for d, _, files in os.walk(root):
        for fn in sorted(files):
            if fn.endswith(".mtl"):
                p = os.path.join(d, fn)
                try:
                    convert_file(p)
                    done += 1
                except (MaterialError, luadata.LuaSyntaxError, OSError, KeyError) as e:
                    failed.append((p, "%s: %s" % (type(e).__name__, e)))
    return done, failed
