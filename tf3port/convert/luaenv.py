"""A Lua environment that runs the game's own model-loading scripts.

The Model Editor converts a TF2 .mdl by passing its data() through the
"loadModel" modifiers that model_editor/editor_base_mod.lua registers
(model_metadata_util.toCompartmentList, ...turnRoadAndRailToLandVehicle,
metadataanimationutil.createAnimationEventsRailVehicle, ...). Those are
plain Lua in the installed game, so instead of rewriting them this module
runs them with lupa:

- require / ug_require resolve resource paths ("/base/x.lua", "::/x") to the
  zips in base/content, and the editor's legacy names ("transf" -> mat4.tl,
  "vec3", "vec2"), which TF2 models use
- .tl files (TF3 writes some scripts in Teal) are compiled with the Teal
  compiler in vendor/tl.lua first
- `_("...")` marks a string for translation; the editor keeps the call in
  its output, so it becomes luadata.Call("_", [...]) on the way out
- log.* calls are collected (Env.log)

The game runs Lua 5.2; lupa offers 5.4 at the oldest-but-close, which these
scripts do not tell apart except for integer vs float numbers (see to_py).
"""
import os
import zipfile

from . import basegame, luadata
from ..paths import TF3_BASE

LEGACY_MODULES = {
    "transf": "scripts/mat4.tl",
    "vec2": "scripts/vec2.tl",
    "vec3": "scripts/vec3.tl",
}

TRANSLATE = "\x00tr\x00"     # prefix _() puts on a string, undone by to_py

VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")


class LuaEnvError(RuntimeError):
    pass


_index = None


def resource_index():
    """resource path (no leading slash) -> zip under base/content holding it."""
    global _index
    if _index is None:
        _index = {}
        for root, _, files in os.walk(TF3_BASE):
            for f in files:
                if not f.endswith(".zip"):
                    continue
                rel = os.path.relpath(os.path.join(root, f), TF3_BASE).replace(os.sep, "/")
                prefix = os.path.dirname(rel)
                prefix = prefix + "/" if prefix else ""
                try:
                    names = zipfile.ZipFile(os.path.join(root, f)).namelist()
                except zipfile.BadZipFile:
                    continue
                for n in names:
                    _index.setdefault(prefix + n, (rel, n))
    return _index


def read_resource(path):
    """Text of a base resource: "/base/x.lua", "::/base/x.lua" or "base/x.lua"."""
    key = path.split("::", 1)[-1].lstrip("/")
    hit = resource_index().get(key)
    if hit:
        return basegame.open_zip(hit[0]).read(hit[1]).decode("utf-8-sig")
    loose = os.path.join(TF3_BASE, *key.split("/"))
    if os.path.isfile(loose):
        return basegame.read_text(key)
    raise LuaEnvError("no %s in the game's base/content" % path)


class Env(object):
    def __init__(self):
        try:
            from lupa import lua54
        except ImportError:
            raise LuaEnvError("the model conversion needs lupa: pip install lupa")
        self.L = lua54.LuaRuntime(unpack_returned_tuples=True)
        self.log = []
        self.modifiers = {}
        tl = self.L.execute(open(os.path.join(VENDOR, "tl.lua"), encoding="utf-8").read())
        self._tl = tl[0] if isinstance(tl, tuple) else tl
        g = self.L.globals()
        g._py_source = self._source
        g._py_log = lambda level, msg: self.log.append((level, str(msg)))
        g._py_modifier = self._add_modifier
        self.L.execute(r'''
            local loaded = {}
            local function load_module(name)
                local key = _py_source(name)
                if loaded[key] == nil then
                    local code = _py_source(name, true)
                    local chunk, err = load(code, "@" .. key, "t", _ENV)
                    if not chunk then error(err, 2) end
                    local r = chunk()
                    loaded[key] = (r == nil) and true or r
                end
                return loaded[key]
            end
            require = load_module
            ug_require = load_module
            toString = tostring
            _ = function(s) return "''' + TRANSLATE.replace("\x00", "\\0") + r'''" .. s end
            log = setmetatable({}, { __index = function(t, level)
                return function(...) _py_log(level, table.concat({...}, " ")) end
            end })
            addModifier = function(kind, fn) _py_modifier(kind, fn) end
        ''')

    def _add_modifier(self, kind, fn):
        self.modifiers.setdefault(kind, []).append(fn)

    def _source(self, name, code=False):
        """require's resolver: -> canonical key, or with code=True the Lua source."""
        key = LEGACY_MODULES.get(name, name.split("::", 1)[-1].lstrip("/"))
        if not code:
            return key
        text = read_resource(key)
        if key.endswith(".tl"):
            out = self._tl.gen(text)
            lua = out[0] if isinstance(out, tuple) else out
            if not lua:
                raise LuaEnvError("Teal could not compile %s: %s" % (key, out))
            return lua
        return text

    def run_mod_script(self, resource):
        """Run a mod script's data().runFn, as the editor does with editor_base_mod.lua."""
        chunk = self.L.eval("function(code, name) local f, e = load(code, '@' .. name, 't', _ENV)"
                            " if not f then error(e) end return f end")(read_resource(resource), resource)
        chunk()
        data = self.L.globals().data()
        if data["runFn"] is not None:
            data["runFn"](self.L.table(), self.L.table())

    def load_data_file(self, text, name):
        """data() of a .mdl/.mtl/... that may use require and locals."""
        f = self.L.eval('''function(code, name)
            local env = setmetatable({}, { __index = _ENV })
            local chunk, err = load(code, "@" .. name, "t", env)
            if not chunk then error(err) end
            chunk()
            if env.data == nil then error(name .. " has no data()") end
            return env.data()
        end''')
        return f(text, name)

    def apply(self, kind, file_name, data):
        for fn in self.modifiers.get(kind, []):
            out = fn(file_name, data)
            if out is not None:
                data = out
        return data


def to_py(v):
    """A Lua value -> Python: lists for 1..n tables, dicts otherwise,
    luadata.Call for _() strings."""
    from lupa.lua54 import lua_type
    t = lua_type(v)
    if t == "table":
        keys = list(v.keys())
        if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
            return [to_py(v[k]) for k in range(1, len(keys) + 1)]
        return {k: to_py(v[k]) for k in keys}
    if t == "function":
        raise LuaEnvError("a function in the data")
    if isinstance(v, bytes):
        v = v.decode("utf-8")
    if isinstance(v, str) and v.startswith(TRANSLATE):
        return luadata.Call("_", [v[len(TRANSLATE):]])
    return v
