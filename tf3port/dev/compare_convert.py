"""Compare tf3port.convert's output with what the Model Editor's Bulk Convert
wrote into staging.

    python port.py compare-convert mesh [vehicle ...]     (default: every config)
    python port.py compare-convert tree <expected> <actual> [--show N]
    python port.py compare-convert material [vehicle ...] [--show N]
    python port.py compare-convert model [vehicle ...] [--show N]

mesh: converts each source .msh/.blob that `build` copied and the editor
rewrote, and compares both files byte for byte with the staged ones. Meshes
no model references keep the source text (the editor skips them); those are
only converted, to see that they do not fail.

tree: compares two mod folders by data rather than by text. .mdl/.mtl/.msh/
.ani are read as Lua tables (key order, layout and float spelling do not
count; numbers match within 1e-6), .blob and everything else byte for byte.
mod.json, _metadata/ and port.json are left out - they carry the modId,
which differs between a golden copy and the mod under test. Prints, per file
type, each differing key path (list indices shown as []) and in how many
files it differs.

material: converts each .mtl in the golden data's pre/ (build's output) and
compares it with post/ (the editor's), byte for byte and, where the bytes
differ, by data. model: the same for .mdl (needs lupa). Golden data: work/golden/<vehicle>/{pre,post} in the
workspace (B-0 in docs/roadmap.md).
"""
import collections
import hashlib
import os
import sys


from tf3port.common import Vehicle, tf3_name, vehicle_names
from tf3port.convert import luadata, material, mesh, model
from tf3port.paths import WORKSPACE

GOLDEN = os.path.join(WORKSPACE, "work", "golden")

EDITOR_HEADER = "function data()\r\nreturn { \r\n"


def staged_meshes(v):
    """(source .msh, staged .msh) the way build's copy_flat lays them out."""
    root = os.path.join(v.res, "models", "mesh")
    for d, _, files in os.walk(root):
        for fn in sorted(files):
            if fn.endswith(".msh"):
                parts = [tf3_name(fn)]
                if d != root:
                    parts.insert(0, tf3_name(os.path.basename(d)))
                yield os.path.join(d, fn), os.path.join(v.veh, "msh", *parts)


def compare_mesh(v, show):
    same = differ = untouched = errors = absent = 0
    for src, dst in staged_meshes(v):
        try:
            text, blob = mesh.convert(open(src, encoding="utf-8-sig", errors="replace").read(),
                                      open(src + ".blob", "rb").read())
        except (mesh.MeshError, luadata.LuaSyntaxError, OSError, KeyError) as e:
            errors += 1
            if show:
                print("  ERROR %s: %s" % (os.path.relpath(src, v.src), e))
            continue
        if not os.path.exists(dst):
            absent += 1
            continue
        staged = open(dst, "rb").read()
        if not staged.decode("utf-8", "replace").startswith(EDITOR_HEADER):
            untouched += 1
            continue
        ok_text = staged == text.encode("utf-8")
        ok_blob = open(dst + ".blob", "rb").read() == blob
        if ok_text and ok_blob:
            same += 1
        else:
            differ += 1
            if show:
                print("  DIFF  %s (%s)" % (os.path.relpath(dst, v.veh),
                                           ", ".join(n for n, ok in (("msh", ok_text), ("blob", ok_blob)) if not ok)))
    print("%-14s %4d/%4d identical   (%d unreferenced, %d not staged, %d errors)"
          % (v.name, same, same + differ, untouched, absent, errors))
    return same, differ, errors


DATA_EXT = (".mdl", ".mtl", ".msh", ".ani")
SKIP_TOP = ("mod.json", "_metadata", "port.json")


def files_under(root):
    out = {}
    for d, dirs, files in os.walk(root):
        if d == root:
            dirs[:] = [x for x in dirs if x not in SKIP_TOP]
        for fn in files:
            rel = os.path.relpath(os.path.join(d, fn), root).replace(os.sep, "/")
            if rel not in SKIP_TOP:
                out[rel] = os.path.join(d, fn)
    return out


def data_diff(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            p = "%s.%s" % (path, k)
            if k not in a:
                out.add(("added", p))
            elif k not in b:
                out.add(("removed", p))
            else:
                data_diff(a[k], b[k], p, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.add(("length", path + "[]"))
        for x, y in zip(a, b):
            data_diff(x, y, path + "[]", out)
    elif isinstance(a, luadata.Call) and isinstance(b, luadata.Call):
        if a.name != b.name:
            out.add(("value", path))
        data_diff(a.args, b.args, path + "()", out)
    elif (isinstance(a, (int, float)) and isinstance(b, (int, float))
          and not isinstance(a, bool) and not isinstance(b, bool)):
        if abs(a - b) > 1e-6 * max(1.0, abs(a), abs(b)):
            out.add(("value", path))
    elif type(a) != type(b):
        out.add(("type", path))
    elif a != b:
        out.add(("value", path))


def compare_tree(expected, actual, show=40):
    exp, act = files_under(expected), files_under(actual)
    stats = collections.defaultdict(collections.Counter)
    nfiles, same_files = collections.Counter(), collections.Counter()
    for rel in sorted(set(exp) | set(act)):
        ext = os.path.splitext(rel)[1].lower() or "(none)"
        nfiles[ext] += 1
        if rel not in act:
            stats[ext][("missing file", rel if show else "")] += 1
            continue
        if rel not in exp:
            stats[ext][("extra file", rel if show else "")] += 1
            continue
        if ext in DATA_EXT:
            try:
                a = luadata.parse(open(exp[rel], encoding="utf-8-sig").read())
                b = luadata.parse(open(act[rel], encoding="utf-8-sig").read())
            except luadata.LuaSyntaxError as e:
                stats[ext][("unparsed", "%s: %s" % (rel, e))] += 1
                continue
            found = set()
            data_diff(a, b, "", found)
            for item in found:
                stats[ext][item] += 1
            if not found:
                same_files[ext] += 1
        else:
            if digest(exp[rel]) == digest(act[rel]):
                same_files[ext] += 1
            else:
                stats[ext][("bytes", "")] += 1
    for ext in sorted(nfiles):
        print("== %-7s %4d/%4d files equal" % (ext, same_files[ext], nfiles[ext]))
        rows = sorted(stats[ext].items(), key=lambda x: (-x[1], x[0]))
        for (kind, path), n in rows[:show]:
            print("  %4d  %-12s %s" % (n, kind, path))
        if len(rows) > show:
            print("  ... %d more" % (len(rows) - show))
    return sum(sum(c.values()) for c in stats.values())


def digest(p):
    with open(p, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def golden_vehicles(names):
    have = sorted(d for d in os.listdir(GOLDEN) if os.path.isdir(os.path.join(GOLDEN, d, "post")))         if os.path.isdir(GOLDEN) else []
    if not have:
        sys.exit("no golden data in %s - run port.py golden" % GOLDEN)
    return names or have


def _convert_material(src, rel):
    return material.convert(open(src, encoding="utf-8-sig").read())


def _convert_model(src, rel):
    parts = rel.replace(os.sep, "/").split("/")
    # content/<dir>/<model>.mdl -> "<mod>::/<dir>/<model>.mdl"
    return model.convert(open(src, encoding="utf-8-sig").read(),
                         "golden::/" + "/".join(parts[1:]), os.path.dirname(src))


def compare_golden(names, show, ext, convert):
    stats = collections.Counter()
    total = same = data_same = errors = 0
    for v in golden_vehicles(names):
        pre = os.path.join(GOLDEN, v, "pre")
        n = s = ds = 0
        for d, _, files in os.walk(pre):
            for fn in sorted(files):
                if not fn.endswith(ext):
                    continue
                src = os.path.join(d, fn)
                rel = os.path.relpath(src, pre)
                want = open(os.path.join(GOLDEN, v, "post", rel), "rb").read()
                n += 1
                try:
                    got = convert(src, rel).encode("utf-8")
                except Exception as e:  # report and go on: one bad file should not hide the rest
                    errors += 1
                    print("  ERROR %s/%s: %s" % (v, rel, e))
                    continue
                if got == want:
                    s += 1
                    continue
                found = set()
                data_diff(luadata.parse(want.decode("utf-8-sig")), luadata.parse(got.decode("utf-8")), "", found)
                if not found:
                    ds += 1
                    stats[("layout only", "")] += 1
                for item in found:
                    stats[item] += 1
        print("%-14s %4d/%4d identical, %d equal as data" % (v, s, n, ds))
        total += n; same += s; data_same += ds
    print("total %d/%d identical, %d more equal as data, %d errors" % (same, total, data_same, errors))
    for (kind, path), k in stats.most_common(show):
        print("  %4d  %-12s %s" % (k, kind, path))
    return total - same


def main():
    args = sys.argv[1:]
    show = int(args[args.index("--show") + 1]) if "--show" in args else 40
    if "--show" in args:
        i = args.index("--show")
        args = args[:i] + args[i + 2:]
    if args and args[0] == "material":
        sys.exit(1 if compare_golden(args[1:], show, ".mtl", _convert_material) else 0)
    if args and args[0] == "model":
        sys.exit(1 if compare_golden(args[1:], show, ".mdl", _convert_model) else 0)
    if args and args[0] == "tree" and len(args) >= 3:
        sys.exit(1 if compare_tree(args[1], args[2], show) else 0)
    if not args or args[0] != "mesh":
        sys.exit(__doc__)
    names = args[1:] or vehicle_names()
    tot = [0, 0, 0]
    for name in names:
        r = compare_mesh(Vehicle(name), show=True)
        tot = [a + b for a, b in zip(tot, r)]
    print("total %d/%d identical, %d errors" % (tot[0], tot[0] + tot[1], tot[2]))
    sys.exit(1 if tot[1] or tot[2] else 0)


if __name__ == "__main__":
    main()
