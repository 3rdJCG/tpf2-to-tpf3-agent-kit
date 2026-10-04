"""B-3: TF2 .mdl -> TF3, without the Model Editor.

Two halves, as in the editor:

1. The game's Lua. The editor passes a TF2 model's data() through the
   "loadModel" modifiers of model_editor/editor_base_mod.lua. luaenv.Env runs
   that very script from the installed game.
2. The editor's own serializer. It reads the result into its typed model
   structure and writes that back out, which drops fields the structure does
   not have, fills in ones it requires, leaves out fields at their default,
   rounds numbers to their type and converts a few TF2 leftovers. That part
   is C++; `editor_pass` below redoes it with rules taken from comparing
   the editor's output on 31 vehicles (port.py compare-convert model).
"""
import os
import struct

from . import luadata, luaenv

FLT_EPSILON = 1.1920928955078125e-07


def fmt_float(x):
    """How the editor writes a float: rounded to float32, then 0 if below
    FLT_EPSILON (in that order - 1.19209289e-07 rounds up to it and stays),
    then 6 significant digits."""
    x = struct.unpack("f", struct.pack("f", x))[0]
    if abs(x) < FLT_EPSILON:
        return "0"
    return "%g" % x


_env = None


def env():
    global _env
    if _env is None:
        _env = luaenv.Env()
        _env.run_mod_script("model_editor/editor_base_mod.lua")
    return _env


def run_lua(text, file_name):
    """TF2 .mdl text -> the table the editor's Lua modifiers leave (Python)."""
    e = env()
    data = e.load_data_file(text, file_name)
    return luaenv.to_py(e.apply("loadModel", file_name, data))


# ---- the editor's serializer -------------------------------------------

def _nodes(node):
    yield node
    for child in node.get("children", []) or []:
        for n in _nodes(child):
            yield n


def _drop(d, *keys):
    for k in keys:
        d.pop(k, None)


def _drop_if(d, key, *defaults):
    if key in d and any(d[key] == x and type(d[key]) == type(x) for x in defaults):
        del d[key]


IDENTITY = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)

LABEL_DEFAULTS = {"nLines": 1, "filter": "NONE", "alpha": 1, "params": {},
                  "renderMode": "STD", "alphaMode": "CUTOUT", "font": "",
                  "fitting": "SCALE"}


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def _cargo_entry(ce):
    # the editor's capacity is a multiple of 4: 103 -> 104, 85 -> 84, 50 -> 52
    cap = ce.get("capacity", 0)
    ce["capacity"] = int(cap / 4.0 + 0.5) * 4
    cts = ce.setdefault("cargoTypeSet", {})
    for k in ("cargoClassesExcluded", "cargoClassesIncluded",
              "cargoTypesExcluded", "cargoTypesIncluded"):
        cts.setdefault(k, {})
    ce.setdefault("loadIndicator", "")
    ce.setdefault("seats", {})


def _translatable(desc, key, keep_empty):
    """name/description are translatable strings: plain ones get _(),
    an empty one is a plain "" (name) or left out (description)."""
    v = desc.get(key)
    if v is None:
        return
    text = v.args[0] if isinstance(v, luadata.Call) and v.name == "_" and v.args else v
    if not isinstance(text, str):
        return
    if text == "":
        if keep_empty:
            desc[key] = ""
        else:
            del desc[key]
    else:
        desc[key] = luadata.Call("_", [text])


def _collider(data):
    """A TF2 MESH collider becomes the bounding box, worked out in float32."""
    col = data.get("collider")
    bi = data.get("boundingInfo")
    if not col or col.get("type") != "MESH" or not bi:
        return
    lo, hi = bi["bbMin"], bi["bbMax"]
    half = [_f32((_f32(h) - _f32(l)) / 2) for l, h in zip(lo, hi)]
    mid = [_f32((_f32(h) + _f32(l)) / 2) for l, h in zip(lo, hi)]
    col["type"] = "BOX"
    col["params"] = {"halfExtents": half}
    col["transf"] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, mid[0], mid[1], mid[2], 1]


def _emitter(e):
    """A TF2 smoke emitter (color, size01, a plain lifeTime ...) in TF3's
    curve form, the way the editor rewrites it."""
    if "color" not in e and "size01" not in e:
        return
    if "color" in e:
        e["colorOverLifeTime"] = {"curve": [{"easing": "Linear", "time": 1, "value": e.pop("color")}]}
    if "size01" in e:
        a, b = e.pop("size01")
        e["sizeOverLifeTime"] = {"curve": [
            {"easing": "Linear", "time": 0, "value": {"value": a}},
            {"easing": "EaseOutSqrt", "time": 4, "value": {"value": b}}]}
    if "initialAlpha" in e:
        alpha = e.pop("initialAlpha")
        if alpha != 1:
            e["alphaOverLifeTime"] = {"curve": [
                {"easing": "Linear", "time": 0, "value": alpha},
                {"easing": "Linear", "time": 1, "value": 0}]}
    for k in ("frequency", "velocity"):
        if k in e and not isinstance(e[k], dict):
            e[k] = {"value": e[k]}
    if "lifeTime" in e and not isinstance(e["lifeTime"], dict):
        life = e["lifeTime"]
        e["lifeTime"] = {"randomMinMax": {"max": life, "min": life / 2.0}}
    _drop_if(e, "velocityDampingFactor", 2.5)
    e.setdefault("particleId", "")
    e.setdefault("shape", {"point": {"maxDir": 0.8}})
    e.setdefault("velocityByDirection", {"value": 0})


DEFAULT_DELAY = 2000


def _delays(data, ani_length):
    """arrival/departureDelay: the longest open_*/close_* animation in ms,
    written when longer than the default."""
    longest = {"open": 0.0, "close": 0.0}
    for lod in data.get("lods", []):
        for n in _nodes(lod.get("node") or {}):
            for name, anim in (n.get("animations") or {}).items():
                kind = name.split("_", 1)[0]
                if kind not in longest or not isinstance(anim, dict):
                    continue
                params = anim.get("params", {})
                if anim.get("type") == "FILE_REF":
                    t = ani_length(params.get("id", ""))
                else:
                    t = max([kf.get("time", 0) for kf in params.get("keyframes", [])] or [0])
                longest[kind] = max(longest[kind], t or 0)
    tv = data.get("metadata", {}).get("transportVehicle")
    if tv is None:
        return
    for kind, key in (("open", "arrivalDelay"), ("close", "departureDelay")):
        ms = int(longest[kind])
        if ms > DEFAULT_DELAY:
            tv.setdefault(key, ms)


def editor_pass(data, ani_length=lambda ref: 0):
    data["version"] = 2
    for lod in data.get("lods", []):
        _drop_if(lod, "static", False)
        node = lod.get("node")
        if node:
            for n in _nodes(node):
                # bookkeeping of replaceMeshIdWithNodeName
                _drop(n, "_meshId", "_origMeshId")
                if n.get("animations") == {}:
                    del n["animations"]
                for anim in (n.get("animations") or {}).values():
                    # metadataanimationutil gives the shared light animations
                    # their keyframes as well as the file; a FILE_REF keeps
                    # only the file
                    if anim.get("type") == "FILE_REF":
                        _drop(anim.get("params", {}), "keyframes")
    md = data.get("metadata", {})

    sp = md.get("seatProvider")
    if sp:
        for seat in sp.get("seats", []):
            _drop_if(seat, "crew", False)
            _drop_if(seat, "forward", True)
            _drop(seat, "standing")

    lv = md.get("landVehicle")
    if lv is not None:
        # convertWeight wrote weightEmpty from it; the sound set went to
        # soundConfig
        _drop(lv, "weight", "soundSet")
        lv.setdefault("weightMaxPayload", 0)
        lv.setdefault("curveSpeedScale", 1)

    rv = md.get("railVehicle")
    if rv is not None:
        _drop(rv, "blinkInterval")
        cfg = rv.get("config")
        if cfg:
            # TF3 switches lights with animations (*Parts); the TF2 index
            # lists and the axle radii have no place in the structure
            _drop(cfg, "axleRadii", "forwardLights", "backwardLights",
                  "forwardEndLights", "backwardEndLights")

    snd = md.get("soundConfig", {}).get("soundSet")
    if snd:
        _drop(snd, "horn", "events")

    tv = md.get("transportVehicle")
    if tv is not None:
        _drop(tv, "multipleUnitOnly")
        _drop_if(tv, "groupFileName", "")
        _drop_if(tv, "loadSpeed", 1, 1.0)
        _drop_if(tv, "reversible", False)
        tv.setdefault("entrances", {})
        tv.setdefault("engineTransportModes", {})
        if tv.get("compartments") == {}:
            tv["compartments"] = [{}]
        for comp in tv.get("compartments", []):
            configs = comp.setdefault("loadConfigs", [{}])
            for lc in configs:
                if lc.get("cargoEntries") == {}:
                    # makeCargoEntry found nothing to carry
                    del lc["cargoEntries"]
                lc.setdefault("cargoEntry", {})
                lc.setdefault("toHide", {})
                _cargo_entry(lc["cargoEntry"])

    if sp is not None:
        sp.setdefault("crewModels", {})

    li = md.get("loadIndicator")
    if li is not None:
        li.setdefault("slots", {})
        for c in (li.get("configs") or {}).values():
            _drop(c.get("cargoBay", {}), "cargoFormat")

    for label in md.get("labelList", {}).get("labels", []):
        for k, default in LABEL_DEFAULTS.items():
            _drop_if(label, k, default)

    for pos in md.get("cameraConfig", {}).get("positions", []):
        _drop_if(pos, "noTransf", False)

    if rv is not None:
        for bogies in (rv.get("config") or {}).get("fakeBogies", []):
            for b in bogies:
                _drop_if(b, "upright", False)

    desc = md.get("description")
    if desc is not None:
        _translatable(desc, "name", keep_empty=True)
        _translatable(desc, "description", keep_empty=False)

    m = md.get("maintenance", {})
    if isinstance(m.get("lifespan"), float):
        m["lifespan"] = int(m["lifespan"])       # an integer in the structure

    for lod in data.get("lods", []):
        for n in _nodes(lod.get("node") or {}):
            if n is not lod.get("node"):
                n.setdefault("transf", list(IDENTITY))
            for anim in (n.get("animations") or {}).values():
                _drop_if(anim, "forward", True)

    _collider(data)
    _delays(data, ani_length)
    for e in md.get("particleSystem", {}).get("emitters", []):
        _emitter(e)

    _drop_if(md.get("maintenance", {}), "runningCostScale", 1, 1.0)
    _drop_if(md.get("cost", {}), "priceScale", 1, 1.0)
    for kind in ("noise", "pollution"):
        e = md.get("emissions", {}).get(kind)
        if e:
            for k in ("power", "speed", "idle"):
                _drop_if(e, k, 0, 0.0)
    return data


def ani_length_in(model_dir):
    """-> ref -> length in ms of the animation file a FILE_REF names,
    relative to the model's folder (shared ::/ ones are light switches)."""
    cache = {}

    def length(ref):
        if ref.startswith("::") or not model_dir:
            return 0
        if ref not in cache:
            path = os.path.join(model_dir, *ref.split("/"))
            try:
                with open(path, encoding="utf-8-sig") as f:
                    ani = luaenv.to_py(env().load_data_file(f.read(), ref))
                cache[ref] = max(ani.get("times") or [0])
            except (OSError, luaenv.LuaEnvError):
                cache[ref] = 0
        return cache[ref]
    return length


def convert_data(text, file_name, model_dir=None):
    """file_name: as the game names the model ("<mod>::/<dir>/<x>.mdl");
    model_dir: its folder on disk, for the .ani files it references."""
    return editor_pass(run_lua(text, file_name), ani_length_in(model_dir))


def convert(text, file_name, model_dir=None):
    return luadata.dump(convert_data(text, file_name, model_dir), float_fmt=fmt_float)
