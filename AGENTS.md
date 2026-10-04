# AGENTS.md

A working guide for AI agents. For people, see [README.md](README.md) and [docs/](docs/).
The porting procedure is the Skill ([.claude/skills/tf2-to-tf3-port/SKILL.md](.claude/skills/tf2-to-tf3-port/SKILL.md)).

## This repository

The pipeline `tf3port/` that ports TF2 rail vehicle mods to TF3, and the findings behind it in `docs/`.
The one entry point is `port.py` at the root (every feature is a subcommand; the table is in `tf3port/entry.py`).

**This repository is public** (`tpf2-to-tpf3-agent-kit`). Write everything tracked on the assumption that anyone
reads it. When a finding came from a particular mod, describe it by how the mod was made and what happened ("a
coach mod whose lamps were never lit"), not by its name.

The **workspace** is the folder with the user's own files (`vehicles/`, `logs/`, `local_settings.json`, copies of
originals). It is `TPF3KIT_WORKSPACE`, else the current directory (if it has `local_settings.json` or `vehicles/`),
else this repository (`tf3port/paths.py`). With tool and workspace in separate folders, run
`python <this repository>/port.py ...` from the workspace. The first line of `port.py paths` shows which it is.

```
port.py                entry point; tf3port/entry.py dispatches the subcommands
tf3port/cli.py         the steps and their order (STEPS, POST, MACROS)
tf3port/common.py      the vehicle config (Vehicle), type names, the pipeline version
tf3port/paths.py       finding things, the workspace, local_settings.json
tf3port/convert/       the conversion without the Model Editor (--engine native, Phase B). native = entry,
                       mesh / material / model, luaenv = runs the game's Lua in lupa, luadata = reads and writes
                       data Lua, basegame = reads the user's TF3, vendor/tl.lua = Teal compiler (MIT)
tf3port/render/        icon drawing (Phase B-5). scene = model to triangles, raster = numpy rasterizer,
                       icons = the editor's framing, track and colour adjustment
tf3port/<step>.py      one module per step
tf3port/editor.py      Model Editor GUI automation (--engine editor)
tf3port/game/          the game itself: start (run), smoke test (smoke), drive test (drive), log (log)
tf3port/new_vehicle.py, summary.py   config template, log summary
tf3port/dev/           for working on the converter (reference data, comparisons, editor calibration)
```

## Rules

- **Nothing about other people's mods goes into tracked files.** Real mods' configs live in `vehicles/` (in the
  workspace, untracked). `examples/vehicles/` and examples in the docs are made up.
- **Nothing about one person's machine goes into tracked files.** Steam user folder IDs, user names and paths with
  drive layouts are handled by detection in `tf3port/paths.py` or by `local_settings.json` (untracked). Never in
  code or docs.
- **No game files in this repository.** Base Lua and assets are Urban Games' work. Read them from the user's TF3 at
  run time (`paths.TF3_BASE`). Extracted copies belong in the workspace's `work/`.
- **Never publish or upload a port on your own initiative** (do not touch "make public" on mod.io either).
  Leave that to the user.
- Never modify the originals; everything is written to staging.
- **Do not reorder the steps inside `post`.** Texture formats depend on material types.
- **Do not run `build` on a vehicle that already works in game.** Test on a copy of its config with another
  `modId`, compare the staging folders, delete the copy.
- Bump `common.PIPELINE_VERSION` after a change that moves files or changes reference forms.
- Commands that start the Model Editor or the game use the screen (and the editor the mouse too). Ask the user to
  close a running editor or game first.
- After a port, the standard in-game check is `port.py smoke` (appearance). `port.py drive` takes minutes: offer
  it, run it when asked or when speed, sound or lights are in doubt.

## Checking changes

- **Read the numbers in the output**: the type breakdown, the texture format breakdown, the light counts. `check`
  only proves references resolve.
- For a refactoring, run the code before and after on separate copies of staging and compare the output byte for
  byte (`build` from the original; `post` onward from a copy of finished staging).
- `python port.py <vehicle> gamecheck` is the game's headless validation (10-30 s, no screen).
- After changing the conversion (`tf3port/convert/`), compare with the reference data:
  `python port.py compare-convert mesh` / `material` / `model` (reference in the workspace's `work/golden/`, made
  with `port.py golden`). The bar is every file identical.
- Generated Lua can be syntax-checked with `lupa`.

## Investigating

- What TF3 expects is in base's Lua and the official assets. How to read `base/content/*.zip`:
  [docs/tf2-tf3-differences.md](docs/tf2-tf3-differences.md#reading-base).
- The Model Editor's log is `logs/model_editor.log` (strip the ANSI codes). Some warnings only appear on screen,
  so ask the user for a screenshot too.
- The game's log: `python port.py gamelog`.
- From symptom to cause: [docs/troubleshooting.md](docs/troubleshooting.md).

## Writing

- Comments and docs say **why**. Code added after a real failure keeps the symptom that led to it.
- Steps print counts to standard output, so people and agents notice when something is off.
- Do not add dependencies (Pillow, lupa, numpy, pyautogui, soundcard).
- Docs and comments are in English; README.md has a Japanese section as well.
