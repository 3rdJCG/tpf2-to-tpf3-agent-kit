---
name: tf2-to-tf3-port
description: Port a Transport Fever 2 vehicle mod to Transport Fever 3 in this repo. Use when the user wants to bring a TF2 vehicle (locomotive, coach, EMU, DMU) over to TF3, add a vehicle config under vehicles/, run or debug the port pipeline (port.py, the tf3port package), run the in-game smoke or drive tests, or diagnose a ported model that renders wrong - missing meshes, mirrored lettering, chrome/see-through bodywork, checkerboard surfaces, lights stuck on, no sound, or Lua errors from the Model Editor.
---

# Porting a TF2 vehicle mod to TF3

The pipeline is the `tf3port` package, run through `port.py` and driven by
a per-vehicle JSON config in `vehicles/` (untracked; format in
`examples/vehicles/` and `docs/pipeline.md`). `docs/` holds the findings; this
file is the procedure.

First run `python port.py paths` - it shows where Steam, TF3, the staging
area and the TF2 workshop were found. Anything missing goes in
`local_settings.json` (untracked).

## Procedure

1. **Write the config.**
   `python port.py new <workshop id> <name> <modId> [contentDir]`
   writes `vehicles/<name>.json` from the mod's `mod.lua` and warns about what
   needs hand work: `*Lights` lists (need `lights`), particle emitters (steam
   engines want `"particles": {"id": "steam"}`), and a non-empty `runFn` (Lua
   that needs a TF3 Teal equivalent - a separate job). Other optional keys:
   `tailLights` (coaches whose lamp meshes are never lit), `soundReplace`
   (sounds the original never shipped), `soundSetFallback`. The source is
   found from `workshopId` in the TF2 workshop folder; `source` overrides it.

2. `python port.py <vehicle> all` - runs every step in order,
   **including the Model Editor**: `tf3port/editor.py` opens it, clicks the
   buttons and closes it. Close any open editor first and keep hands off the
   mouse while it runs (a few minutes).

   The individual steps, if one needs redoing:
   - `build` - TF2 layout to TF3 staging. Wipes staging, so `convert` must follow.
   - `convert` - the TF2 -> TF3 conversion of `.mdl`/`.mtl`/`.msh`/`.ani`,
     done by `tf3port/convert/` (runs the game's own Lua with lupa; output is
     byte-identical to the editor's Bulk Convert on 31 vehicles). No editor,
     no mouse. `--engine editor` clicks the editor's Bulk Convert instead
     (a read-only Bulk Validation first proves it opened the right mod).
     If you change `tf3port/convert/`, rerun `port.py compare-convert
     mesh|material|model` against the golden data (`port.py golden`).
   - `post` - materials, textures, lights, menu, particles, sounds, strings,
     consists. Order matters inside; do not reorder.
   - `genicons` - draws the five icons per model with `tf3port/render/` (numpy,
     no editor; framing, track stage and colour tweak follow the editor's
     settings). `icons` then has nothing to do. With `--engine editor` the
     Model Editor's `Icons` > `Bulk Generate` makes them and `icons` installs
     them. `port.py compare-icons` scores ours against the editor's.
   - `validate` - Model Editor `Bulk Validation`; `check` - our own checks;
     `gamecheck` - the game's headless validator.

   Read the numbers it prints (material types, texture formats, light counts,
   model counts); off-normal numbers are how silent breakage shows up. A
   vehicle where all materials come out transparent (or all solid) deserves a
   look at the albedo alpha before calling it fine.

   Several at once: loop `port.py <v> all > logs/port_<v>.log` in a
   background shell, then `python port.py summary <v> ...` prints the
   counts and every MISSING / Error line per vehicle.

3. **Automated in-game check** (game closed first; no mouse needed). See
   `docs/game-testing.md`.
   - `python port.py smoke <vehicle...>` - the standard check, about
     a minute: photographs every model in a test game. Look at
     `logs/smoke/<run>/sheet_*.png` for checkerboards, missing parts,
     liveries that look alike; `models.json` for blank names. CBLEND bodies
     are black in these shots by design.
   - Optional, only when asked or when speed, sound or lights are in doubt
     (a few minutes per mod; buying one in game by hand covers the same):
     `python port.py drive <vehicle...>` runs each mod's shortest
     consist (else one powered car) on a test line the script builds itself
     (no save to supply; cached after the first run, `--rebuild` to redo) and
     records: bought, max speed against topSpeed (reached / CAPPED /
     climbing - only CAPPED is a fault), sound set loaded, horn audible, plus
     moving / close / cockpit / night shots. Read `logs/drive/<run>/sheet.png`.
     If the unit picked is an intermediate car, no horn and no lights is the
     correct result.

4. Test in game by hand: TF3 > enable the mod > a year inside the vehicle's
   `availability` window > build a depot and buy it. Then
   `python port.py gamelog` - the game's own log grouped by mod.
   **The editor's Bulk Validation passing means little**: missing sound sets,
   dangling groupFileName / crewModels, and materials that resolved to the
   wrong file all load fine in the editor and only show up in game.
   Check: checkerboard bodies, blank names or icons in the vehicle list, the
   driver's seat position, sound, and that every livery looks different.

Everything after `build`/`convert` is idempotent.

**Do not run `build` on a vehicle that already works in game just to test
the pipeline.** Copy its config with a different `modId`, run `all` on that,
compare the two staging folders, then delete the copy's staging folder.

### When the editor automation fails

It clicks fixed coordinates (`tf3port/editor_ui.json`), so a game update that
moves the UI breaks it. It fails loudly ("never started - the click missed"),
never silently. Re-measure with screenshots:

    python port.py calibrate --shot menu tab_tools
    python port.py calibrate --shot menu tab_icons scroll_panel_end

and read the button centres off `logs/calibration/*.png`. If it aborts with
"is working on X, which is not in <dir>/", the editor opened a different mod
than intended and was killed - check `pathOptions.lastOpenedMod`. If the
editor dies at startup with `ComboBox::SetSelected` in the log,
`toolsOptions.selectedExportModId` is past the end of its mod list. Details:
`docs/model-editor.md`.

## Reading errors

The Model Editor writes nothing to `crash_dump\stdout.txt` (that is the game's
log). `tf3port/editor.py` captures `logs/model_editor.log`; by hand, launch
via `port.py editor`. Strip ANSI codes before reading:
`sed 's/\x1b\[[0-9;]*m//g'`.

**Some warnings only ever appear on screen** - texture format complaints,
`Legacy model detected`, the cover-image error. Ask for a screenshot as well as
the log.

To see what TF3 itself expects, read its Lua and official assets - see
"Reading base" in `docs/tf2-tf3-differences.md`.

**Symptom to cause: `docs/troubleshooting.md`.** Look there first.

## Things that are easy to get wrong

- **`::/` references base, `/` references this mod's content root.** Official
  files write `/vehicle/shared/ani/...` and `require "/scripts/..."` because
  they *are* base. Copying that into a mod breaks the whole model. Check an
  example inside your own mod, not a base file.
- **Read the step output, not just `check`.** `check` only proves references
  resolve.
- **Textures flip vertically.** Verified by comparing pixel rows, not by eye.
- **Lowercase every path**, including `groupFileName` (uppercase crashes the game).
- **UI icons are `.tga`**; only model textures must be `.dds`.
- **How a mod was authored matters more than what it is.** A mod using TF2's
  later features (its own `.dds`, `PHYSICAL_*_CBLEND_DIRT` materials, `*Parts`
  light lists) converts almost for free. One using the old forms needs every
  fix-up step. Check the source's materials and `railVehicle.config` first.
- **Liveries repeat file names across folders.** `build` keeps the parent
  folder in names to keep them apart.

## Privacy and licensing

- Never publish or upload a port on your own initiative (do not tick "make
  public" on mod.io either). Leave that to the user.
- Never write real mods' configs, workshop ids or authors into tracked files,
  and never write personal paths (Steam user folder id, user name) into code
  or docs. `vehicles/`, `reference/`, `logs/`, `work/` and
  `local_settings.json` are untracked for this reason.
