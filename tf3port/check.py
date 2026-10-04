"""check: our own checks on a converted mod - every reference resolves,
textures are in the formats TF3 asks for, paths are lowercase.
"""
import os
import re

from .common import read
from .textures import formats_from_materials


def cmd_check(v):
    missing = []
    for root, _, files in os.walk(v.veh):
        for fn in files:
            if not fn.endswith((".mdl", ".mtl")):
                continue
            p = os.path.join(root, fn)
            for ref in re.findall(r'"((?:msh|mat|tex|ani|icons)/[^"]+)"', read(p)):
                if not os.path.exists(os.path.join(os.path.dirname(p),
                                                   ref.replace("/", os.sep))):
                    missing.append("%s -> %s" % (os.path.relpath(p, v.veh), ref))
    # the editor only says this on screen, never in the log, so check it here:
    # a sampler bound to the wrong compression is a warning per material
    wrong = []
    fmt, _ = formats_from_materials(v)
    for key, want in sorted(fmt.items()):
        p = os.path.join(v.veh, "mat", "tex", key.replace("/", os.sep) + ".dds")
        if not os.path.exists(p):
            continue
        got = open(p, "rb").read(88)[84:88].decode("latin1")
        if got != want:
            wrong.append("%s is %s, wants %s" % (key, got, want))

    bad = [os.path.join(r, f) for r, _, fs in os.walk(v.veh) for f in fs
           if f != f.lower()]
    grp = [f for _, _, fs in os.walk(v.veh) for f in fs if f.endswith(".grp")]
    print("missing refs: %d" % len(missing))
    for m in missing[:20]:
        print("  " + m)
    print("texture format mismatches: %d" % len(wrong))
    for w in wrong[:10]:
        print("  " + w)
    print("paths with uppercase: %d" % len(bad))
    print("disallowed .grp files: %d" % len(grp))
    # references spelled with capitals to files that exist in lowercase: the
    # game dies loading them (resource::Fixer::Model assertion), the editor
    # and the validator do not notice
    upper = []
    for root, _, fs in os.walk(v.veh):
        for fn in fs:
            if fn.endswith((".mdl", ".mtl", ".lua")):
                for ref in re.findall(r'"([^"]*[A-Z][^"]*\.(?:mdl|mtl|msh|ani|dds|tga|snd))"',
                                      read(os.path.join(root, fn))):
                    if not ref.startswith("::/"):
                        upper.append("%s: %s" % (fn, ref))
    print("references with uppercase: %d" % len(upper))
    for u in upper[:10]:
        print("  " + u)
