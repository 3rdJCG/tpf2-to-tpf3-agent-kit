"""Write vehicles/<name>.json for a TF2 workshop mod.

    python port.py new <workshop id> <name> <modId> [contentDir]

Fills in the mod's name, authors and tags from its mod.lua, and says what the
port will run into: light lists (*Parts convert by themselves, *Lights need a
`lights` mapping), particle emitters, consists, sound sets, and a non-empty
runFn (Lua that needs a TF3 equivalent - a separate job).
"""
import json
import os
import re
import sys

from tf3port.paths import VEHICLES, WORKSHOP


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    wid, name, mod_id = sys.argv[1:4]
    content = sys.argv[4] if len(sys.argv) > 4 else name
    src = os.path.join(WORKSHOP, wid)
    if not os.path.isdir(src):
        sys.exit("not downloaded: %s - subscribe to it in TF2 first" % src)
    os.makedirs(VEHICLES, exist_ok=True)
    out = os.path.join(VEHICLES, name + ".json")
    if os.path.exists(out):
        sys.exit("%s exists" % out)
    ml = open(os.path.join(src, "mod.lua"), encoding="utf-8", errors="replace").read()
    title = re.search(r'name\s*=\s*_?\(?\s*"([^"]*)"', ml).group(1)
    authors = [{"name": a, "role": "CREATOR"}
               for a in re.findall(r'name\s*=\s*"([^"]*)",\s*\n\s*role', ml)]

    parts = lights = emitters = 0
    for root, _, files in os.walk(os.path.join(src, "res", "models", "model")):
        for fn in files:
            if fn.endswith(".mdl"):
                t = open(os.path.join(root, fn), encoding="utf-8",
                         errors="replace").read()
                parts += len(re.findall(r"\w+Parts = \{\s*\d", t))
                lights += len(re.findall(r"\w+Lights\d? = \{\s*\d", t))
                emitters += len(re.findall(r"emitters\s*=\s*\{\s*\{", t))
    cfg = {
        "modId": mod_id,
        "modName": "%s (TF2 port WIP)" % title,
        "description": "TF2 %s (workshop %s) imported for TF3 porting tests."
                       % (title, wid),
        "authors": authors,
        "tags": ["Vehicle", "Train"],
        "workshopId": wid,
        "contentDir": content,
        "invertMgaGreen": True,
        "tailLights": [],
        "lights": {},
    }
    json.dump(cfg, open(out, "w", encoding="utf-8"), indent=4, ensure_ascii=False)
    print("wrote %s  (%s)" % (out, title))
    print("  *Parts lists: %d, *Lights lists: %d%s" % (
        parts, lights, "  <- needs a `lights` mapping" if lights and not parts else ""))
    if emitters:
        print("  particle emitters: %d  <- check `particles` in the config" % emitters)
    run = re.search(r"runFn\s*=\s*function\s*\([^)]*\)(.*?)\bend\b", ml, re.S)
    if run and run.group(1).strip():
        print("  runFn is not empty  <- read it before porting:\n    %s"
              % run.group(1).strip()[:300])


if __name__ == "__main__":
    main()
