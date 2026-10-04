"""One screen per ported vehicle from logs/port_<name>.log.

    python port.py summary <vehicle> ...

Pulls out the numbers that reveal silent breakage (model and material
counts, texture formats, problem lines from the editor, `check` results)
and every line that says MISSING / Error / Traceback.
"""
import os
import re
import sys


from tf3port.paths import LOGS

KEEP = re.compile(
    r"^(== |meshes \d|  dropped|  missing texture|  MISSING|PHYSICAL_NRML_MAP:|"
    r"\{'DXT1'|  DX10|  DXT|  BC|.*emitters ->|  replaced|\d+ wav copied|"
    r"\w+: \d+ problem lines|  \S.*(Error|error|not found|missing)|"
    r"missing refs|texture format mismatches|paths with uppercase|"
    r"disallowed|\d+ icons installed|missing \d+|Traceback|\w*Error:|"
    r"ABORTED|timed out|never started|stalled|.*exited)")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for name in sys.argv[1:]:
        p = os.path.join(LOGS, "port_%s.log" % name)
        if not os.path.exists(p):
            print("##### %s: no log" % name)
            continue
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
        print("##### %s" % name)
        seen = set()
        for l in lines:
            if not KEEP.match(l):
                continue
            # the editor repeats one error per model; show each once
            key = re.sub(r"'[^']*'", "''", l)
            if key in seen:
                continue
            seen.add(key)
            print("  " + l[:220])


if __name__ == "__main__":
    main()
