"""The one entry point: `python port.py ...` (or `python -m tf3port ...`).

    python port.py <vehicle> <steps...>      port a vehicle (steps: see `port.py <vehicle> -h`)
    python port.py new <workshopId> <name> <modId> [contentDir]
                                              write vehicles/<name>.json from the mod
    python port.py summary <vehicle...>      counts and errors from logs/port_<vehicle>.log
    python port.py smoke <vehicle...>        in game: photograph every model
    python port.py drive <vehicle...>        in game: run a train on a test line (optional)
    python port.py gamelog [modId]           the game's log, grouped by mod
    python port.py game [--timeout S] -- <args...>   start TF3 with arguments
    python port.py editor                    open the Model Editor with its log kept
    python port.py paths                     where everything was found

  for working on the converter itself:
    python port.py golden [vehicle...]       reference output from the Model Editor
    python port.py compare-convert mesh|material|model|tree ...
    python port.py compare-icons [vehicle...]
    python port.py calibrate ...             re-measure the Model Editor's buttons

Run it from your workspace (the folder with vehicles/ and local_settings.json).
"""
import importlib
import sys

# command -> module with a main() that reads sys.argv
COMMANDS = {
    "new": "tf3port.new_vehicle",
    "summary": "tf3port.summary",
    "smoke": "tf3port.game.smoke",
    "drive": "tf3port.game.drive",
    "gamelog": "tf3port.game.log",
    "game": "tf3port.game.run",
    "golden": "tf3port.dev.make_golden",
    "compare-convert": "tf3port.dev.compare_convert",
    "compare-icons": "tf3port.dev.compare_icons",
    "calibrate": "tf3port.dev.calibrate_editor",
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return
    cmd = argv[0]
    if cmd == "paths":
        from .paths import report
        return report()
    if cmd == "editor":
        from .editor import open_by_hand
        return open_by_hand()
    if cmd in COMMANDS:
        sys.argv = ["port.py " + cmd] + argv[1:]
        return importlib.import_module(COMMANDS[cmd]).main()
    # anything else is a vehicle name followed by pipeline steps
    from .cli import main as pipeline
    sys.argv = ["port.py"] + argv
    return pipeline()
