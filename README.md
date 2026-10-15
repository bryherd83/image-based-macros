# Image Based Macros

Game macros that **look at the screen and press keys**, like a person would. They don't use
injection, executors, memory reading or modified game files. Each macro takes screenshots,
finds what it needs with image matching (OpenCV), and sends normal keyboard and mouse input
through Windows.

Each folder is its own project with its own README.

## Projects

| Project | Game | What it does | Status |
|---|---|---|---|
| [anime-legacy](anime-legacy/) | Roblox · Anime Legacy | Clears Dungeons (walks every room using the minimap), Trials and the Culling Game. Joins the Dungeon and Trial every half hour, reconnects after a disconnect | ✅ Working |

## How they work

```
 screen ──► capture (DXGI, GDI fallback) ──► find things (template matching, colour masks)
                                                       │
 keyboard / mouse ◄── decide what to do (one small state machine per game mode) ◄─┘
```

- **Capture:** the fast GPU screen capture (DXGI via `dxcam`). If no new frames arrive, as
  happens when the monitor is switched off, it falls back to the old Windows copy method (GDI).
- **Seeing:** template images live in each project's `assets/` folder, cropped from 1920×1080
  screenshots. Positions are scaled for other window sizes.
- **Input:** `SendInput` key and mouse events. The macros only press anything while the game is
  the active window and pause as soon as you click away.
- **Learning:** values that differ per PC (camera turn speed, walking speed, timings) are
  learned while running and saved to a local `settings.json`, which isn't uploaded.
- **Tests:** most logic runs against simulators and saved screenshots, so changes can be
  checked without the game open.

## Requirements

- Windows 10 or 11
- [Python 3.11+](https://www.python.org/downloads/). Tick "Add python.exe to PATH" while installing.
- The game running fullscreen, 1920×1080 recommended

Each project has a `run.bat` that sets everything up the first time you run it.

## Quick start

1. **Download:** green **Code** button → **Download ZIP**, then unzip it. Or clone it:
   `git clone https://github.com/bryherd83/image-based-macros.git`
2. Open the project folder, for example `anime-legacy`.
3. Double-click **`run.bat`**. The first run installs the Python packages it needs.
4. Read that project's README for its hotkeys.

## Repository layout

```
image-based-macros/
├── README.md             ← you are here
├── LICENSE               ← MIT
├── _template/            ← starting point for a new macro
└── anime-legacy/         ← one folder per game
    ├── README.md
    ├── run.bat
    ├── assets/           ← template images
    ├── *.py              ← the macro
    └── test_*.py         ← offline tests and simulators
```

## Adding a new macro

1. Copy `_template/` to a new folder named after the game, such as `my-game/`.
2. Crop the buttons and icons you need from a 1920×1080 screenshot into `assets/`.
3. Fill in the README: hotkeys, what it farms, settings.
4. Add a row to the **Projects** table above.

## Disclaimer

These are personal automation tools. Using macros can be against a game's terms of service, and
**you are responsible for how you use them**. They only read the screen and send normal input;
they never modify or inject into a game. They're provided as-is under the MIT license, with no
warranty.
