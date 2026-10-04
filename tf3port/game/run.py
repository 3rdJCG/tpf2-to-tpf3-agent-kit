"""Launch Transport Fever 3 with command-line arguments and wait for it.

    python port.py game [--timeout S] [--log FILE] -- <game args...>

The game is started the way Steam would (SteamAppId in the environment, so
steam_api does not bounce it through Steam), its stdout is kept, and it is
killed after --timeout seconds if it has not quit by itself.
"""
import os
import subprocess
import sys
import time

from ..paths import GAME_LOG, TF3_APP_ID as APP_ID, TF3_EXE as EXE




def crashed(since):
    """The game's own log says it hit a fatal error after `since`. It then
    sits in its crash handler instead of exiting, so waiting is pointless."""
    try:
        if os.path.getmtime(GAME_LOG) < since:
            return False
        with open(GAME_LOG, "rb") as f:
            return b"Calling HandleCrash" in f.read()
    except OSError:
        return False


def run(args, timeout=120, log=None):
    env = dict(os.environ, SteamAppId=APP_ID, SteamGameId=APP_ID)
    out = open(log, "wb") if log else subprocess.DEVNULL
    t = time.time()
    p = subprocess.Popen([EXE] + args, cwd=os.path.dirname(EXE), env=env,
                         stdout=out, stderr=subprocess.STDOUT)
    while p.poll() is None and time.time() - t < timeout:
        time.sleep(1)
        if crashed(t):
            print("game crashed - see %s" % GAME_LOG)
            time.sleep(3)
            break
    killed = p.poll() is None
    if killed:
        p.kill()
        p.wait()
    if log:
        out.close()
    return p.returncode, killed, time.time() - t


def main():
    a = sys.argv[1:]
    timeout, log = 120, None
    while a and a[0] != "--":
        if a[0] == "--timeout":
            timeout = int(a[1]); a = a[2:]
        elif a[0] == "--log":
            log = a[1]; a = a[2:]
        else:
            sys.exit(__doc__)
    if len(a) < 2:
        sys.exit(__doc__)
    code, killed, secs = run(a[1:], timeout, log)
    print("exit=%s killed=%s after %.0fs" % (code, killed, secs))


if __name__ == "__main__":
    main()
