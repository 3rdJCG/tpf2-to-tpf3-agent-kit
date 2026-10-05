# The pipeline

`python port.py <vehicle> <steps...>`. `<vehicle>` is `vehicles/<vehicle>.json` in the workspace (else
`examples/vehicles/`). The code is the `tf3port/` package, one module per step.

## Steps

```
python port.py <vehicle> all       everything below, in order

1. build       TF2 layout -> TF3 staging area (rebuilds this mod's staging folder)
2. convert     TF2 -> TF3 conversion (our own; --engine editor clicks the Model Editor's Bulk Convert)
3. post        materials -> textures -> lights -> menu -> particles -> sounds -> strings -> consists -> names
4. genicons    draws the five icons (--engine editor: the Model Editor's Icons > Bulk Generate)
5. icons       installs the generated icons
6. validate    Model Editor: Tools > Bulk Validation (only with --engine editor; skipped by default, gamecheck does the job)
7. check       our own checks / gamecheck: the game's headless validation
```

| Step | Module | What it does |
|---|---|---|
| `build` | `build.py` | Moves the `res/` layout to `content/<contentDir>/`. Rewrites references, lowercases, splits the config per LOD, makes node names unique, writes out `transf` calls, leaves out unused or empty models, resolves assets from base and other mods, copies in files the mod takes from TF2 itself or a TF2 DLC (`tf2base.py`, needs TF2 installed), writes `mod.json` and the cover image |
| `convert` (default) | `convert/native.py` | The TF2 → TF3 conversion without the Model Editor (no screen or mouse, seconds). Runs the game's Lua with lupa and reproduces what the editor does on top by rule. Byte-identical to the editor's output on 31 vehicles ([roadmap.md](roadmap.md), Phase B) |
| `convert --engine editor` | `editor_steps.py` → `editor.py` | The official conversion (`.mdl`/`.mtl`/`.msh`). A read-only Bulk Validation first proves the editor opened the right mod |
| `materials` | `materials.py` | Settles types and sampler names, decides transparency, `alpha_test` |
| `textures` | `textures.py` | Converts to DDS (DXT1/DXT5/BC5U), flips vertically, mipmaps, powers of two, inverts the green channel of mga and normal maps |
| `lights` | `lights.py` | Maps `*Lights` lists (`lights` in the config), adds tail lights (`tailLights`) |
| `menu` | `menu.py` | Puts vehicles in the purchase menu. Names nameless vehicles `<mod name> <model name>`. Groups the mod's vehicles into one entry (below) |
| `particles` | `particles.py` | `particleId` and `alphaOverLifeTime` |
| `sounds` | `sounds.py` | Ports sound sets, resamples to 48 kHz, `soundReplace` |
| `strings` / `consists` | `strings.py` | `strings.json`, consists as `.mu.lua` |
| `names` | `names.py` | Names in the purchase menu (Japanese and English). `names` in the config and `name_prefix` (below). Runs after `strings`, which rewrites `strings.json` |
| `genicons` (default) | `render/` | Draws the five icons with a numpy renderer straight into `content/<dir>/icons/`. About 10 s per model. `icons` then has nothing to do |
| `genicons` / `icons` (`--engine editor`) | `editor_steps.py` / `icons.py` | The Model Editor's Bulk Generate, and installing its output |
| `validate` | `editor_steps.py` | The Model Editor's Bulk Validation (only with `--engine editor`) |
| `check` | `check.py` | References exist, texture formats, upper case in references |
| `gamecheck` | `gamecheck.py` | `TransportFever3.exe --validate`. Also catches sound and model problems the editor lets through |

### Rules

- **Do not reorder the steps inside `post`.** A texture's format (DXT1/DXT5) depends on what the material binds it
  to, so the types have to be settled first.
- `build` rebuilds staging, which throws away what `convert` did. Always run `convert` after `build`.
- Everything except `build` / `convert` can be rerun safely (idempotent).
- **Do not run `build` on a vehicle that already works in game.** To check the pipeline, copy its config with only
  `modId` changed, compare the two staging folders, and delete the copy's staging folder afterwards.
- **Read the numbers every time.** The type breakdown (`PHYSICAL_NRML_MAP: 15, PHYS_TRANSPARENT_NRML_MAP: 1`), the
  format breakdown (`{'DXT1': 29, 'DXT5': 2, 'BC5U': 0}`), the light counts. `check` only proves references
  resolve, so types or formats that change silently pass it. A number off from what you expect is the sign of
  breakage. Everything transparent, or everything opaque, points at the albedo's alpha.

### The version stamp

`build` writes the pipeline version (`common.PIPELINE_VERSION`) into `_metadata/port.json`, and the later steps
**refuse to run when it does not match**. Bump it when a change moves files or changes reference forms.

This came from a real accident: after textures moved, `post` ran on a staging folder built under the old layout,
and **without an error or a warning** the windows turned opaque and every texture became DXT5.

## The vehicle config

`python port.py new <workshop id> <name> <modId> [contentDir]` writes `vehicles/<name>.json` from the downloaded
TF2 mod's `mod.lua`, and warns about what will need hand work (`*Lights` lights, particles, a non-empty `runFn`).

`vehicles/` lives in your workspace and is never committed to this repository: **it describes other people's mods,
so it stays on your machine.** Examples of the format are in `examples/vehicles/`.

| Key | Required | Meaning |
|---|---|---|
| `modId` | yes | Staging folder name and mod ID |
| `contentDir` | yes | Vehicle folder name under `content/` |
| `workshopId` | yes | TF2 workshop ID. Without `source`, the original is found from this |
| `modName` / `description` / `authors` / `tags` | | Go into `_metadata/modinfo.json`. `authors` names the original authors |
| `source` | | Where the original is (absolute, or relative to the workspace). For mods not from the workshop |
| `lights` | | For vehicles with `*Lights` lists: light mesh name → slot (`front_forward` etc.) |
| `tailLights` | | For coaches whose lamps never light: the meshes to use as tail lights |
| `particles` | | `{"id": "steam"}` for steam engines. `alpha` / `color` override where the fade starts and the colour |
| `soundReplace` | | Sounds the original refers to but does not ship → base sounds |
| `soundSetFallback` | | A base sound set to use in place of one that cannot be ported |
| `invertMgaGreen` | | Invert the mga green channel (default `true`) |
| `menuGroup` | | `false` leaves the purchase menu ungrouped (grouped by default) |
| `menuHead` | | The model to head the grouped entry (when cab or engine is written unusually and the automatic choice lands on an intermediate car) |
| `menuGroups` | | `{"<head>": ["<model>", ...]}` spells out the whole grouping |
| `names` | | Names in the purchase menu: `{"<file name>": {"ja": "...", "en": "..."}}`. The file name is like `loco.mdl` or `train.mu.lua`. Anything not listed keeps its original name |

## Grouping in the purchase menu

### The store screen's rules

How the purchase screen is put together can be read in `base/content/gui.zip`,
`gui/line_vehicle_mgmt/vehicle_store_window.tl`. The essentials:

- Vehicles (`transportVehicle.groupFileName`) and consists (`MultipleUnit.groupFileName`) go into **the same
  table**, keyed by the group name string. Vehicles and consists may share a group.
- A group's **head is the entry whose path equals that string**. Paths are `<modId>::/<folder>/<file>`.
- Entries with a group name (members) are not listed on the left. They appear only when the head's row is opened.
- **A head vehicle that names itself as its group is listed twice** (once as head, once as member).
- **A consist with a group name is never listed on its own.** If a consist is the head, its group name stays empty.
- A head vehicle with empty `filterTags` shows only as the group's heading and cannot be bought itself. This is
  how a display-only model (a picture of the whole train) heads a group. A member with empty `filterTags` is not
  listed.
- A vehicle's group name is a ResName, so a path relative to the file (`"x.mdl"`) resolves. **A consist's group
  name is a plain string** and does not resolve, so write the full name `<modId>::/<folder>/<head>.mu`. **A
  consist's resource name has no `.lua`** (checked in game with `multipleUnitRep.getName`; writing `.mu.lua` matches
  nothing and every consist disappears).

### The `menu` step (vehicles)

By default it groups the mod's vehicles into one entry (`menuGroup: false` stops it).

- **The original author's groups are kept.** With one group, the remaining vehicles join it. With two or more, it
  leaves them alone.
- **The head is the vehicle that should be the entry's face**: one with both a driver's seat (`crew = true`) and an
  engine → a driver's seat → an engine → by name. So that an EMU is not shown by an intermediate car. Display-only
  models ending in `_menu` / `_group` are not made heads. Some mods never mark the driver's seat with `crew`; use
  `menuHead` for those.
- **The head loses its group name** (TF2 authors wrote it on the head too, which lists it twice).
- Display-only models ending in `_menu` / `_group` get empty `filterTags` (so they cannot be bought; as a head they
  become the group's heading).
- What it adds is recorded in `_metadata/menu_groups.json` and chosen again on every run (so its own earlier choice
  is not mistaken for the author's).

### The `consists` step

- **The original author's groups are kept.** In TF2 they pointed at a head consist (`.lua`) or a head model
  (`.mdl`).
  - If at a model that still exists after the port, the consist **joins that model's vehicle group** (or that of
    the model's own head). The consists then list under the display-only model, as the author meant.
  - If at a consist, or at a model that is gone (an empty placeholder that `build` left out), the consists form a
    group of their own. The head is the named consist, else the first. The head consist's group name is empty;
    the members carry the head's full name.
- A mod without groups is grouped into one entry by the same rules as vehicles (`menuGroup: false` stops it).
- Consists in sub-folders may share a file name (liveries). The shallowest keeps the plain name; deeper ones get
  their folder in front. Flattened on the name alone, the later one overwrote the earlier and **one livery's
  consists pointed at the other's cars**.
- `filterTags` is added when missing. Some files indent with spaces (matching only tabs once left consists without
  it, listed nowhere).
- The texts lifted out of consists (non-ASCII names and descriptions) are added to `strings.json` here, because
  `strings` has already run.

## Names

The `names` step replaces every vehicle name (`description.name`) and consist name (`name`) with a translation key
`PORTNAME_<modId>_<file>` and writes Japanese and English text into `strings.json`. The text is `names` from the
config, else the original name. The original names are kept in `_metadata/names.json` on the first run, and reruns
start from there (so its own output is never taken for the original).

- **Prefix**: `"name_prefix": "◆"` in `local_settings.json` puts a mark in front of every name, to tell ported
  vehicles apart in the purchase menu. A personal preference, so it lives in `local_settings.json`, not in the
  vehicle configs.
- A name in only one language is used for the other too (so a raw translation key never shows).
- A naming pattern that works: vehicles "Operator Class-subseries (livery)", consists "Series N cars (train,
  livery)".

## Porting several at once

```
python port.py <vehicle> all > logs/port_<vehicle>.log
python port.py summary <vehicle> ...      only the counts and MISSING / Error lines, per vehicle
```

A few minutes per vehicle. With `--engine editor` they cannot run in parallel (one Model Editor at a time).
