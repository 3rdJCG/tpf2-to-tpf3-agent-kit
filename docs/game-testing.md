# Automated tests in the game itself

`TransportFever3.exe` has undocumented command-line options (found by disassembling the exe). With them, much of
what used to mean opening the game and checking by hand runs unattended.

## Starting the game

**Started directly, the exe has steam_api try to relaunch it through Steam, and it exits doing nothing (exit
code 53).** Start it with `SteamAppId=3493540` (and `SteamGameId`) in the environment. `tf3port/game/run.py` does
this, and stops the game as crashed when its log says `Calling HandleCrash` (note that crash reports are sent to
Urban Games automatically).

```
python port.py game [--timeout S] [--log FILE] -- <game arguments...>
```

| Option | What it does | Used by |
|---|---|---|
| `--validate StagingArea,<modId> <out.json>` | Validates a mod without opening a window and writes JSON (10-30 s) | `port.py <vehicle> gamecheck` |
| `--validate-all <source> <json-prefix>` / `--validate-client` | Validation of every mod / for clients | unused |
| `--and-cook <dir>` | Packages the mod for distribution after validating | unused |
| `--script <modId>::/<file.lua>` | Loads a Lua file at startup and calls the `update` (every frame) and `handleEvent` that its `data()` returns. `app` and `api` are available | smoke and drive tests |
| `--settings <file>` | Starts with another settings file | unused |
| `--exec <arg>` | Purpose unknown | |

- `--validate` is **the game's own load check** (model data, sound set references, WAV format, file names, size).
  It also catches the sound problems that the Model Editor's Bulk Validation lets through.
- The `--script` path is a **resource path** (`::/` is base). The script lives in a helper staging mod,
  `zz_port_tools`, created automatically. Without `data()` the game dies.
- With `lupa` installed, the script's Lua can be syntax-checked beforehand.
- `update` runs every frame, so an error repeats every frame. Wrap the body in `pcall`.

## Smoke test: photograph every model

```
python port.py smoke <vehicle...>
python port.py smoke --all
```

It starts a test game with `app.startGame` (the ported mods in `StartGameParams.mods`), places each model in the
world with `cmd.makeCustomEntityCreateCmd`, photographs it with `gui.camera.takeScreenshot`, saves the shots with
the names in `logs/smoke/<run>/`, and quits. The contact sheets `sheet_NN.png` show them all. About 2.5 s per model.

Look for: checkerboards, missing parts, liveries that look alike, blank names in `models.json`. A crash while
loading is a real fault (upper case in `groupFileName` was found this way).

- A bare entity has no colour, so **colour-blend (CBLEND) bodies come out black**. That is not a fault. Giving it a
  colour with `makeEntitySetColorCmd` kills the game.
- The camera can be adjusted with the environment variables `SMOKE_DIST` / `SMOKE_ANGLE` / `SMOKE_PITCH`.

## Drive test: buy, run, sound the horn (optional)

**The standard check stops at the smoke test (appearance).** The drive test takes a few minutes including the
game's startup, so use it when speed, sound or lights are in doubt, or when asked. Buying one in game and running
it checks the same things by hand.

```
python port.py drive <vehicle...> [--rebuild] [--save NAME] [--loco <modId>::/<dir>/<model>.mdl]
python port.py drive --all
```

**No test savegame is needed.** The script builds the test line: in a new game (fixed seed) it finds the flattest
straight north-south strip that stays above water (the longest the map has; 5 km on the default map) and builds
depot → station → high-speed electrified track → station on it, plus a line. The first run saves it as
`tf3port_testline_v<N>`; later runs load that save **with this run's mods** (about 15 s faster than building it).
`--rebuild` builds it again. Bump `TESTLINE_SAVE` in `drive.py` when the layout changes. With `--save`, it uses
your own savegame instead (one with a depot and a line).

It buys one unit per mod, puts it on the line and records the following. The unit is the mod's shortest consist
(`.mu.lua`) if it has any, else its first powered car, else its first car behind a locomotive.

| Check | How |
|---|---|
| Bought | `makeVehicleBuyCmd` succeeds at the depot |
| Top speed | The highest `MOVE_PATH` `dyn.speed`, against the lowest `landVehicle.topSpeed` in the unit. Within 3 %: reached. Levelled off below that for 15 s: **CAPPED** (suspect the conversion of power, weight or top speed). Neither: climbing (the line was only too short) |
| Sound set | `soundConfig.soundSet.name` is loaded |
| Horn | `gui.sound.letVehicleHorn` three times from the cockpit view; the PC's audio output (WASAPI loopback recording) gets louder right after |
| Shots | Following while moving, close up, cockpit view, and from four sides at 23:00 |

Sequence: at 4x speed from the depot to the first station → after departure, back to normal speed for the shots
and the horn → at 4x, measure top speed (until reached, levelled off, or the second station) → night shots.
Results go to `logs/drive/<run>/results.json` and `sheet.png`, one unit per row. About 1.5 minutes per unit (plus
15 s on the run that builds the test line).

What building the test line taught about TF3's API:

- Building is `api.cmd.makeWorldBuildProposalCmd(SimpleProposal, nil, true, true)`. `p.constructionsToAdd[1] = c`
  has no effect (the proposal stays empty, cost 0); **assign the whole table**.
- Money is added the way missions pay rewards (a `JournalEntry` of type INCOME through
  `makeJournalBookAssetCmd`). The starting money runs out on the depot and stations.
- **New track cannot join a construction's frozenNodes** ("cannot build"). The way out is the far node of a frozen
  edge that is not itself in frozenNodes.
- Track is a `SegmentAndEntity` (`type = 1`, `comp.roadType = TRACK`, and `roadTemplate` / `roadStyle` /
  `laneConfigs` from `streetTemplateRep`). Base's `mission/tasks/auto_builder/track_builder.tl` is the example.
- A modular station **needs `params.modules` written out**. Without it the station's updateFn dies on `pairs(nil)`,
  and `getConstructionResult` throws. The content is the slot numbers that the station script's `createTemplateFn`
  uses, each with the `moduleRep` metadata and updateScript.
- A line is `api.type.Line` with `Line.Stop`s (`stationGroup` from `stationGroupSystem.getStationGroup(station)`,
  station 0, terminal 0).
- `makeVehicleSendToDepotCmd` does nothing for a vehicle standing in a depot (the nearest depot is the one it is
  in). To make it run it needs a line.
- To load a savegame with other mods, replace `info.mods` in the result of `app.getSavegameInfo` with a list of
  `Mod.ModId` (`.name`) and pass it to `app.loadGame`. A list of strings is thrown back as the error itself.
- Sending many proposals at once crashed the game. Send them one after another.

Other findings:

- Buying needs `VehiclePart.compartment2loadConfig` (one `api.type.LoadConfig` per compartment) and
  `TransportVehiclePart.autoLoadConfig` (the same number of `true`). Without them the game dies.
- Depots and lines cannot be listed with `forEachEntityWithComponent`. Use
  `api.engine.system.vehicleDepotSystem.forEach` and `lineSystem.getLines()`. Whether a model is powered is
  `metadata.landVehicle.engines`.
- Headlights face along the track and **do not show side-on**. The night shots go round the train.
- For a mod without consists, if the unit picked is an intermediate car, no horn and no lights is the correct
  result. Read the results together with the vehicle type.
- From beside a long consist the horn was not picked up (too far from the leading car). It is sounded from the
  cockpit view.
- Inside the depot neither the shots nor the cockpit view work. The shots are taken after leaving the first
  station.
- The horn verdict: the median RMS from 5 s to 1 s before the first blast against the highest RMS in the 4 s after
  it; above 1.5x is "heard". Recording needs `soundcard` and `numpy`. Do not mute the game.

## When unsure about the API

The API's type definitions are in `<TF3>/api/tealdef/` (`app.d.tl`, `api/*.d.tl`). The UI's source is the `.tl`
files in `base/content/gui.zip`. **Names in the definitions sometimes differ from the real ones** (defined as
`SaveGameId`, actually `api.type.SavegameId`). When unsure, look at how gui.zip uses it.

Known to work:

- Camera: `api.gui.camera.focusPosition`, `setCameraData(Vec5f(x, y, distance, angle, pitch))`, `followEntity`,
  `enterFollowCameraCockpit` / `leaveFollowCameraCockpit`, `takeScreenshot(1)`
- Commands: `makeCustomEntityCreateCmd`, `makeCustomEntityUpdateTransformationCmd`, `makeVehicleBuyCmd`,
  `makeVehicleSetLineCmd`, `makeVehicleSellCmd`, `makeGameSetSpeedCmd`, `makeGameSetTimeOfDayCmd`,
  `makeWorldBuildProposalCmd`, `makeLineCreateCmd`, `makeJournalBookAssetCmd`
- Types: `api.type.SavegameId`, `StartGameParams.new()` (`.mods`, `.seed`), `Mat4f` / `Vec4f` / `Vec3f` / `Vec5f`
