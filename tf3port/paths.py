"""Where things are on this machine.

Everything is found automatically, and any of it can be overridden in
`local_settings.json` in the workspace (not tracked by git):

    {
        "steam": "C:/Program Files (x86)/Steam",
        "tf3": "D:/SteamLibrary/steamapps/common/Transport Fever 3",
        "tf2": "D:/SteamLibrary/steamapps/common/Transport Fever 2",
        "tf3_local": "C:/Program Files (x86)/Steam/userdata/<id>/3493540/local",
        "tf2_workshop": "D:/SteamLibrary/steamapps/workshop/content/1066780"
    }

How each is found:
    steam         the SteamPath value Steam writes under HKCU\\Software\\Valve\\Steam
    tf3, tf2, workshop  the Steam libraries listed in steamapps/libraryfolders.vdf
                  (TF2 itself is optional: only for mods that use TF2's own or
                  DLC vehicles' files)
    tf3_local     userdata/<account folder>/<TF3 app id>/local - TF3 keeps the
                  staging area, screenshots and its log there. With several
                  Steam accounts on one PC, the most recently used one wins.

The workspace is the folder that holds your own files: `local_settings.json`,
`vehicles/` (your vehicle configs) and `logs/`. It is, in order:
    the TPF3KIT_WORKSPACE environment variable
    the current directory, if it has local_settings.json or vehicles/
    this repository
so the tool can live in one folder and your configs and copies of other
people's mods in another - run the commands from that other folder.
"""
import glob
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _workspace():
    if os.environ.get("TPF3KIT_WORKSPACE"):
        return os.path.abspath(os.environ["TPF3KIT_WORKSPACE"])
    here = os.getcwd()
    if (os.path.exists(os.path.join(here, "local_settings.json"))
            or os.path.isdir(os.path.join(here, "vehicles"))):
        return here
    return REPO


WORKSPACE = _workspace()

TF3_APP_ID = "3493540"
TF2_APP_ID = "1066780"

_SETTINGS = os.path.join(WORKSPACE, "local_settings.json")
_local = {}
if os.path.exists(_SETTINGS):
    _local = json.load(open(_SETTINGS, encoding="utf-8"))


def local_setting(key, default=None):
    return _local.get(key) or default


def _steam():
    if _local.get("steam"):
        return _local["steam"]
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return os.path.normpath(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return r"C:\Program Files (x86)\Steam"


def _libraries(steam):
    libs = [steam]
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf):
        for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8").read()):
            libs.append(os.path.normpath(m.group(1).replace("\\\\", "\\")))
    out = []
    for l in libs:
        if l not in out:
            out.append(l)
    return out


def _first(paths):
    return next((p for p in paths if os.path.isdir(p)), "")


STEAM = _steam()
LIBRARIES = _libraries(STEAM)

TF3 = _local.get("tf3") or _first(
    os.path.join(l, "steamapps", "common", "Transport Fever 3") for l in LIBRARIES)

TF2 = _local.get("tf2") or _first(
    os.path.join(l, "steamapps", "common", "Transport Fever 2") for l in LIBRARIES
    if os.path.isdir(os.path.join(l, "steamapps", "common", "Transport Fever 2", "res")))

WORKSHOP = _local.get("tf2_workshop") or _first(
    os.path.join(l, "steamapps", "workshop", "content", TF2_APP_ID) for l in LIBRARIES)


def _tf3_local():
    if _local.get("tf3_local"):
        return _local["tf3_local"]
    found = glob.glob(os.path.join(STEAM, "userdata", "*", TF3_APP_ID, "local"))
    return max(found, key=os.path.getmtime) if found else ""


TF3_LOCAL = _tf3_local()

TF3_BASE = os.path.join(TF3, "base", "content") if TF3 else ""
TF3_EXE = os.path.join(TF3, "TransportFever3.exe") if TF3 else ""
EDITOR_EXE = os.path.join(TF3, "model_editor", "ModelEditor.exe") if TF3 else ""

STAGING = os.path.join(TF3_LOCAL, "staging_area") if TF3_LOCAL else ""
SCREENSHOTS = os.path.join(TF3_LOCAL, "screenshots", "icons") if TF3_LOCAL else ""
SCREENSHOTS_ROOT = os.path.join(TF3_LOCAL, "screenshots") if TF3_LOCAL else ""
GAME_LOG = os.path.join(TF3_LOCAL, "crash_dump", "stdout.txt") if TF3_LOCAL else ""
SAVES = os.path.join(TF3_LOCAL, "save") if TF3_LOCAL else ""
EDITOR_SETTINGS = os.path.join(os.environ.get("APPDATA", ""), "Transport Fever 3",
                               "model_editor_settings_v13.lua")

# the workspace's own folders (not tracked)
LOGS = os.path.join(WORKSPACE, "logs")
VEHICLES = _local.get("vehicles") or os.path.join(WORKSPACE, "vehicles")
EXAMPLES = os.path.join(REPO, "examples", "vehicles")


def report():
    """What was found - `python port.py paths` prints this."""
    rows = [("workspace", WORKSPACE), ("steam", STEAM), ("tf3", TF3), ("tf3_local", TF3_LOCAL),
            ("tf2 (optional)", TF2), ("tf2_workshop", WORKSHOP), ("staging", STAGING),
            ("editor settings", EDITOR_SETTINGS), ("vehicles", VEHICLES)]
    for k, p in rows:
        print("%-16s %s %s" % (k, "ok " if p and os.path.exists(p) else "-- ", p or "(not found)"))
