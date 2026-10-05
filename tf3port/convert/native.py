"""The Model Editor's Bulk Convert, done here: every model and material of a
staged mod, plus the meshes and animations the models use.

What the editor changes, and so what this changes (checked on 31 vehicles,
port.py compare-convert tree on the golden data): .mdl, .mtl, and the .msh
(+ .blob) and .ani that some model references. Meshes and animations no
model uses are left as they are, as the editor leaves them. Nothing else in
the mod is touched.
"""
import os

from . import luadata, luaenv, material, mesh, model


def _refs(data, out):
    """Paths a converted model references: lods' meshes, FILE_REF animations."""
    if isinstance(data, dict):
        m = data.get("mesh")
        if isinstance(m, str):
            out.add(m)
        if data.get("type") == "FILE_REF":
            ref = (data.get("params") or {}).get("id")
            if isinstance(ref, str) and not ref.startswith("::"):
                out.add(ref)
        for v in data.values():
            _refs(v, out)
    elif isinstance(data, list):
        for v in data:
            _refs(v, out)


def _mesh_exists(ref, model_dir):
    if ref.startswith("::/"):
        return ref[3:] in luaenv.resource_index()
    return os.path.exists(os.path.join(model_dir, ref))


def prune_missing_meshes(data, model_dir, gone=None):
    """Leave out nodes whose mesh exists nowhere, and return their paths.

    One missing mesh makes the game drop the whole model ("removed because
    they reference an invalid resource"). It happens with a mod that only
    rewrites a TF2 base vehicle's .mdl when TF3 remodelled that vehicle: the
    body is still there, but headlights and some window panes were split up
    and renamed. Without those parts the vehicle still runs and looks right."""
    gone = [] if gone is None else gone
    if isinstance(data, dict):
        for v in data.values():
            prune_missing_meshes(v, model_dir, gone)
    elif isinstance(data, list):
        keep = []
        for v in data:
            m = v.get("mesh") if isinstance(v, dict) else None
            if isinstance(m, str) and not _mesh_exists(m, model_dir):
                gone.append(m)
                continue
            prune_missing_meshes(v, model_dir, gone)
            keep.append(v)
        data[:] = keep
    return gone


def _is_tf3_model(text):
    try:
        return luadata.parse(text).get("version") == 2
    except luadata.LuaSyntaxError:
        return False          # TF2 models are real Lua (require, locals)


def convert_mod(content_root, mod_id, log=print):
    """Convert the mod whose content/ folder is content_root, in place.
    -> {"models": n, "materials": n, "meshes": n, "animations": n, "failed": [...]}"""
    counts = {"models": 0, "materials": 0, "meshes": 0, "animations": 0, "skipped": 0}
    failed = []
    used = set()
    for d, _, files in os.walk(content_root):
        for fn in sorted(files):
            p = os.path.join(d, fn)
            rel = os.path.relpath(p, content_root).replace(os.sep, "/")
            if fn.endswith(".mdl"):
                text = open(p, encoding="utf-8-sig").read()
                if _is_tf3_model(text):
                    counts["skipped"] += 1
                    continue
                try:
                    data = model.convert_data(text, "%s::/%s" % (mod_id, rel), d)
                except (luaenv.LuaEnvError, Exception) as e:  # Lua errors come as several types
                    failed.append((rel, "%s: %s" % (type(e).__name__, str(e).splitlines()[0])))
                    continue
                for m in sorted(set(prune_missing_meshes(data, d))):
                    log("  %s: left out a part whose mesh exists nowhere: %s" % (rel, m))
                refs = set()
                _refs(data, refs)
                # ::/ is base's own file, already in TF3 form and not ours to
                # rewrite (a mod that only rewrites a base vehicle's .mdl
                # refers to nothing else)
                used.update(os.path.normpath(os.path.join(d, r)) for r in refs
                            if not r.startswith("::/"))
                with open(p, "wb") as f:
                    f.write(luadata.dump(data, float_fmt=model.fmt_float).encode("utf-8"))
                counts["models"] += 1
            elif fn.endswith(".mtl"):
                try:
                    material.convert_file(p)
                    counts["materials"] += 1
                except material.MaterialError as e:
                    if "already in TF3 form" in str(e):
                        counts["skipped"] += 1
                    else:
                        failed.append((rel, str(e)))
    for p in sorted(used):
        rel = os.path.relpath(p, content_root).replace(os.sep, "/")
        if not os.path.exists(p):
            failed.append((rel, "referenced but missing"))
            continue
        try:
            if p.endswith(".msh"):
                mesh.convert_file(p)
                counts["meshes"] += 1
            elif p.endswith(".ani"):
                data = luaenv.to_py(model.env().load_data_file(open(p, encoding="utf-8-sig").read(), rel))
                with open(p, "wb") as f:
                    f.write(luadata.dump(data, float_fmt=model.fmt_float).encode("utf-8"))
                counts["animations"] += 1
        except Exception as e:  # report every file, stop on none
            failed.append((rel, "%s: %s" % (type(e).__name__, str(e).splitlines()[0])))
    counts["failed"] = failed
    return counts


def cmd_convert(v):
    """`port.py <vehicle> convert --engine native`."""
    r = convert_mod(os.path.join(v.dst, "content"), v.mod_id)
    print("models %(models)d, materials %(materials)d, meshes %(meshes)d, "
          "animations %(animations)d, already converted %(skipped)d" % r)
    for rel, err in r["failed"]:
        print("  FAILED %s: %s" % (rel, err))
    if r["failed"]:
        raise SystemExit("convert: %d files failed - rerun `build` and use "
                         "--engine editor for this vehicle" % len(r["failed"]))
