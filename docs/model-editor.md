# Driving the Model Editor

Only used with `--engine editor`. The default pipeline converts and draws icons without the editor.

TF3's Model Editor has no command line, no headless mode and no scripting hook (the exe was checked: it parses no
arguments). Its UI is custom-drawn, so UI Automation cannot see its controls either. What is left is clicking
screen coordinates, and `tf3port/editor.py` does that.

## How it works

One operation is: write the settings file → launch → ☰ → tab → button → wait for the "done" line in the log →
close. **The mod and the prefix are passed through the settings file**, not clicked. Only the tab and the button
are clicked.

| File | Role |
|---|---|
| `tf3port/editor.py` | Rewrites the settings file, launches, clicks, watches the log, closes |
| `tf3port/editor_ui.json` | Button coordinates (relative to the window's client area, 1920x1009, UI scale 1) |
| `port.py calibrate` | Re-measures the coordinates |

The settings file is `%APPDATA%\Transport Fever 3\model_editor_settings_v13.lua` (keep its CRLF line ends).

| Setting | Role |
|---|---|
| `applicationOptions.windowPos` / `windowSize` | Pinned to `{0, 23}` / `{1920, 1009}` |
| `renderOptions.uiAutoScaling` / `uiScaling` | Pinned to `false` / `1` |
| `pathOptions.lastOpenedMod` | The mod opened at startup. **Every bulk operation works on the open mod** |
| `toolsOptions.selectedExportModId` | The Tools tab's Target mod. It has no effect on bulk operations (probably the destination of Copy Loaded Model), but **an index past the end of the list kills the editor at startup**, so it is set to the mod being opened. The index counts staging folders that have a `mod.json`, in name order, from 0 (the `.vscode` folder the editor creates does not count) |
| `toolsOptions.bulkFolder` / `screenshotOptions.bulkPrefixFilter` | The bulk prefix (empty = every model) |

| Button | Tab | Log |
|---|---|---|
| Bulk Convert | Tools | `Starting bulk converting of N models` … `Converting <path>` … `Bulk converting done` |
| Bulk Resave | Tools | Likewise `Resaving` / `Bulk resaving done` |
| Bulk Validation | Tools | Likewise `Validating` / `Bulk validation done` |
| Bulk Generate | Icons (scroll the panel to the bottom) | `Processing vehicle i of N` / `Opening <mod>::/<path>`. **There is no "done" line** |

## Safety checks

- Before converting, a read-only Bulk Validation runs first, and the paths in its log must lie inside the vehicle's
  folder. If not, **the editor is killed** and the run stops.
- If a click misses (no start line within 30 s), it stops with "never started - the click missed". It never
  reports success without the log saying so.
- It refuses to run while a Model Editor is open, and when the client area is not the recorded size.
- A window that starts minimised at 0x0 is restored before it is measured.

## Clicking quirks

- pyautogui's `click()` fits in one frame and is ignored. It hovers, holds the button down for 0.15 s, then
  releases.
- Without focus the first click is swallowed. It taps Alt once, then brings the window to the front.
- The wheel takes 120 per notch (`scroll(-1)` does not move it).

## When the UI changes

A game update that moves the UI breaks the coordinates. The safety checks above stop the run; take new screenshots
and read the coordinates off them.

```
python port.py calibrate --shot menu tab_tools
python port.py calibrate --shot menu tab_icons scroll_panel_end
```

Read the button centres off `logs/calibration/*.png` and correct `tf3port/editor_ui.json`.

- Stopped with "is working on X, which is not in <dir>/": the editor opened a different mod. Check
  `pathOptions.lastOpenedMod`.
- Dies at startup leaving `ComboBox::SetSelected` in the log: `toolsOptions.selectedExportModId` is past the end
  of the list.

## Logs

The Model Editor writes only to standard output (`crash_dump\stdout.txt` is **the game's**; the editor does not
write it). `editor.py` keeps it in `logs/model_editor.log`. To open the editor by hand with a log, use
`port.py editor`. Strip the ANSI colour codes before reading: `sed 's/\x1b\[[0-9;]*m//g'`.

**Some red and yellow warnings on screen never reach the log**: texture format warnings, `Legacy model detected`,
and the cover image error. When investigating by hand, look at both the log and the screen.

## Notes for using it by hand

- Write `installPath` / `userDataPath` under `pathOptions` in the settings file **with forward slashes**.
  Backslashes are read as Lua string escapes (`\u`, `\8` ...) and break.
- Start the Model Editor through `ModelEditor.bat` in the TF3 folder, not the exe (it adds `model_editor\plugins`
  to PATH). `port.py editor` does the same.
- It reads content once at startup. Restart it after changing staging.
- **Tools tab**: `Convert Loaded Model` (the one open model) / `Bulk Convert` (every model matching the prefix).
  Both are the TF2 → TF3 conversion and leave textures alone.
- **Bulk Resave does not convert textures.** The official wiki says it turns `.tga` into `.dds` on save; trying it,
  it only reformats `.mdl` / `.mtl` and leaves the `.tga` files and references as they are.
- **Im-/Export tab**: export settings such as the compression quality of `TGA Textures`.
- `LIT` `GEO` `WIRE` `FLAT` in the top toolbar are render modes. `GEO` is a checkerboard for checking UVs.
