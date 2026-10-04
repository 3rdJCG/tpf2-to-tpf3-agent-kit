"""Port a TF2 vehicle mod to TF3.

One entry point for the whole pipeline, driven by a per-vehicle config in
vehicles/<name>.json (see examples/vehicles/ for the format).

    python port.py <vehicle> all         # everything below, in order

    python port.py <vehicle> build       # TF2 source -> TF3 staging
    python port.py <vehicle> convert     # TF2 -> TF3 models/materials/meshes
    python port.py <vehicle> post        # materials, textures, lights...
    python port.py <vehicle> genicons    # Model Editor: Bulk Generate
    python port.py <vehicle> icons
    python port.py <vehicle> validate check gamecheck

convert is done by tf3port.convert (no Model Editor; it runs the game's own
Lua and matches the editor's Bulk Convert byte for byte on 31 vehicles).
`--engine editor` makes the editor do it instead. That, resave, validate and
genicons drive the Model Editor through tf3port/editor.py (it opens, clicks,
and closes by itself - keep hands off the mouse while it runs). Close any
editor you have open first.

`post` is materials -> textures -> lights -> ..., in that order: textures
picks DXT1 vs DXT5 from what the materials bind, so the types must be settled
first. Every step after `build` is idempotent.

The details behind each step are in docs/; the short version: textures flip
vertically (TGA is bottom-up, DDS top-down), TF3's trains use the _NRML_MAP
material types (plain PHYSICAL / PHYS_TRANSPARENT only where a mesh has no
tangents), base assets are referenced with a `::/` prefix, and lights only
switch with direction if each node carries the shared on/off animations.
"""
import argparse
import sys

from .build import cmd_build
from .check import cmd_check
from .common import Vehicle, require_fresh_build
from .editor_steps import EDITOR_STEPS, run_editor
from .gamecheck import cmd_gamecheck
from .icons import cmd_icons
from .lights import cmd_lights
from .materials import cmd_materials
from .menu import cmd_menu
from .names import cmd_names
from .particles import cmd_particles
from .sounds import cmd_sounds
from .strings import cmd_consists, cmd_strings
from .textures import cmd_textures


STEPS = {
    "build": cmd_build,
    "materials": cmd_materials,
    "textures": cmd_textures,
    "lights": cmd_lights,
    "sounds": cmd_sounds,
    "menu": cmd_menu,
    "particles": cmd_particles,
    "strings": cmd_strings,
    "consists": cmd_consists,
    "names": cmd_names,
    "icons": cmd_icons,
    "check": cmd_check,
    "gamecheck": cmd_gamecheck,
}

POST = ["materials", "textures", "lights", "menu", "particles", "sounds",
        "strings", "consists", "names"]

MACROS = {
    "post": POST,
    # genicons must come after post: the icons are renders of the finished
    # materials and textures
    "all": ["build", "convert"] + POST + ["genicons", "icons", "validate",
                                          "check", "gamecheck"],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("vehicle", help="name of a config in vehicles/ or examples/vehicles/")
    ap.add_argument("steps", nargs="+",
                    help=" | ".join(sorted(MACROS) + sorted(STEPS)
                                    + sorted(EDITOR_STEPS)))
    ap.add_argument("--engine", choices=("native", "editor"), default="native",
                    help="native (default): convert with tf3port.convert and draw "
                         "the icons with tf3port.render - no editor, no mouse. "
                         "editor: click the Model Editor's Bulk Convert and "
                         "Bulk Generate instead")
    args = ap.parse_args()
    editor_steps = EDITOR_STEPS
    if args.engine == "native":
        from .convert.native import cmd_convert
        from .render import cmd_genicons, cmd_icons_native
        STEPS["convert"] = cmd_convert
        STEPS["genicons"] = cmd_genicons
        STEPS["icons"] = cmd_icons_native
        STEPS["validate"] = lambda v: print(
            "validate: skipped - no Model Editor with --engine native; gamecheck "
            "runs the game's own validation (use --engine editor for the editor's)")
        editor_steps = tuple(s for s in EDITOR_STEPS
                             if s not in ("convert", "genicons", "validate"))

    v = Vehicle(args.vehicle)
    steps = []
    for s in args.steps:
        steps += MACROS.get(s, [s])
    for s in steps:
        if s not in STEPS and s not in editor_steps:
            sys.exit("unknown step: %s" % s)

    i = 0
    while i < len(steps):
        s = steps[i]
        if s not in ("build", "check"):
            require_fresh_build(v, s)
        if s in editor_steps:
            # one editor session for a run of adjacent editor steps
            j = i
            while j < len(steps) and steps[j] in editor_steps:
                j += 1
            print("== editor: %s ==" % " ".join(steps[i:j]))
            run_editor(v, steps[i:j])
            i = j
            continue
        print("== %s ==" % s)
        STEPS[s](v)
        i += 1


if __name__ == "__main__":
    main()
