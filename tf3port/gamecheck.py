"""gamecheck: the game's own validator, run headless
(TransportFever3.exe --validate).
"""
import collections
import json
import os
import re
import sys

from .paths import LOGS, TF3_APP_ID, TF3_EXE


def cmd_gamecheck(v):
    """Run the game's built-in mod validator, headless.

        TransportFever3.exe --validate StagingArea,<modId> <out.json>

    It loads the mod the way the game does - model data verification, sound
    set references, WAV format, file names, mod size - which the Model
    Editor's Bulk Validation does not: that passed every mod whose sounds
    then failed in game. No window opens; it takes 10-30 s per mod.

    Launched directly, steam_api restarts the exe through Steam and exits
    with 53 having done nothing; SteamAppId in the environment prevents that.
    """
    import subprocess
    out = os.path.join(LOGS, "validate", v.mod_id + ".json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    env = dict(os.environ, SteamAppId=TF3_APP_ID, SteamGameId=TF3_APP_ID)
    r = subprocess.run([TF3_EXE, "--validate", "StagingArea," + v.mod_id, out],
                       cwd=os.path.dirname(TF3_EXE), env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=900)
    if not os.path.exists(out):
        sys.exit("the game's validator wrote nothing (exit %d). Is the game "
                 "running? Close it first." % r.returncode)
    res = json.load(open(out, encoding="utf-8"))
    groups = collections.Counter()
    messages = res.get("messages") or []
    for m in messages:
        first = m["message"].split("\n")[0]
        groups[(m["level"], m.get("context", ""), re.sub(r"\d+(\.\d+)?", "N", first))] += 1
    print("game validator: PC %s%s, %d messages -> logs/validate/%s.json" % (
        res.get("levelPc"), " (CRITICAL)" if res.get("criticalPc") else "",
        len(messages), v.mod_id))
    order = {"Critical": 0, "Error": 1, "Warning": 2}
    for (level, ctx, msg), n in sorted(groups.items(),
                                       key=lambda kv: (order.get(kv[0][0], 3), -kv[1])):
        print("  %-7s x%-3d %s: %s" % (level, n, ctx, msg[:170]))
