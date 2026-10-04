"""Summarise the game's own log for the ported mods.

    python port.py gamelog            # all staging mods
    python port.py gamelog <modId>    # one mod id

Reads <userdata>/local/crash_dump/stdout.txt - the game's log of its latest
session - and groups every WARNING / ERROR that names a mod by mod and by
message, with numbers flattened so repeats collapse.

The Model Editor's Bulk Validation only proves a model loads. Missing sound
sets, broken groupFileName references and textures that resolve to nothing
only show up here, after the game has loaded the mods.
"""
import collections
import re
import sys

from ..paths import GAME_LOG as LOG

ANSI = re.compile(r"\x1b\[[0-9;]*m")
NOISE = ("Preserved props", "It has been created by", "gamepad-only",
         "Multiple (2) mods with same id")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only = sys.argv[1:]
    lines = ANSI.sub("", open(LOG, encoding="utf-8", errors="replace").read()).splitlines()
    by_mod = collections.defaultdict(collections.Counter)
    i = 0
    while i < len(lines):
        l = lines[i]
        if re.search(r" - (WARNING|ERROR) ", l) and not any(n in l for n in NOISE):
            msg = l.split("]", 1)[-1].strip().lstrip("+ ").strip()
            # multi-line entries continue with "    + " / "    | "
            j = i + 1
            while j < len(lines) and re.match(r"^\s+[+|]", lines[j]):
                msg += " " + lines[j].strip().lstrip("+| ").strip()
                j += 1
            mods = re.findall(r"([a-z0-9_]+)::/", msg) or ["(no mod named)"]
            for m in set(mods):
                if only and m not in only:
                    continue
                by_mod[m][re.sub(r"\d+", "N", msg)[:300]] += 1
            i = j
            continue
        i += 1
    for mod in sorted(by_mod):
        print("##### %s" % mod)
        for msg, n in by_mod[mod].most_common():
            print("  %4d  %s" % (n, msg))


if __name__ == "__main__":
    main()
