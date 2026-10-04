"""Record where the Model Editor's buttons are, for tf3port/editor.py.

    python port.py calibrate --shot [NAME ...]  # click, screenshot
    python port.py calibrate --test NAME        # hover over a target
    python port.py calibrate                    # hover + Enter for each

Redo this after a game update moves the UI. The usual way is --shot: it opens
the editor, clicks the named targets in order and saves a screenshot after
each into logs/calibration/, from which the new coordinates can be read off:

    python port.py calibrate --shot menu tab_tools
    python port.py calibrate --shot menu tab_icons scroll_panel_end

The editor is launched with the pinned window size and UI scale (see
editor.pin_window). Coordinates in tf3port/editor_ui.json are relative to the
window's client area, stored with the client size they were taken at;
editor.py refuses to click if the size differs.

Where things are (1920x1009, uiScaling 1):
    menu              the "hamburger" at the far top right; opens Options
    tab_tools/icons   tabs along the top of the Options panel
    bulk_*            full-width buttons in the Tools tab
    scroll_panel_end  wheel over the Options panel until the bottom
    bulk_generate     Icons tab, bottom of the panel (needs the scroll)
"""
import argparse
import json
import os
import sys
import time

from tf3port import editor
from tf3port.paths import LOGS, STAGING

# (name, clicks that make it visible once the Options panel is open, prompt)
TARGETS = [
    ("tab_tools", [], "the 'Tools' tab of the Options panel"),
    ("bulk_resave", ["tab_tools"], "the 'Bulk Resave' button"),
    ("bulk_convert", ["tab_tools"], "the 'Bulk Convert' button"),
    ("bulk_validation", ["tab_tools"], "the 'Bulk Validation' button"),
    ("tab_icons", [], "the 'Icons' tab of the Options panel"),
    ("bulk_generate", ["tab_icons", "scroll_panel_end"],
     "the 'Bulk Generate' button"),
]

SHOTS = os.path.join(LOGS, "calibration")


def shot(ed, name):
    import pyautogui
    os.makedirs(SHOTS, exist_ok=True)
    left, top, w, h = ed.client_rect()
    path = os.path.join(SHOTS, name + ".png")
    pyautogui.screenshot(region=(left, top, w, h)).save(path)
    print("   saved %s" % path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shot", nargs="*", metavar="NAME",
                    help="click these recorded targets in order, saving a "
                         "screenshot after each, instead of recording")
    ap.add_argument("--test", metavar="NAME",
                    help="open the editor and hover over a recorded target")
    ap.add_argument("--mod", help="staging mod to open (default: the first "
                                   "one with a mod.json)")
    args = ap.parse_args()
    if not args.mod:
        mods = sorted(d for d in os.listdir(STAGING)
                      if os.path.exists(os.path.join(STAGING, d, "mod.json")))
        if not mods:
            sys.exit("no mod in %s - port one first" % STAGING)
        args.mod = mods[0]

    import pyautogui

    editor.pin_window()
    editor.select_mod(args.mod)
    with editor.Editor() as ed:
        print("waiting for the editor to finish loading...")
        ed.wait_ready()
        left, top, w, h = ed.client_rect()
        print("client area %dx%d at (%d, %d)" % (w, h, left, top))
        ed.focus()

        if args.shot is not None:
            shot(ed, "start")
            for name in args.shot:
                ed.click(name)
                time.sleep(1)
                shot(ed, name)
            return

        if args.test:
            ed.click("menu")
            for name, before, _ in TARGETS:
                if name == args.test:
                    for b in before:
                        ed.click(b)
            x, y = editor.load_ui()["targets"][args.test]
            pyautogui.moveTo(left + x, top + y, duration=0.3)
            input("mouse is on %r. Enter to close the editor." % args.test)
            return

        ui = {"client": [w, h], "targets": {}}
        if os.path.exists(editor.UI):
            ui["targets"] = editor.load_ui()["targets"]
        json.dump(ui, open(editor.UI, "w", encoding="utf-8"), indent=4)

        def record(name, desc):
            input("\nPoint the mouse at %s, then press Enter here.\n"
                  "(Do not click it.) " % desc)
            mx, my = pyautogui.position()
            ui["targets"][name] = [mx - left, my - top]
            json.dump(ui, open(editor.UI, "w", encoding="utf-8"), indent=4)
            print("   %s = %s" % (name, ui["targets"][name]))

        record("menu", "the menu button at the far top right (three lines)")
        ed.click("menu")
        for name, before, desc in TARGETS:
            for b in before:
                ed.click(b)     # also proves the coordinates just recorded
            record(name, desc)
        print("\nwrote %s" % editor.UI)


if __name__ == "__main__":
    main()
