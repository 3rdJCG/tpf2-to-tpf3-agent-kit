"""Drive the TF3 Model Editor from a script.

The Model Editor has no command line, no headless mode and no scripting hook -
the exe was checked for argument parsing and has none. Its UI is custom-drawn,
so UI Automation cannot see the controls either. That leaves clicking pixels.

What keeps that from being hopeless is that most of the state the bulk
operations read is *persisted in the settings file*, not typed into the window:

    pathOptions.lastOpenedMod          which mod the editor opens with
    toolsOptions.bulkFolder            prefix filter for Tools > Bulk *
    screenshotOptions.bulkPrefixFilter prefix filter for Icons > Bulk Generate

So a run is: patch the settings file, launch, click one tab and one button,
watch the log for the line that says the work finished, quit. Only the clicks
come from recorded coordinates; everything else is data.

Coordinates live in tf3port/editor_ui.json, recorded by port.py calibrate.
They are relative to the window's client area, and the window is pinned to a
fixed position and size (and uiScaling to 1) so they stay put. A game update
that moves the UI will break them; every operation therefore waits for its
specific "done" line in the log and fails loudly instead of quietly clicking
nothing.

Log lines, taken from the strings in ModelEditor.exe:

    Starting bulk converting of {} models  ...  Bulk converting done
    Starting bulk resaving of {} models    ...  Bulk resaving done
    Starting bulk validation of {} models  ...  Bulk validation done
    Processing vehicle {} of {}...         (Bulk Generate - no "done" line)
"""
import ctypes
import ctypes.wintypes
import json
import os
import re
import subprocess
import sys
import time

from .paths import EDITOR_EXE as EXE, EDITOR_SETTINGS as SETTINGS, LOGS, STAGING, TF3

LOG = os.path.join(LOGS, "model_editor.log")
UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editor_ui.json")

# The window is pinned here so recorded coordinates keep meaning something.
WINDOW_POS = (0, 23)
WINDOW_SIZE = (1920, 1009)

ANSI = re.compile(r"\x1b\[[0-9;]*m")
user32 = ctypes.windll.user32


# --------------------------------------------------------------------------
# settings file


def _set(text, section, key, lua):
    """Replace `key = <value>,` directly inside top-level `section`.

    Walks lines and tracks brace depth so that a same-named key in a nested
    table (screenshotOptions.sideConfig.maxWidth etc.) is never touched.
    """
    lines = text.split("\n")
    head = re.compile(r"^\t\t%s = \{\s*$" % re.escape(section))
    entry = re.compile(r"^(\t*%s = ).*,\s*$" % re.escape(key))
    inside = False
    depth = 0
    for n, line in enumerate(lines):
        if not inside:
            inside = bool(head.match(line))
            depth = 1 if inside else 0
            continue
        if depth == 1:
            m = entry.match(line)
            if m:
                lines[n] = m.group(1) + lua + ","
                return "\n".join(lines)
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
    sys.exit("%s: no %s.%s" % (SETTINGS, section, key))


def quote(s):
    """A Lua string literal. Paths must use forward slashes - a backslash here
    is read as an escape (\\u, \\8) and silently corrupts the path."""
    return '"%s"' % s.replace("\\", "/").replace('"', '\\"')


def configure(**kw):
    """Patch the settings file. Keys are 'section.key'; values are Lua source.

    The editor rewrites this file on exit, so this has to run before launch
    and while no editor is open.
    """
    text = open(SETTINGS, encoding="utf-8-sig").read()
    for dotted, lua in kw.items():
        section, key = dotted.split(".")
        text = _set(text, section, key, lua)
    # the editor writes CRLF; keep it so a diff shows only what changed
    open(SETTINGS, "w", encoding="utf-8", newline="\r\n").write(text)


def pin_window():
    """Fix the things that move the controls around under the mouse."""
    configure(**{
        "applicationOptions.windowPos": "{ %d, %d, }" % WINDOW_POS,
        "applicationOptions.windowSize": "{ %d, %d, }" % WINDOW_SIZE,
        "renderOptions.uiAutoScaling": "false",
        "renderOptions.uiScaling": "1",
    })


def tools_mod_index(mod_id):
    """The Tools tab's 'Target mod' is stored as an index, not an id
    (toolsOptions.selectedExportModId). It indexes the staging mods sorted by
    name, from 0 - checked against the dropdown at indices 0-4 and 5/10/15/20.

    The bulk operations do NOT use it: for weeks this index was one too high
    and every Bulk Convert / Validation still worked on the opened mod (the
    paths in the log were always the right vehicle's). It is most likely the
    destination of Copy Loaded Model. It is set anyway so the dropdown agrees
    with the opened mod - and because an index past the end of the list
    crashes the editor at startup (ComboBox::SetSelected assertion)."""
    # only real mods: the editor drops a .vscode workspace folder in here,
    # which it does not list. Counting it put every index one too high -
    # harmless while it still landed on some mod, a crash for the last one.
    mods = sorted(d for d in os.listdir(STAGING)
                  if os.path.exists(os.path.join(STAGING, d, "mod.json")))
    if mod_id not in mods:
        sys.exit("%s is not in %s" % (mod_id, STAGING))
    return mods.index(mod_id)


def select_mod(mod_id, prefix=""):
    """Point every part of the editor at `mod_id`.

    The mod the editor opens is what every bulk operation works on; the Tools
    tab's 'Target mod' is kept in step with it (see tools_mod_index). Both
    bulk prefixes are set to `prefix`.
    """
    configure(**{
        "pathOptions.lastOpenedMod": "{ %s, }" % quote(mod_id),
        "pathOptions.lastOpenedSubPath": quote(""),
        "toolsOptions.selectedExportModId": str(tools_mod_index(mod_id)),
        "toolsOptions.bulkFolder": quote(prefix),
        "screenshotOptions.bulkPrefixFilter": quote(prefix),
    })


# --------------------------------------------------------------------------
# process and window


def running():
    """Pids of any Model Editor already open. Two at once fight over the
    settings file, and an old one has a stale content index."""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ModelEditor.exe",
                          "/FO", "CSV", "/NH"], capture_output=True, text=True)
    return [int(row.split('","')[1]) for row in out.stdout.splitlines()
            if row.startswith('"ModelEditor.exe"')]


class Editor(object):
    def __init__(self):
        if running():
            sys.exit("a Model Editor is already open - close it first.\n"
                     "It indexes content once at startup, and on exit it would\n"
                     "overwrite the settings this run depends on.")
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        env = dict(os.environ)
        env["PATH"] = (os.path.join(TF3, "model_editor", "plugins") + ";"
                       + env["PATH"])
        self.log = open(LOG, "wb")
        self.log.write(("==== run %s ====\n"
                        % time.strftime("%Y-%m-%d %H:%M:%S")).encode())
        self.log.flush()
        self.offset = self.log.tell()
        self.proc = subprocess.Popen([EXE], cwd=TF3, env=env, stdout=self.log,
                                     stderr=subprocess.STDOUT)
        self.hwnd = None

    # -- log ---------------------------------------------------------------

    def read_log(self):
        """Everything logged since the last call, minus the colour codes."""
        with open(LOG, "rb") as f:
            f.seek(self.offset)
            raw = f.read()
        # only consume whole lines so a match is never split across reads
        cut = raw.rfind(b"\n") + 1
        self.offset += cut
        return ANSI.sub("", raw[:cut].decode("utf-8", "replace"))

    # -- window ------------------------------------------------------------

    def _find_window(self):
        """Found by process id, not title - the title is undocumented."""
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def cb(hwnd, _):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.proc.pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        user32.EnumWindows(cb, 0)
        return found[0] if found else None

    def wait_ready(self, timeout=180):
        """Wait for the window, then for the startup content load to settle.

        There is no "ready" line, so readiness is "the window exists and the
        log has been quiet for a few seconds".
        """
        deadline = time.time() + timeout
        while not self.hwnd:
            if self.proc.poll() is not None:
                sys.exit("model editor exited during startup. See %s" % LOG)
            if time.time() > deadline:
                sys.exit("model editor window never appeared")
            self.hwnd = self._find_window()
            # the window exists at 0x0 for a moment before it is sized - and
            # stays 0x0 if it came up minimised, which happened right after
            # another editor had crashed. Restore it and look again.
            if self.hwnd and self.client_rect()[2] == 0:
                user32.ShowWindow(self.hwnd, 9)      # SW_RESTORE
                self.hwnd = None
            time.sleep(0.5)
        quiet = time.time()
        while time.time() - quiet < 5:
            if self.read_log():
                quiet = time.time()
            if time.time() > deadline:
                break
            time.sleep(0.5)
        self.check_size()

    def client_rect(self):
        """(left, top, width, height) of the client area in screen pixels."""
        r = ctypes.wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(r))
        pt = ctypes.wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        return pt.x, pt.y, r.right, r.bottom

    def check_size(self):
        ui = load_ui(required=False)
        if not ui:
            return
        _, _, w, h = self.client_rect()
        for _ in range(10):                     # minimised: restore, re-measure
            if w:
                break
            user32.ShowWindow(self.hwnd, 9)     # SW_RESTORE
            time.sleep(1)
            _, _, w, h = self.client_rect()
        if [w, h] != ui["client"]:
            sys.exit("window client area is %dx%d but calibration was done at "
                     "%dx%d.\nCoordinates would be off. Recalibrate."
                     % (w, h, ui["client"][0], ui["client"][1]))

    def focus(self):
        """Bring the editor to the front. Windows refuses SetForegroundWindow
        from a background process unless it just saw input, so tap Alt first."""
        import pyautogui
        user32.ShowWindow(self.hwnd, 9)          # SW_RESTORE
        if user32.GetForegroundWindow() != self.hwnd:
            pyautogui.press("alt")
            user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.5)

    def click(self, name):
        import pyautogui
        ui = load_ui()
        if name not in ui["targets"]:
            sys.exit("%s has no target %r - recalibrate" % (UI, name))
        t = ui["targets"][name]
        left, top, _, _ = self.client_rect()
        self.focus()
        if isinstance(t, dict):
            # {"scroll": [x, y, clicks]}: wheel over a panel, e.g. to reach a
            # button below the fold. Overshooting to the end is deliberate -
            # the bottom of a panel is a stable place to measure from.
            x, y, n = t["scroll"]
            pyautogui.moveTo(left + x, top + y, duration=0.3)
            # pyautogui passes the amount straight to mouse_event on Windows,
            # where one notch is WHEEL_DELTA = 120; scroll(-1) moves nothing
            for _ in range(abs(n)):
                pyautogui.scroll(-120 if n < 0 else 120)
                time.sleep(0.03)
            time.sleep(0.8)
            return
        x, y = t
        # The UI polls input once per frame and wants to see hover before a
        # press; pyautogui.click()'s instant down/up is silently dropped.
        pyautogui.moveTo(left + x, top + y, duration=0.3)
        time.sleep(0.3)
        pyautogui.mouseDown()
        time.sleep(0.15)
        pyautogui.mouseUp()
        time.sleep(1.0)

    def close(self, timeout=60):
        if self.proc.poll() is None and self.hwnd:
            user32.PostMessageW(self.hwnd, 0x0010, 0, 0)   # WM_CLOSE
            deadline = time.time() + timeout
            while self.proc.poll() is None and time.time() < deadline:
                time.sleep(0.5)
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait()
        self.log.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def load_ui(required=True):
    if not os.path.exists(UI):
        if required:
            sys.exit("no %s - run:\n    python port.py calibrate" % UI)
        return None
    return json.load(open(UI, encoding="utf-8"))


# --------------------------------------------------------------------------
# operations


# Which clicks each operation needs, and how to read its progress in the log.
#   start  - first line; group 1 is the model count
#   item   - one line per model; group 1 is the model path, which is checked
#            against the vehicle folder (see run)
#   done   - last line, or None when the editor never prints one
OPS = {
    "convert": dict(
        clicks=["tab_tools", "bulk_convert"],
        start=r"Starting bulk converting of (\d+) models",
        item=r"\]\s+Converting (\S+)", done=r"Bulk converting done"),
    "resave": dict(
        clicks=["tab_tools", "bulk_resave"],
        start=r"Starting bulk resaving of (\d+) models",
        item=r"\]\s+Resaving (\S+)", done=r"Bulk resaving done"),
    "validate": dict(
        clicks=["tab_tools", "bulk_validation"],
        start=r"Starting bulk validation of (\d+) models",
        item=r"\]\s+Validating (\S+)", done=r"Bulk validation done"),
    "genicons": dict(
        clicks=["tab_icons", "scroll_panel_end", "bulk_generate"],
        start=r"Processing vehicle \d+ of (\d+)",
        item=r"\]\s+Opening (?:[\w.-]+::/)?(\S+)", done=None),
}

# Seconds without any new log line before giving up on a running operation.
STALL = 180


def run(mod_id, content_dir, ops, prefix=""):
    """Open the editor on `mod_id`, run each op in `ops` in turn, close it.

    Every model path the editor reports must sit under `content_dir`; the
    first one that does not kills the editor. That is the guard against the
    editor working on some other mod than intended, because Bulk Convert on
    an already-converted mod is not something to find out about afterwards
    (it caught nothing so far - the mods were always right). A `convert`
    is always preceded by a `validate`: validation is read-only, so a wrong
    target is caught before anything is written.

    Returns {op: log text of that op} for the caller to pick errors out of.
    """
    load_ui()
    if "convert" in ops and "validate" not in ops[:ops.index("convert")]:
        i = ops.index("convert")
        ops = ops[:i] + ["guard"] + ops[i:]
    pin_window()
    select_mod(mod_id, prefix)
    out = {}
    with Editor() as ed:
        ed.wait_ready()
        ed.click("menu")        # a toggle: open the Options panel once only
        for op in ops:
            if op == "guard":
                # its findings are about the unconverted TF2 models - only
                # the paths matter here, so the log text is not returned
                print("-- editor: validate (target mod check before convert)")
                watch(ed, op, OPS["validate"], mod_id, content_dir)
                continue
            print("-- editor: %s" % op)
            out[op] = watch(ed, op, OPS[op], mod_id, content_dir)
    return out


def watch(ed, op, spec, mod_id, content_dir):
    for c in spec["clicks"]:
        ed.click(c)
    seen = ""
    total = None
    items = []
    started = time.time()
    last = time.time()
    while True:
        chunk = ed.read_log()
        if chunk:
            last = time.time()
            for line in chunk.splitlines():
                seen += line + "\n"
                m = re.search(spec["start"], line)
                if m and total is None:
                    total = int(m.group(1))
                    print("   %d models" % total)
                    if total == 0:
                        ed.close()
                        sys.exit("%s found no models in %s - wrong prefix?"
                                 % (op, mod_id))
                m = re.search(spec["item"], line)
                if m and total is not None:
                    path = m.group(1)
                    items.append(path)
                    print("   [%d/%d] %s" % (len(items), total, path))
                    if not path.replace("\\", "/").startswith(content_dir + "/"):
                        ed.proc.kill()
                        sys.exit("ABORTED: %s is working on %s, which is not in "
                                 "%s/.\nThe editor's target mod is wrong. Killed "
                                 "it before it got further." % (op, path, content_dir))
                if spec["done"] and re.search(spec["done"], line):
                    return seen
        if total is None and time.time() - started > 30:
            ed.close()
            sys.exit("%s never started - the click missed.\n"
                     "The UI may have moved. Check with:\n"
                     "    python port.py calibrate --shot menu %s\n"
                     "Log: %s" % (op, " ".join(spec["clicks"]), LOG))
        # Bulk Generate has no done line: done is "every model opened and the
        # log has gone quiet"
        if (not spec["done"] and total is not None and len(items) >= total
                and time.time() - last > 8):
            return seen
        if time.time() - last > STALL:
            ed.close()
            sys.exit("%s stalled: no log output for %ds (%d of %s models). "
                     "Log: %s" % (op, STALL, len(items), total, LOG))
        if ed.proc.poll() is not None:
            sys.exit("model editor exited during %s. Log: %s" % (op, LOG))
        time.sleep(0.5)


def problems(text):
    """ERROR / WARNING lines from a slice of editor log, minus the UI sound
    warnings (alutCreateBufferFromFile) that every click produces."""
    return [l for l in text.splitlines()
            if re.search(r" - (ERROR|WARNING) |\]\s+Error ", l)
            and "alutCreateBufferFromFile" not in l]


def open_by_hand():
    """`port.py editor`: open the Model Editor for hands-on work, the way its
    own ModelEditor.bat does, but with its output kept in logs/model_editor.log.
    Errors otherwise only flash by on screen."""
    if running():
        sys.exit("a Model Editor is already open")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = os.path.join(TF3, "model_editor", "plugins") + ";" + env["PATH"]
    with open(LOG, "wb") as log:
        log.write(("==== run %s ====\n" % time.strftime("%Y-%m-%d %H:%M:%S")).encode())
        log.flush()
        print("Model Editor open; its log goes to %s (closes when you close it)" % LOG)
        subprocess.call([EXE], cwd=TF3, env=env, stdout=log, stderr=subprocess.STDOUT)
    print("log: %s" % LOG)
