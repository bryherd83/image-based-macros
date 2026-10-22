"""Anime Legacy auto farm (Python version).

    F5  = choose what to farm          F6  = start / stop
    F7  = test: what it can see now    F8  = quit
    F9  = test: turn the camera right and back   F10 = hide / show the status box

Play Roblox fullscreen (1920x1080). The macro only acts while Roblox is the active window.
Run it with run.bat (or: .venv\\Scripts\\python.exe farm.py).
"""
from __future__ import annotations

import ctypes
import datetime as dt
import ctypes.wintypes as wt
import math
import queue
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk

import hud
import logsend
import minimap as mm
import winio
from culling import DEFAULT_OFFSET, Culling, next_popup, popup_offset
from dungeon import DungeonRun
from game import Game, load_settings, save_settings
from reconnect import Watchdog
from trial import run_trial
from worldboss import WorldBoss

HOTKEYS = {0x74: "F5", 0x75: "F6", 0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10"}


# ======================= hotkeys (own thread, Windows message loop) =======================
def hotkey_thread(q: queue.Queue):
    user32 = ctypes.windll.user32
    ok = []
    for i, (vk, name) in enumerate(HOTKEYS.items(), start=1):
        if user32.RegisterHotKey(None, i, 0x4000, vk):   # MOD_NOREPEAT
            ok.append(name)
        else:
            q.put(("log", f"couldn't register {name} (another program uses it)"))
    msg = wt.MSG()
    names = list(HOTKEYS.values())
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == 0x0312:                          # WM_HOTKEY
            q.put(("hotkey", names[msg.wParam - 1]))


# ======================= the farm itself (worker thread) =======================
class _WatchEnv:
    """What the reconnect watchdog (reconnect.py) may do, from the farm's worker thread."""

    def __init__(self, farm):
        self.farm = farm

    def log(self, msg):
        self.farm.game.log(msg)

    def status(self, msg):
        self.farm.game.status(msg)

    def toast(self, msg):
        self.farm.app.toast(msg, 8000)          # (also writes it to the log)

    def clip(self, why):
        self.farm.game.clip(why)

    def running(self):
        return self.farm.running

    def roblox_window(self):
        return winio.find_roblox()

    def close_roblox(self, hwnd):
        self.farm.game.release_all()
        winio.close_roblox(hwnd)

    def open_game(self, url):
        winio.open_url(url)

    def activate(self, hwnd):
        winio.activate(hwnd)

    def sleep(self, s):
        end = time.monotonic() + s
        while self.farm.running and time.monotonic() < end:
            time.sleep(0.2)


class Farm:
    def __init__(self, app):
        self.app = app
        self.S = app.S
        self.running = False
        self.thread = None
        self.game = Game(self.S, app.set_info, lambda: not self.running)
        self.dungeon_saved = None          # an interrupted dungeon, resumed within 2 minutes
        self.dungeon_saved_at = 0.0
        self.last_shot = time.monotonic()
        self.last_clean = 0.0
        self.watch = Watchdog(_WatchEnv(self), self.S)
        self.last_watch = self.last_seen_check = 0.0
        self.last_join = None             # wall clock of the last popup joined
        self.popup_shot = 0.0
        self.popup_missed = None          # the due time already reported as missed
        self.last_game_seen = time.monotonic()

    def start(self):
        if self.running:
            return
        if not winio.find_roblox():
            self.app.toast("Can't find Roblox. Open the game first.")
            return
        winio.activate(winio.find_roblox())
        self.running = True
        self.last_game_seen = time.monotonic()
        S = self.S
        self.game.log(f"=== started · farming {S['mode']}"
                      f"{' + trials (leave after wave %d)' % S['trial_leave_after'] if S['join_trials'] else ''} ===")
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()
        self.app.toast("Auto farm ON (F6 to stop)")

    def test_boss_walk(self):
        """F5 button: the world boss walk on its own (teleport to Map 4, walk, stay there)."""
        if self.running:
            self.app.toast("Stop the farm first (F6), then press the test again")
            return
        if not winio.find_roblox():
            self.app.toast("Can't find Roblox. Open the game first.")
            return
        winio.activate(winio.find_roblox())
        self.running = True

        def go():
            g = self.game
            try:
                g.log("=== world boss walk test ===")
                res = WorldBoss(g, Culling(g)).test_walk()
                self.app.toast("World boss test: " + res, 10000)
            except Exception as e:  # noqa: BLE001
                g.log("error: " + "".join(traceback.format_exception(e))[-1500:])
            finally:
                self.running = False
                g.release_all()
        self.thread = threading.Thread(target=go, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.game.release_all()
        self.app.toast("Auto farm OFF")

    def loop(self):
        g = self.game
        culling = Culling(g)
        self.boss = WorldBoss(g, culling)
        try:
            while self.running:
                try:
                    self.tick(g, culling)
                except Exception as e:  # noqa: BLE001 - keep farming, but write it down
                    g.release_all()
                    g.log("error: " + "".join(traceback.format_exception(e))[-1500:])
                    g.clip("the farm hit an error")
                    time.sleep(1.0)
                time.sleep(0.25)
        finally:
            g.release_all()                 # (sprint stays as it is: it is meant to stay on)

    def popup_watch(self, g, mode):
        """Around the time a popup is due (and nothing joined): a screenshot every 10 s, and a
        log line if none was joined within a minute - so a missed popup leaves evidence
        (laptop 10-15: no 23:00 dungeon, nothing in the log to say why)."""
        S = self.S
        kinds = (("dungeon",) if mode != "culling" else ()) + (("trial",) if S["join_trials"] else ())
        if not kinds:
            return
        now = dt.datetime.now()
        off = float(S.get("popup_offset_sec", DEFAULT_OFFSET))
        kind, due = next_popup(kinds, now - dt.timedelta(seconds=75), off)
        since = (now - due).total_seconds()
        if not 0 <= since <= 70:
            return
        if self.last_join and abs((self.last_join - due).total_seconds()) < 60:
            return                              # joined it
        if 15 <= since < 60 and time.monotonic() - self.popup_shot >= 10:   # joins take 1-4 s
            self.popup_shot = time.monotonic()
            g.shot(f"{kind}-popup-due", force=True)
        elif since >= 60 and self.popup_missed != due:
            self.popup_missed = due
            g.log(f"the {kind} popup due at {due:%H:%M:%S} didn't show up (or wasn't recognised)"
                  f" · screenshots '{kind}-popup-due' saved")

    def tick(self, g: Game, culling: Culling):
        S = self.S
        now = time.monotonic()
        g.info["farm"] = f"ON · {S['mode']}" + (" + trials" if S["join_trials"] else "")
        # ---- disconnected / Roblox closed? (only while Roblox is in front, or gone altogether:
        # never takes over while you're using another window)
        if now - self.last_watch > 1.0:
            self.last_watch = now
            if (g.active() or not winio.find_roblox()) and \
                    self.watch.check(now, time.time(), now - self.last_game_seen):
                time.sleep(0.5)
                return
        if not g.active():
            g.release_all()
            g.status("waiting: click on the Roblox window")
            time.sleep(0.5)
            return
        mins = S.get("log_shot_minutes", 5)
        if mins and now - self.last_shot > mins * 60:
            self.last_shot = now
            g.shot(f"every-{mins}min", force=True)
        if now - self.last_clean > 3600:
            self.last_clean = now
            g.logger.cleanup()
        f = g.frame()
        if f is None:
            g.status("can't read the screen")
            time.sleep(0.5)
            return
        g.info["window"] = f"{f.shape[1]}x{f.shape[0]} · capture {g.cap.mode}"
        if now - self.last_seen_check > 2.0:          # the game is on screen (not a disconnect box)
            self.last_seen_check = now
            if g.find("worlds", f) or g.find("roomhud", f) or hud.has_minimap(f):
                self.last_game_seen = now
        if g.close_join_event(f) or g.close_drops(f):
            return
        mode = S["mode"]
        # ---- Dungeon / Trial popup: press its green check
        if mode != "culling" or S["join_trials"]:
            pop = hud.find_popup(f)
            if pop and pop.kind == "trial" and g.find("roomhud", f) and hud.has_minimap(f):
                pop = None          # still in a dungeon: run_dungeon decides (finish it unless stuck)
            if pop and ((pop.kind == "dungeon" and mode != "culling") or (pop.kind == "trial" and S["join_trials"])):
                g.release_all()
                g.click(pop.x, pop.y)
                g.status(f"joining the {pop.kind}")
                g.log(f"joining the {pop.kind}")
                g.shot(f"joining-{pop.kind}", force=True)
                self.last_join = dt.datetime.now()
                # stop setting up Defense: its Play button was still on screen and got pressed
                # while the dungeon loaded, which took you to Defense instead (PC 10-19 15:31)
                culling.joined_popup()
                off = popup_offset(self.last_join)
                if off is not None:                 # learn this PC's clock (see culling.py)
                    # a popup can be joined late (still busy), never early: a lower value counts
                    # at once, a higher one only when two joins in a row agree
                    cur = float(S.get("popup_offset_sec", DEFAULT_OFFSET))
                    cand = getattr(self, "_off_cand", None)
                    if off < cur or (cand is not None and abs(off - cand) <= 5):
                        g.save_setting("popup_offset_sec", off, quiet=True)
                    self._off_cand = off
                time.sleep(1.0)
                return
        self.popup_watch(g, mode)
        # ---- in a dungeon or a trial?
        if (mode != "culling" or S["join_trials"]) and g.find("roomhud", f):
            if g.find("defheart", f) and not hud.has_minimap(f):
                # Defense mode, run by the game's own automation: hands off, only the
                # Dungeon / Trial popups (checked above) are clicked
                g.release_all()
                g.info["run"] = "defense"
                c = g.find("close", f)
                if c:                       # a window left open over the run (e.g. Teleport menu)
                    g.close_menu(*c)
                    return
                wv = hud.read_counter(f, "wave", old_bx=hud.DEFENSE_WAVE_X)
                g.info["wave"] = wv.text if wv else "?"
                leave_at = int(S.get("defense_leave_after", 10))
                now_m = time.monotonic()
                if (mode == "defense" and leave_at > 0 and wv and wv.a >= leave_at
                        and now_m - getattr(self, "_defense_left", -1e9) > 8):
                    c = g.find("leave", f)
                    if c:
                        self._defense_left = now_m
                        g.click(*c)
                        g.log(f"Defense: wave {wv.a} reached · leaving (it starts again from the lobby)")
                        g.status(f"Defense: wave {wv.a} · leaving")
                        culling.last_in_run, culling.last_start, culling.last_nav = now_m, 0, 0
                        time.sleep(2)
                        return
                g.status(f"in Defense (the game plays it) · wave {g.info['wave']} · leaving after wave {leave_at}"
                         " or for the next dungeon / trial popup")
                if time.monotonic() - getattr(self, "_defense_logged", -1e9) > 600:
                    self._defense_logged = time.monotonic()
                    g.log("in Defense mode · leaving it to the game, only joining dungeon / trial popups")
                time.sleep(0.5)
                return
            is_dungeon = hud.has_minimap(f)
            for _ in range(3):                  # the screen can be dimmed for a moment
                if is_dungeon:
                    break
                time.sleep(0.4)
                is_dungeon = g.has_minimap()
            if is_dungeon and mode != "culling":
                self.run_dungeon(g)
                return
            if not is_dungeon and S["join_trials"]:
                g.info["run"] = "trial"
                res = run_trial(g, mode, int(S["trial_leave_after"]))
                self.last_game_seen = time.monotonic()
                g.info["run"] = "-"
                if res == "dungeon" and mode != "culling":
                    self.run_dungeon(g)
                culling.last_in_run, culling.last_start, culling.last_nav = time.monotonic(), 0, 0
                if res == "paused":
                    g.status("trial paused · click on the Roblox window to go on")
                    g.log("trial paused (Roblox wasn't the active window)")
                elif res not in ("stopped", "defense"):
                    g.status("trial finished")
                    g.log("trial finished")
                return
        if self.boss.tick(f):
            return
        if mode == "dungeon":
            culling.waiting_room(f)
            return
        if mode == "defense":
            culling.defense_tick(f)
            return
        culling.tick(f)

    def run_dungeon(self, g: Game):
        resume = None
        if self.dungeon_saved is not None and time.monotonic() - self.dungeon_saved_at < 120:
            resume = self.dungeon_saved
            g.status("dungeon: picking up where it left off")
            g.log("dungeon: picking up where it left off")
        else:
            g.reader.reset()
            g.log("dungeon started")
            g.shot("dungeon-started", force=True)
        g.info["run"] = "dungeon"
        run = DungeonRun(g, resume_from=resume)
        t0 = time.monotonic()
        finished = run.run()
        self.last_game_seen = time.monotonic()
        g.info["run"] = "-"
        todo, done = run.mem.counts()
        mins = (time.monotonic() - t0) / 60
        if finished:
            self.dungeon_saved = None
            if getattr(self, "boss", None):
                self.boss.dungeon_finished()
            try:
                g.log(f"dungeon time: {run.time_summary()}")
                if run.turn_summary():
                    g.log(run.turn_summary())
            except Exception:
                pass
            g.log(f"dungeon finished · {run.rooms_cleared} rooms cleared by the macro in {mins:.1f} min "
                  f"({done} cleared, {todo} left on the map)")
            g.shot("dungeon-finished", force=True)
            g.status("dungeon finished")
        elif run.left_for == "trial":
            # it clicked the Trial popup: wait until the dungeon is gone, then the next tick
            # finds the trial. If the click didn't take, the next tick picks the dungeon up again
            # and trial_check clicks again.
            self.dungeon_saved, self.dungeon_saved_at = run, time.monotonic()
            g.status("leaving the dungeon for the trial")
            t0 = time.monotonic()
            while time.monotonic() - t0 < 20 and self.running and g.has_minimap():
                time.sleep(0.5)
            if not g.has_minimap():
                self.dungeon_saved = None
            g.log(f"left the dungeon for the trial after {mins:.1f} min · {run.rooms_cleared} rooms cleared "
                  f"by the macro ({done} cleared, {todo} left on the map)")
        else:
            self.dungeon_saved, self.dungeon_saved_at = run, time.monotonic()
            g.log(f"dungeon interrupted after {mins:.1f} min · will pick up within 2 minutes")

    # ---------------- tests ----------------
    def test_screen(self):
        g = self.game
        h = winio.find_roblox()
        if not h:
            self.app.toast("Can't find the Roblox window. Open the game first.", 6000)
            return
        winio.activate(h)
        time.sleep(0.4)
        g.window()
        f = g.frame()
        if f is None:
            self.app.toast("Can't read the screen.", 6000)
            return
        H, W = f.shape[:2]
        lines = [f"Roblox window: {W}x{H}" + ("  (good)" if (W, H) == (1920, 1080) else "  (should be 1920x1080 fullscreen)")
                 + f" · capture: {g.cap.mode}"]
        seen = [n for n in ("worlds", "dice", "create", "play", "close", "leave", "spawn", "joinevent", "roomhud")
                if g.tpl.find(f, n)]
        lines.append("sees: " + (", ".join(seen) if seen else "none of the buttons"))
        w = hud.dps_width(f)
        lines.append("DPS meter: " + ("can't read it" if w is None else
                                      "hitting something" if w >= hud.DPS_HIT_WIDTH else "0 (nothing in reach)"))
        pop = hud.find_popup(f)
        lines.append(f"popup: {pop.kind} (check at {pop.x},{pop.y})" if pop else "popup: none")
        if "roomhud" in seen:
            en, wv = hud.read_counter(f, "enemies"), hud.read_counter(f, "wave")
            lines.append(f"enemies: {en.text if en else '?'}   wave/room: {wv.text if wv else '?'}   "
                         f"minimap: {'yes (dungeon)' if hud.has_minimap(f) else 'no (trial)'}")
        t = time.perf_counter()
        v = mm.MapReader().parse(hud.minimap_crop(f))
        ms = (time.perf_counter() - t) * 1000
        if v:
            todo = sum(1 for c in v.cells.values() if c in (mm.TODO, mm.TREASURE))
            a = mm.read_arrow(hud.minimap_crop(f, 20))
            lines.append(f"minimap: {len(v.cells)} rooms ({todo} to do), {len(v.doors) // 2} doors, room size {v.s}px, "
                         f"you're in a {mm.NAMES.get(v.here(), '?')} room · arrow "
                         f"{'-' if a is None else str(round(math.degrees(a))) + ' deg'} · read in {ms:.0f} ms")
        # how fast can it look?
        t = time.perf_counter()
        n = 0
        while time.perf_counter() - t < 0.5:
            g.view()
            n += 1
        lines.append(f"minimap reads per second: {n * 2}")
        msg = "\n".join(lines)
        g.log("F7 test:\n  " + msg.replace("\n", "\n  "))
        self.app.toast(msg, 9000)

    def test_camera(self):
        g = self.game
        h = winio.find_roblox()
        if not h:
            self.app.toast("Open Roblox first")
            return
        winio.activate(h)
        time.sleep(0.3)
        g.window()
        px = round(math.pi / 2 * float(self.S.get("cam_px_per_rad", 584)))
        self.app.toast("Camera test: turning right 90 degrees...", 2000)
        g.cam_drag(px)
        time.sleep(1.2)
        self.app.toast("...and back left", 2000)
        g.cam_drag(-px)
        g.log(f"F9 camera test: dragged {px}px each way")


# ======================= window, status box =======================
class App:
    def __init__(self):
        self.S = load_settings()
        self.root = tk.Tk()
        self.root.withdraw()
        self.q: queue.Queue = queue.Queue()
        self.info = {}
        self.toast_msg = ""
        self.toast_until = 0.0
        self.show_box = True
        self.farm = Farm(self)
        logsend.start(self.S, self.farm.game.logger.dir, status_fn=self._live)   # to the log receiver on another PC, if any
        self._build_box()
        self._build_settings()
        threading.Thread(target=hotkey_thread, args=(self.q,), daemon=True).start()
        self.root.after(100, self._poll)
        self.root.after(300, self._refresh_box)
        self.toast("Anime Legacy auto farm loaded · F7 = test · F6 = start · F8 = quit", 5000)
        self.settings_win.deiconify()

    # ---- status box (bottom-left of the game, click-through) ----
    def _build_box(self):
        b = tk.Toplevel(self.root)
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        b.attributes("-alpha", 0.85)
        b.configure(bg="#101010")
        self.box_text = tk.Label(b, text="", justify="left", anchor="nw", bg="#101010", fg="#f0f0f0",
                                 font=("Consolas", 10), padx=8, pady=6)
        self.box_text.pack(fill="both", expand=True)
        b.update_idletasks()
        try:   # click-through, no taskbar button, never takes focus
            hwnd = ctypes.windll.user32.GetParent(b.winfo_id())
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x08000000)
        except Exception:
            pass
        self.box = b

    def _live(self):
        """What the live status page shows (sent by logsend every few seconds)."""
        i = dict(self.info)
        g = self.farm.game
        status = {"on": bool(self.farm.running), "mode": self.S.get("mode"),
                  "trials": bool(self.S.get("join_trials")), "run": i.get("run", "-"),
                  "doing": i.get("doing", "-"), "enemies": i.get("enemies", "-"),
                  "wave": i.get("wave", "-"), "rooms": i.get("rooms", "-"),
                  "roblox_in_front": bool(g.active()) if hasattr(g, "active") else None,
                  "time": time.strftime("%H:%M:%S")}
        frame = getattr(g, "last_frame", None)
        return status, frame if self.farm.running else None

    def set_info(self, info):
        self.info = dict(info)

    def toast(self, msg, ms=2500):
        self.toast_msg = msg
        self.toast_until = time.monotonic() + ms / 1000
        self.farm.game.log(msg.replace("\n", " | ")) if hasattr(self, "farm") else None

    def _refresh_box(self):
        try:
            if not self.show_box:
                self.box.withdraw()
            else:
                h = winio.find_roblox()
                r = winio.client_rect(h) if h else None
                i = self.info
                lines = [f"farm: {'ON' if self.farm.running else 'off (F6)'} · {self.S['mode']}"
                         f"{' + trials' if self.S['join_trials'] else ''}   run: {i.get('run', '-')}",
                         f"doing: {i.get('doing', '-')}",
                         f"map:   {i.get('map', '-')}",
                         f"enemies: {i.get('enemies', '-')}   wave/room: {i.get('wave', '-')}",
                         f"screen: {i.get('window', '-')}"]
                if time.monotonic() < self.toast_until:
                    lines = self.toast_msg.split("\n") + [""] + lines
                self.box_text.configure(text="\n".join(lines))
                if r:
                    # bottom-right corner: since the game's 10-19 UI update the old spot (left,
                    # 70% down) covered the game's own panels
                    x, y, W, H = r
                    bw, bh = self.box.winfo_reqwidth(), self.box.winfo_reqheight()
                    self.box.geometry(f"+{x + W - bw - 8}+{y + H - bh - 8}")
                else:
                    self.box.geometry("+20+600")
                self.box.deiconify()
        except Exception:
            pass
        self.root.after(300, self._refresh_box)

    # ---- F5 window ----
    def _build_settings(self):
        w = tk.Toplevel(self.root)
        w.title("Anime Legacy farm")
        w.attributes("-topmost", True)
        w.resizable(False, False)
        w.protocol("WM_DELETE_WINDOW", w.withdraw)
        pad = {"padx": 12, "pady": 3, "sticky": "w"}
        ttk.Label(w, text="What should the macro farm?").grid(row=0, column=0, columnspan=3, **pad)
        self.mode_var = tk.StringVar(value=self.S["mode"])
        for r, (val, txt) in enumerate((("culling", "Culling Game"),
                                        ("dungeon", "Dungeons (waits for the Dungeon popup)"),
                                        ("both", "Culling Game, and jump into Dungeons when they pop up"),
                                        ("defense", "Dungeons, and Defense in between (the game plays Defense)")),
                                       start=1):
            ttk.Radiobutton(w, text=txt, value=val, variable=self.mode_var, command=self._picked).grid(
                row=r, column=0, columnspan=3, **pad)
        self.trial_var = tk.BooleanVar(value=self.S["join_trials"])
        ttk.Checkbutton(w, text="Also join Trials when they pop up, and leave after wave", variable=self.trial_var,
                        command=self._picked).grid(row=5, column=0, columnspan=2, **pad)
        self.leave_var = tk.StringVar(value=str(self.S["trial_leave_after"]))
        e = ttk.Entry(w, textvariable=self.leave_var, width=5)
        e.grid(row=5, column=2, padx=4, sticky="w")
        self.leave_var.trace_add("write", lambda *a: self._picked())
        self.mount_var = tk.BooleanVar(value=bool(self.S.get("ride_mount", True)))
        ttk.Checkbutton(w, text="Ride the mount (M) in dungeons",
                        variable=self.mount_var, command=self._picked).grid(row=6, column=0, columnspan=3, **pad)
        self.boss_var = tk.BooleanVar(value=bool(self.S.get("world_boss", False)))
        ttk.Checkbutton(w, text="World boss at the top of every hour (Map 4), then back to Map 5",
                        variable=self.boss_var, command=self._picked).grid(row=7, column=0, columnspan=3, **pad)
        ttk.Button(w, text="Test the walk", command=lambda: (self._picked(), w.withdraw(), self.farm.test_boss_walk())
                   ).grid(row=7, column=3, padx=4, sticky="w")
        ttk.Button(w, text="Start  (F6)", command=lambda: (self._picked(), w.withdraw(), self.farm.start())).grid(
            row=8, column=0, padx=12, pady=10, sticky="w")
        ttk.Label(w, text="F5 = open this window again", foreground="gray").grid(row=8, column=1, columnspan=2,
                                                                               sticky="w")
        self.settings_win = w
        w.withdraw()

    def _picked(self):
        self.S["mode"] = self.mode_var.get()
        self.S["join_trials"] = bool(self.trial_var.get())
        self.S["ride_mount"] = bool(self.mount_var.get())
        self.S["world_boss"] = bool(self.boss_var.get())
        try:
            self.S["trial_leave_after"] = int(self.leave_var.get())
        except ValueError:
            pass
        save_settings(self.S)

    # ---- hotkeys ----
    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.farm.game.log(val)
                elif val == "F5":
                    self.settings_win.deiconify()
                    self.settings_win.lift()
                elif val == "F6":
                    self.farm.stop() if self.farm.running else self.farm.start()
                elif val == "F7":
                    threading.Thread(target=self.farm.test_screen, daemon=True).start()
                elif val == "F8":
                    self.quit()
                    return
                elif val == "F10":
                    self.show_box = not self.show_box
                elif val == "F9":
                    threading.Thread(target=self.farm.test_camera, daemon=True).start()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def quit(self, save=True):
        self.farm.running = False
        self.farm.game.release_all()
        if save:
            save_settings(self.S)
        self.root.after(200, self.root.destroy)

    def mainloop(self):
        self.root.mainloop()


if __name__ == "__main__":
    import sys
    app = App()
    if "--selftest" in sys.argv:          # start, show the windows for a moment, quit (settings untouched)
        app.root.after(1500, lambda: app.quit(save=False))
    app.mainloop()
