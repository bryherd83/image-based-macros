# Anime Legacy auto farm

An image-based macro for the Roblox game **Anime Legacy**. It reads the screen (minimap, HUD
counters, DPS meter, popups) and plays with normal keyboard and mouse input. There's no
executor and no script injection.

## What it does

| Mode | What happens |
|---|---|
| **Dungeons** | Joins the Dungeon popup (every half hour at :01:40 and :31:40). Reads the minimap to know which rooms are cleared, turns the camera to face each door, walks room to room, waits for the enemies to die, and keeps going until every room is cleared. About 8–9 minutes for 50 rooms. |
| **Trials** | Joins the Trial popup (at :16:40 and :46:40). Presses Spawn, walks straight into each room until the DPS meter shows it's hitting, and moves on when the wave is cleared. Leaves after a chosen wave. About 3.5 minutes to wave 24. |
| **Culling Game** | Waits in the lobby, joins, and leaves at a chosen wave. |

**Dungeon + Trial together:** a dungeon that's still clearing rooms is finished first. If it's
stuck (no new room for 2 minutes) when the Trial pops up, it leaves for the Trial.

### Reliability features
- **Learns your PC:** camera turn speed, walking and sprint speed, and how far to walk into
  trial rooms are learned and saved to `settings.json`.
- **Stuck recovery:** re-checks the camera direction, nudges around obstacles, and presses
  Spawn if a room takes too long.
- **Auto-reconnect:** reads Roblox's own log. After a real disconnect or a crash it warns you
  for 30 s, then closes Roblox and opens Anime Legacy again. Normal teleports never trigger it.
  At most 6 times an hour.
- **Sprint always on:** checks your walking speed on the minimap and presses sprint if it's off.
- **Monitor off:** keeps working with the monitor switched off, using a slower screen-copy
  fallback.
- **Trait-roll screens:** waits through the black full-screen "MYTHICAL TRAIT" animation
  instead of thinking the run ended.
- **Instant Replay clips (optional):** if NVIDIA Instant Replay is on, it saves a clip (Alt+F10)
  when something goes wrong.
- **Log:** `Pictures\Screenshots\anime-legacy-log\log-py.txt`, plus screenshots of anything
  unusual. Screenshots older than 24 h are deleted.

## Setup

1. Install [Python 3.11+](https://www.python.org/downloads/). Tick **"Add python.exe to PATH"**.
2. Run Roblox **fullscreen at 1920×1080**.
3. Double-click **`run.bat`**. The first run creates a `.venv` folder and installs `numpy`,
   `opencv-python`, `dxcam` and `comtypes`.
4. Click into Roblox and press **F6**.

## Hotkeys

| Key | Does |
|---|---|
| **F5** | Choose what to farm (Dungeons / Culling Game / both, join Trials, leave-after wave) |
| **F6** | Start / stop |
| **F7** | Test: shows what it can see right now (minimap, counters, buttons) |
| **F8** | Quit |
| **F9** | Test: turns the camera right and back (checks the camera drag works) |
| **F10** | Hide / show the status box |

The macro only acts while Roblox is the active window. Click another window and it pauses;
click back into Roblox and it carries on. It needs the mouse and keyboard while it runs.

## Settings

`settings.json` is created on the first run. Most of it is learned automatically. The ones
you may want to change:

| Setting | Default | Meaning |
|---|---|---|
| `mode` | `dungeon` | `dungeon`, `culling` or `both` |
| `join_trials` | `true` | Join the Trial popup |
| `trial_leave_after` | `21` | Leave the trial after this wave |
| `skill_key` | `""` | A key to press every 1.5 s during runs, such as `"z"` |
| `sprint_key` | `lctrl` | The game's sprint toggle |
| `dungeon_leave_for_trial_sec` | `120` | Leave a stuck dungeon for the Trial after this long without a new room |
| `auto_reconnect` | `true` | Reopen the game after a disconnect or crash |
| `clips` | `true` | Save NVIDIA Instant Replay clips when something goes wrong |

## Files

| File | What's in it |
|---|---|
| `farm.py` | Hotkeys, status box, main loop, what to do when |
| `game.py` | Game actions (click, Spawn, popups) and default settings |
| `winio.py` | Screen capture (DXGI and GDI), keyboard and mouse input, window handling |
| `hud.py` / `minimap.py` | Reading the counters, DPS meter, popups and the minimap |
| `dungeon.py` | Dungeon navigation |
| `trial.py` | Trial rooms |
| `culling.py` | Culling Game and the popup schedule |
| `reconnect.py` | Disconnect detection and rejoin |
| `sim.py`, `sweep.py`, `test_*.py` | Simulators and offline tests |

## Tests

```bat
.venv\Scripts\python.exe sweep.py            :: 96 simulated dungeons
.venv\Scripts\python.exe test_trial.py       :: trial simulator
.venv\Scripts\python.exe test_sprint.py
.venv\Scripts\python.exe test_reconnect.py
.venv\Scripts\python.exe test_capture.py
.venv\Scripts\python.exe test_schedule.py
.venv\Scripts\python.exe farm.py --selftest
```

`test_replay.py` and `test_offline.py` need saved screenshots in `testdata/screens/`. These
aren't uploaded.

## Troubleshooting

- **"can't read the minimap" or nothing happens:** the game must be fullscreen 1920×1080. Press
  F7 to see what it detects.
- **Camera doesn't turn:** press F9. If the camera doesn't move, check that nothing else is
  holding the right mouse button.
- **Close the AutoHotkey version first.** Both use the same F-keys.
- Anything else: check `log-py.txt` in `Pictures\Screenshots\anime-legacy-log\`.
