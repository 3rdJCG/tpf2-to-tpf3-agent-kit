# Differences between TF2 and TF3

What you run into when bringing a TF2 vehicle mod to TF3, as far as actual ports have confirmed it. The arrow
after each item names the step in this repository that takes care of it.

## Things that break the look

### Textures flip vertically

TGA has its origin at the bottom left (OpenGL), DDS at the top left (DirectX). The UVs stay as they were in TF2,
so unless the image is flipped during conversion, the model samples the wrong rows of the texture. The symptoms
are "parts of the body have the wrong colour" and "numbers and lettering are mirrored". Confirmed by comparing pixel
rows, not by eye.
→ `textures`

### Material types

TF3's **train** `.mtl` files (429 in base) use the normal-mapped types.

| Use | Type | Parameter / sampler | Texture format |
|---|---|---|---|
| Opaque surfaces | `PHYSICAL_NRML_MAP` | `map_albedo` / `albedoTex` | DXT1 |
| Glass etc. | `PHYS_TRANSPARENT_NRML_MAP` | `map_albedo_opacity` / `albedoOpacityTex` | DXT5 |
| Lamps | `EMISSIVE` | | |

- A type that does not resolve falls back to the default material, which **turns metallic and mirrors the
  scenery**.
- Each type accepts different sampler names. A mismatch gives a **checkerboard**.
- The normal-mapped types **require tangents**. On a mesh without them the editor dies silently. Such meshes take
  `PHYSICAL` / `PHYS_TRANSPARENT` without a normal map (base uses them too).
- TF2 authors often used `PHYS_TRANSPARENT` on opaque bodywork. Carried over by type name, the body turns
  translucent. Decide by **whether the albedo actually uses its alpha** (on one locomotive, 1 texture of 31 did:
  the windows). Opaque ones also lose `alpha_test`.
- BC compression noise drops some pixels' alpha below 255 (about 0.008 % on a body texture). "Transparent if any
  pixel is under 255" turns the body into a cutout, so the threshold is 0.1 %.
- When the albedo becomes DXT1, DXT1's 1-bit alpha lets the encoder make pixels transparent. A leftover
  `alpha_test cutout` punches holes there.
- With two or more transparent materials, each needs `alpha_test` set to `cutout` or `sorted`.

→ `materials`

### The green channel of mga

TF2 reads it as gloss (0 = rough), TF3 as roughness (0 = smooth). Not inverted, every surface turns into a mirror.
`isLegacyMaterial = true` does not take care of it. (Decided before the vertical flip was in place, so worth
checking again. `invertMgaGreen` in the config turns it off.)
→ `textures`

### Normal maps

BC5U (ATI2N), and **with the vertical flip the green channel is inverted too** (otherwise the bumps point the
wrong way; a different reason from the mga inversion). If the original has none, do not make one: refer to
`::/assets/shared/mat/tex/default_normal_map.dds`.
→ `textures`

### Base is referenced with `::/`

A path starting with `/` means **this mod's content root**. Base files are written like
`::/vehicle/shared/ani/front_forward_parts_on.ani`.

Official files write `/vehicle/shared/ani/...` and `require "/scripts/soundsetutil.lua"`, but that works **because
they are base's own files**. Copied into a mod, they look for `<modId>::/vehicle/...` and fail. This trap was hit
three times: shared animations, shared emissive materials and soundsetutil. The symptoms are the whole model
failing to load (the placeholder worker carrying a crate) or Lua's `module not found`. The `soundConfig.soundSet.name`
and `transformatorConfig` that the converter writes use `::/`, so when unsure, look at an example inside your own
mod.

## Lights

**TF2 had two ways to write lights, and the converter treats them differently.**

| In TF2 | Converter | What to do |
|---|---|---|
| `frontForwardParts` etc. (`*Parts`) filled in | **Converted** to animations | Nothing |
| Only `forwardLights` etc. (`*Lights`) | **Dropped** | Map them by hand in `lights` in the config |

`base/metadataanimationutil.lua` only handles `*Parts`. A vehicle with only `*Lights` left alone has **every light
on all the time** (both ends, whatever the direction). Check the original `.mdl` for which one it is first
(`port.py new` counts them and warns).

In TF3 each node gets a shared animation that switches it on and off.

```lua
animations = {
    front_forward_parts_off = { params = { id = "::/vehicle/shared/ani/front_forward_parts_off.ani" }, type = "FILE_REF" },
    front_forward_parts_on  = { params = { id = "::/vehicle/shared/ani/front_forward_parts_on.ani" },  type = "FILE_REF" },
},
```

The key is the full name including `_parts`. `front`/`back` is which end of the vehicle, `forward`/`backward` the
direction of travel.

| Mesh | Slot | Lit when |
|---|---|---|
| White, front end | `front_forward` | moving forward |
| White, rear end | `back_backward` | moving backward |
| Red, front end | `front_backward` | moving backward |
| Red, rear end | `back_forward` | moving forward |

The shared animations in `vehicle/shared/ani/` are `front_forward` / `front_backward` / `back_forward` /
`back_backward` / `inner_forward` / `inner_backward`, each `_parts_on` / `_parts_off`, plus `blink_lights_*`,
`brake_lights_*`, `beacon_lights`, `strobe_lights` and others.
→ `lights`

### Adding tail lights the original lacks

Coach mods that model the lamp meshes but leave `backwardEndLights` empty are common. Adding a node **beside** the
lamp mesh with a shared emissive material from base, and giving it a direction animation, makes it light up.

```lua
materials = { "::/vehicle/train/emissive/train_red_lights.mtl", },   -- red (tail light)
materials = { "::/vehicle/train/emissive/train_all_lights.mtl", },   -- white (headlight)
```

Write the mesh names in `tailLights` in the config. When it lights depends on the sign of the lamp's position (the
x of the mesh centre, moved by the node transform). **A lamp at the front end is at the tail when moving backward**,
so it is `front_backward`; at the rear end, `back_forward`. Some mods bake positions into the meshes and leave the
node transform at zero, so it looks at the mesh centre, not the node position.
→ `lights`

## Other differences

| Item | TF2 | TF3 | Handled by |
|---|---|---|---|
| Meshes `.msh`/`.blob` | | **Read as they are** (the converter rewrites them) | `convert` |
| Mod info | `mod.lua` | `mod.json` + `_metadata/modinfo.json` | `build` |
| Path resolution | Relative to `res/models/{mesh,material}/` respectively | Relative to **the `.mdl`'s own folder**. Base is `::/` | `build` |
| File names | Upper case allowed | Lower case recommended (validation warns). `.grp` is **rejected** | `build` |
| Cover image | `image_00.tga` at the root | `image_00.tga` for the gallery, **`_metadata/0.png`** (1280x720) for upload | `build` |
| UI icons | `res/textures/ui/...` | Five `.tga` in `<vehicle>/icons/` (`_icon20@2x`, `_icon_small@2x`, a `_cblend` of each, `_store`) | `genicons` → `icons` |
| Textures | `.tga` | `.dds` required. Warns when not a power of two. Rejects tiny ones (4x4 etc.) | `textures` |
| `.mdl` | `version = 1` | `version = 2` | `convert` |
| `railVehicle.configs` | One may serve every LOD | **One per LOD**, referring only to nodes and meshes that LOD has | `build` |
| Node names | Duplicates allowed (`Cube` everywhere) | Seats and axles refer to nodes **by name**, so duplicates seat the driver outside | `build` |
| Animations | `res/models/animation/<sub>/*.ani` | `<vehicle>/ani/*.ani`. **Format and names carry over** (doors etc.) | `build` |
| Animation times | Need not start at 0 | **A keyframe at time 0 is required** | `build` |
| Sound sets | `res/config/sound_set/<name>.lua` | `<vehicle>/sound/<name>.snd.lua`, referred to as `.snd` | `sounds` |
| WAV | 44.1 kHz works | **48000 Hz required** | `sounds` |
| Particles | Only a `color` on the emitter | Needs `particleId` and `alphaOverLifeTime` | `particles` |
| Consists | `res/config/multiple_unit/<name>.lua` | `<vehicle>/<name>.mu.lua`. Needs `filterTags`. **Keep** `groupFileName` (it groups consists in the purchase menu). A vehicle's `groupFileName` must be **lower case** (upper case crashes the game) | `consists` / `menu` |
| Translations | `strings.lua` (a Lua table) | **`strings.json` at the mod root** | `strings` |
| Strings | Non-ASCII text allowed | The editor **strips non-ASCII characters**. Names become translation keys, the text goes to `strings.json` | `strings` |
| Other mods' assets | Could be referenced directly | Do not resolve | `build` copies them in from the workshop |
| Empty `.mdl` | Used as a consist's display model | Not needed. Bulk Generate **crashes** on it | `build` leaves it out |
| `transf` functions | `require "transf"` worked inside a `.mdl` | Does not (the editor dies) | `build` writes out the matrices |

## Sound sets

The `soundsetutil` API changed.

| | TF2 | TF3 |
|---|---|---|
| `require` | `"soundsetutil"` | **`"::/scripts/soundsetutil.lua"`** |
| Last argument of `addTrackParam01` | `"speed01"` | `{"vehicle", "speed01"}` |
| `axleRefWeight` in `addEventClacks` | `10.0` | `10.0 * 1000.0` |

The factor of 1000 is because **weights went from tonnes to kg** (like `weight = 84` → `weightEmpty = 84000`).
Shared sounds map from `vehicle/<rest>` to `::/vehicle/train/shared/sound/<rest>`. `audioutil` is likewise
`"::/scripts/audioutil.lua"`.

Sets written with TF2's old `soundeffectsutil` have no matching API in TF3, so they are replaced by a base set for
the engine type (`soundSetFallback` in the config overrides it). Some mods keep their sets in
`sound_set/<sub-folder>/`.

## Texture formats

TF2 mods that ship their own `.dds` often do not match **the format each sampler wants**. The editor names them on
screen, but **neither the log nor the validation report mentions them**. `check` finds them as
`texture format mismatches`.

| Sampler | Wants |
|---|---|
| `albedoTex` (`map_albedo`) | DXT1 / BC1 |
| `albedoOpacityTex` (`map_albedo_opacity`) | DXT5 / BC3 |
| `metalGlossAoTex` | DXT1 / BC1 |
| `normalTex` | **BC5U / ATI2N** |

A DX10 header with `dxgiFormat = 83` already holds BC5 data, so rewriting the header is enough (lossless).

**A broken DDS header is reported as "missing texture".** Reusing the header from Pillow's output leaves
`dwPitchOrLinearSize` / `dwDepth` / `dwRGBBitCount` broken, and TF3 calls a texture it cannot read "missing".
Comparing with a base texture shows it (linearSize is the compressed size in bytes, depth is 1, bitCount is 0).

## Particles (exhaust and steam)

TF2's emitters held little more than a colour and a rate; the sprite was fixed by the engine. TF3 names it with
`particleId` and fades it with `alphaOverLifeTime`. The converter leaves `particleId = ""` and adds no fade, so out
comes **an opaque coloured blob** (in one case the author's purplish colour became a purple blob). Official diesels
use `particleId = "diesel_exhaust"`, a grey colour (0.39-0.47), and `alphaOverLifeTime` from 0.3 to 0. Steam engines
use base's `steam_chimney` (chimney) and `cylinder` (cylinders), told apart by height.

## Broken references in the original

TF2 silently substitutes textures and sounds that do not exist, so some mods carry **references that were already
broken in the original**. TF3's validation reports them as errors.

| What is missing | What happens |
|---|---|
| Materials no model uses | `build` drops them |
| TF2 game assets (`terrain/coal_albedo.dds`, `vehicle/train/emissive/train_all_lights.mtl` ...) | `build` looks for the same name and path in TF3's own zips and points at it with `::/` (placeholders excluded) |
| A TF2 base or DLC vehicle's meshes, materials and textures (a mod that only rewrites that vehicle's `.mdl`) | `build` copies them in from your TF2 install (`tf2base.py`). Pointing at TF3's version does not work: TF3 remodelled such vehicles, with other mesh names and material groups, and the game rejects the model |
| Emissive texture (`map_emissive`) | `build` generates a white one (64x64). The colour comes from `emissiveScale` |
| Normal map (`map_normal`) | Base's `default_normal_map.dds` |
| Albedo, mga | No stand-in, shown as `MISSING`. Look for them in the author's other mods |
| Sounds | `"soundReplace": { "<TF2 reference>": "::/<TF3 reference>" }` in the config |

Some mods keep textures outside `res/textures/models/` (`res/textures/<folder>/`). `build` picks them up from all
of `res/textures/` except `ui/`.

## How a mod was made matters more

**How a mod was authored matters more than what kind of vehicle it is.**

- **Mods using TF2's later features** (their own `.dds`, `PHYSICAL_*_CBLEND_DIRT` types, `*Parts` lights) convert
  almost as they are. Their `.dds` formats often do not match what the samplers want, though.
- **Mods written the old way** need every fix-up step. Look at the original's materials and `railVehicle.config`
  first.
- **Mods with liveries collide on names.** Textures, materials, animations and models with the same name sit in
  different folders. Flattened, they overwrite each other: "two liveries look the same", "checkerboard". `build`
  keeps one level of parent folder, and records the model name mapping in `_metadata/model_names.json`.
- **Some mods refer to TF2's shared textures** (dirt, rust). They map to `::/vehicle/shared/mat/tex/dirt_albedo.dds`
  and the like.
- **Some refer to other mods' assets** (in a series of EMU mods, the destination-sign textures of a sibling mod).
- **EMU and DMU mods sometimes have Lua in `runFn` in `mod.lua`.** TF3 uses Teal (`.tl`), so a non-empty `runFn`
  is a separate job. Read it before starting.
- Large textures or meshes in the original trigger TF3's size limit (500 MB) or the warning about the most distant
  LOD's weight. Fixing that means remaking the assets; the port cannot.

## Reading base

`base/content/*.zip` files start with **`UG\x03\x04`** instead of `PK` (Urban Games' own signature). Only the
first local header carries it, so patching those two bytes to `PK` (as `tf3port/convert/basegame.py` does) makes
them ordinary zips. .NET's `System.IO.Compression.ZipFile` reads them as they are.

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
$a = [System.IO.Compression.ZipFile]::OpenRead($zip)
```

The Lua inside (`base/model_metadata_util.lua`, `base/metadataanimationutil.lua` ...) shows what TF3 expects of TF2
data. The official vehicles' `.mtl` files are worked examples too (`base/content/vehicle/train/alco_hh600.zip`
etc.). The API's type definitions are in `<TF3>/api/tealdef/`, the UI's source in the `.tl` files of
`base/content/gui.zip`. Base files are Urban Games' work: read them from your own TF3 install, do not copy them into
this repository.
