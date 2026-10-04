# From symptom to cause

A quick lookup for when a ported vehicle looks or behaves wrong. The right-hand column names the step in this
repository that deals with it.

## Appearance

| Symptom | Cause | Fix |
|---|---|---|
| Bodywork mirrors the scenery (looks like chrome) | The material type did not resolve, or the green channel of the mga texture was not inverted | `materials` / `textures` |
| Bodywork is see-through | A `PHYS_TRANSPARENT*` type on an opaque part, or `alpha_test cutout` on a DXT1 albedo | `materials` |
| Bodywork turns into a cutout (holes) | Compression noise pushes alpha below 255. Treat a texture with under 0.1 % non-opaque pixels as opaque | `materials` |
| Checkerboard | Material type and sampler names do not match (opaque: `map_albedo`/`albedoTex`; transparent: `map_albedo_opacity`/`albedoOpacityTex`) | `materials` |
| Checkerboard, or two liveries look the same | `.mtl`/`.mdl` files with the same name in different folders overwrote each other when flattened | `build` (keeps the parent folder in the name) |
| Consists are not grouped in the purchase menu; each is listed on its own | The consist's `groupFileName` was dropped (TF3 consists have it too) | `consists` |
| The same vehicle is listed twice in the purchase menu | The head of a group names itself as its group | `menu` (leaves it out of the head) |
| A consist vanished from the purchase menu | A consist with a group name is not listed unless its head is found: the head was named by a short name, or the head consist itself has a group name | `consists` (full names; empty on the head) |
| A consist is listed nowhere | No `filterTags` | `consists` |
| A consist of one livery contains cars of another | Consist files with the same name in sub-folders overwrote each other when flattened | `consists` (adds the folder name) |
| Some parts have the wrong colours, lettering is mirrored | The texture was not flipped vertically (TGA is stored bottom-up, DDS top-down) | `textures` |
| The model is replaced by a worker carrying a crate | A reference does not resolve: `/vehicle/...` where `::/vehicle/...` was meant | `build` |
| Every light is on at both ends, all the time | TF2's `*Lights` lists are dropped by the conversion (`*Parts` lists convert automatically) | `lights` in the config |
| A coach's tail lights never light | The lamps are there but `backwardEndLights` is empty | `tailLights` in the config |
| Tail lights light at the wrong end | A mod that baked positions into its meshes and left the node transforms at zero. Decide by the mesh centre, not the node | `lights` |
| Exhaust is an opaque coloured blob | `particleId` is empty and there is no `alphaOverLifeTime` | `particles` |
| Smoke or steam is yellow or tinted on one side | The author's colour (a non-grey `colorOverLifeTime`), hardly visible with TF2's sprites. `particles` warns about it | `particles.color` in the config |
| A steam engine's smoke looks wrong | `"particles": {"id": "steam"}` maps the emitters to base's `steam_chimney` / `cylinder` | `particles` in the config |
| The driver sits outside the cab | Duplicate node names (`Cube` everywhere): seat references are converted to node names | `build` |
| Blank name or icon in the vehicle list | A `.mdl` that is not a vehicle (e.g. a parts holder) got in, or the name is empty | `build` / `menu` |
| A name shows its translation key | A key defined nowhere. Borrow it from another mod's strings.lua, or make a name from the key | `strings` |
| A consist's name shows `<modId>_mu_<name>_1` | Its text was moved to a key after `strings` had run (only in a single `all`) | `consists` adds it to strings.json |

## Editor and game errors

| Symptom | Cause | Fix |
|---|---|---|
| Lua error, `config` is nil | TF2 shares one `railVehicle.config` across all LODs; TF3 needs one per LOD | `build` |
| Lua error in `checkAndReplaceConfig` | The config refers to a mesh that LOD does not have | `build` |
| Every mesh and material is "not found" | The mod is not in `staging_area`, or the editor was not restarted | |
| `module '<modId>::/scripts/...' not found` | `require "/scripts/..."` copied from a base file. In a mod it is `::/` | `sounds` |
| The editor dies with `attempt to call field 'degToRad'` | The TF2 `.mdl` computes its matrices with `require "transf"` | `build` (writes the matrices out) |
| Bulk Generate dies silently / `requires missing mesh attribute 'tangent'` | A `_NRML_MAP` type on a mesh without tangents | `materials` (to `PHYSICAL` / `PHYS_TRANSPARENT`) |
| Bulk Generate dies with `Vulkan ErrorInitializationFailed` | An empty placeholder model (zero bounding box). Dying at the same model every time tells it apart from running out of GPU memory | `build` (leaves it out) |
| Dies at startup with `ComboBox::SetSelected` | `toolsOptions.selectedExportModId` is past the end of the list | [model-editor.md](model-editor.md) |
| The game dies in `Fixer::Model` | Upper case in `groupFileName` | `consists` |
| The game dies when buying from a script | `compartment2loadConfig` / `autoLoadConfig` missing | [game-testing.md](game-testing.md) |
| A step stops, naming the pipeline version | The staging folder was built by older code. Start again from `build` and `convert` | |

## Validation warnings

| Symptom | Cause | Fix |
|---|---|---|
| `WAV file has sample rate of 44100 Hz` | TF3 requires 48 kHz | `sounds` |
| `Referenced sound set not found` (game log) | The `.snd.lua` did not load. `require "audioutil"` must be `"::/scripts/audioutil.lua"`. Sets built on the old `soundeffectsutil` cannot be ported | `sounds` (replaced by a base set) |
| `0 sound sets` although the wav files were copied | The sets are in `sound_set/<sub-folder>/` | `sounds` |
| `Two transparent materials ... neither sorted nor cutout` | With two or more transparent materials, `alpha_test` is required | `materials` |
| `map_normal has missing texture` (the file exists) | Broken `dwPitchOrLinearSize` / `dwDepth` / `dwRGBBitCount` in the DDS header | `textures` |
| `has format BC3/DXT5, please use BC1/DXT1` (on screen only) | A shipped `.dds` is not in the format its sampler wants | `textures`; `check` reports the rest |
| `non-power-of-2 dimension` | Dimensions are not powers of two. UVs are normalised, so resizing is safe | `textures` |
| `Texture ... is too small` | A tiny texture such as 4x4 | `textures` (scaled up to 64) |
| `keyframes starting after 0` | No keyframe at time 0. Copy the first key to time 0 (shifting the times instead breaks things that switch at the **end** of door closing, such as cabin lights) | `build` |
| `MISSING ... (no stand-in for this sampler)` | Already broken in the original. TF2 silently substituted something | [tf2-tf3-differences.md](tf2-tf3-differences.md#broken-references-in-the-original) |
| `build` reports `textures 0` and glass is opaque | The textures are outside `res/textures/models/` | `build` |
| `Mod size exceeds limit` / `Worst LOD has mesh data of ...` | The original's textures and meshes are large. The port cannot fix that; it only matters for uploading | |

## How to investigate

- **Do not trust the Model Editor's Bulk Validation.** Sound sets that do not load, dangling `groupFileName` or
  `crewModels`, and materials that resolved to the wrong file all load fine in the editor and only show up in game
  or on screen. Run `gamecheck` and the smoke test.
- The game's log, grouped by mod: `python port.py gamelog [<modId>]`
- Some editor warnings **only ever appear on screen** (texture formats, `Legacy model detected`, the cover image).
