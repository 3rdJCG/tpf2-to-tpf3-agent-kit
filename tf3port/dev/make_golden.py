"""B-0: golden data for Phase B - what the Model Editor's Bulk Convert makes of
`build`'s output, with nothing from `post` on top.

For each vehicle: copy vehicles/<v>.json to <v>_golden.json with modId +
"_golden", run `build`, keep the staging as work/golden/<v>/pre, run `convert`,
keep it as work/golden/<v>/post, then delete the copy's staging and config.
The live mods are not touched. Textures are left out of both copies (convert
does not change them, and they are gigabytes).

    python port.py golden [vehicle ...]      (default: every config)

Output: <workspace>/work/golden/<vehicle>/{pre,post,golden.json} and a log
beside them. About 30-40 s per vehicle; the Model Editor runs for each, so
keep hands off the mouse. Remake the data after a game update - the editor's
output is what Phase B is held to (docs/roadmap.md, B-0).
"""
import json
import os
import shutil
import subprocess
import sys
import time

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tf3port.common import vehicle_names
from tf3port.paths import STAGING, VEHICLES, WORKSPACE as WS

SKIP_EXT = {".tga", ".dds", ".png"}
OUT = os.path.join(WS, "work", "golden")


def keep(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    n = 0
    for d, _, files in os.walk(src):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            rel = os.path.relpath(os.path.join(d, fn), src)
            os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
            shutil.copy2(os.path.join(d, fn), os.path.join(dst, rel))
            n += 1
    return n


def port(name, *steps, log):
    with open(log, "a", encoding="utf-8") as f:
        f.write("\n==== %s %s\n" % (time.strftime("%H:%M:%S"), " ".join(steps)))
        f.flush()
        r = subprocess.run([sys.executable, os.path.join(KIT, "port.py"), name] + list(steps),
                           stdout=f, stderr=subprocess.STDOUT, cwd=WS,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return r.returncode


def one(v):
    src_cfg = os.path.join(VEHICLES, v + ".json")
    cfg = json.load(open(src_cfg, encoding="utf-8"))
    gname = v + "_golden"
    cfg["modId"] += "_golden"
    cfg["modName"] = cfg.get("modName", v) + " (golden)"
    gcfg = os.path.join(VEHICLES, gname + ".json")
    json.dump(cfg, open(gcfg, "w", encoding="utf-8"), indent=4, ensure_ascii=False)
    staged = os.path.join(STAGING, cfg["modId"])
    log = os.path.join(OUT, v + ".log")
    os.makedirs(OUT, exist_ok=True)
    open(log, "w").close()
    try:
        if port(gname, "build", log=log):
            return "build failed"
        n_pre = keep(staged, os.path.join(OUT, v, "pre"))
        if port(gname, "convert", log=log):
            return "convert failed"
        n_post = keep(staged, os.path.join(OUT, v, "post"))
        json.dump({"vehicle": v, "modId": cfg["modId"], "liveModId": cfg["modId"][:-len("_golden")],
                   "made": time.strftime("%Y-%m-%d %H:%M"), "files_pre": n_pre, "files_post": n_post},
                  open(os.path.join(OUT, v, "golden.json"), "w"), indent=2)
        return "ok (%d / %d files)" % (n_pre, n_post)
    finally:
        if os.path.exists(staged):
            shutil.rmtree(staged, ignore_errors=True)
        os.remove(gcfg)


def main():
    names = sys.argv[1:] or vehicle_names()
    unknown = [v for v in names if not os.path.exists(os.path.join(VEHICLES, v + ".json"))]
    if unknown:
        sys.exit(__doc__ + "\nno config for: %s (in %s)" % (", ".join(unknown), VEHICLES))
    for v in names:
        t = time.time()
        r = one(v)
        print("%-12s %-30s %4.0fs" % (v, r, time.time() - t), flush=True)


if __name__ == "__main__":
    main()
