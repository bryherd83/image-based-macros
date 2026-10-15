"""Windows plumbing: finding the Roblox window, capturing it, sending keys and mouse.

Capture uses DXGI desktop duplication (dxcam): it sees fullscreen games correctly,
so there is no need for the old 'jiggle the mouse so Windows refreshes the
picture' trick. If dxcam fails it falls back to a GDI copy plus that trick.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import random
import time

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

try:  # physical pixels everywhere
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

ROBLOX_EXES = ("robloxplayerbeta.exe", "windows10universal.exe")


# ======================= Window =======================
def _exe_of(hwnd) -> str:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def _title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_roblox():
    found = []
    PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        exe = _exe_of(hwnd)
        if exe == "robloxplayerbeta.exe" or (exe == "windows10universal.exe" and "roblox" in _title(hwnd).lower()):
            r = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            if r.right - r.left >= 100 and r.bottom - r.top >= 100:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(PROC(cb), 0)
    return found[0] if found else None


def client_rect(hwnd):
    """(left, top, width, height) of the client area in screen pixels."""
    r = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def is_foreground(hwnd) -> bool:
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


def activate(hwnd):
    try:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


# ======================= Capture =======================
def _same_picture(a, b) -> bool:
    """Two whole-screen pictures show the same thing (a sparse grid of pixels, so it's quick)."""
    if a is None or b is None or a.shape != b.shape:
        return False
    return float(np.abs(a[::16, ::16].astype(np.int16) - b[::16, ::16]).mean()) < 1.0


class Capture:
    """grab() returns the client area as a BGR numpy array (H, W, 3)."""
    STALE_SEC = 1.5

    def __init__(self, log=print):
        self.log = log
        self.cam = None
        self.cam_rect = None          # (left, top, right, bottom) of the display being captured
        self.cam_key = None
        self.mode = "none"            # none | dxgi | gdi
        self.fails = 0
        self._flip = 1
        self._full = None             # last whole-display picture (DXGI)
        self._full_t = 0.0            # when it arrived
        self._stale = False           # no new DXGI frames for a while: reading via GDI

    def _dx_for(self, x, y) -> bool:
        try:
            import dxcam
            F = dxcam.__dict__.get("__factory") or dxcam.DXFactory()
            for di, outs in enumerate(F.outputs):
                for oi, out in enumerate(outs):
                    out.update_desc()
                    c = out.desc.DesktopCoordinates
                    if c.left <= x < c.right and c.top <= y < c.bottom:
                        key = (di, oi)
                        if self.cam is None or self.cam_key != key:
                            if self.cam is not None:
                                try:
                                    self.cam.release()
                                except Exception:
                                    pass
                            self.cam = dxcam.create(device_idx=di, output_idx=oi, output_color="BGR")
                            self.log(f"capture: DXGI, display {oi + 1}")
                        self.cam_key = key
                        self.cam_rect = (c.left, c.top, c.right, c.bottom)
                        self.mode = "dxgi"
                        return True
        except Exception as e:  # noqa: BLE001
            self.log(f"capture: DXGI not available ({e}); using GDI")
        self.cam, self.cam_rect, self.mode = None, None, "gdi"
        return False

    def grab(self, rect):
        x, y, w, h = rect
        if self.mode != "gdi":
            cr = self.cam_rect
            if self.cam is None or not cr or not (cr[0] <= x < cr[2] and cr[1] <= y < cr[3]):
                self._dx_for(x, y)
                self._full = None
        if self.mode == "dxgi" and self.cam is not None:
            # Always the whole display, cut up here. dxcam only keeps a copy of the last region
            # it was asked for, so asking for the minimap right after the whole screen gave
            # nothing back whenever Roblox hadn't drawn a new frame in between (the dungeon then
            # stopped walking: "can't read the minimap"). No new frame means the screen hasn't
            # changed, so the kept picture is still what's on it.
            try:
                f = self.cam.grab(new_frame_only=True)
                # while reading via GDI, the GDI read's own mouse nudge makes Windows report a
                # "new frame" with the same frozen picture (monitor off): that's not the game
                # drawing again. Going back on it froze a trial on wave 4 for 53 minutes.
                if f is not None and not (self._stale and _same_picture(f, self._full)):
                    self._full, self._full_t = f, time.monotonic()
            except Exception as e:  # noqa: BLE001
                self.log(f"capture: DXGI grab failed ({e}); re-opening")
                self.cam, self._full = None, None
            full = self._full
            # Roblox draws many frames a second. None for STALE_SEC = Windows stopped handing
            # frames over (monitor switched off, a freeze): read the screen the old way (GDI,
            # what the AHK version used, which keeps working with the monitor off) until new
            # frames come again. Never permanent, so a lag spike can't leave it stuck on GDI.
            if full is not None and time.monotonic() - self._full_t > self.STALE_SEC:
                if not self._stale:
                    self._stale = True
                    self.log(f"capture: no new frames for {self.STALE_SEC:.1f}s (monitor off?) · "
                             "reading the screen the old way until they come back")
                g = self._gdi(x, y, w, h)
                if g is not None:
                    return g
            elif self._stale and full is not None:
                self._stale = False
                self.log("capture: new frames again · back to the fast capture")
            if full is not None:
                l, t = x - self.cam_rect[0], y - self.cam_rect[1]
                crop = full[max(0, t):max(0, t + h), max(0, l):max(0, l + w)]
                if crop.size:
                    self.fails = 0
                    return crop.copy()
            self.fails += 1
            if self.fails >= 20:          # DXGI keeps failing: use the GDI copy instead
                self.log("capture: switching to GDI")
                self.mode = "gdi"
            return None
        return self._gdi(x, y, w, h)

    def _gdi(self, x, y, w, h):
        # fullscreen games: Windows keeps an old picture until the mouse moves
        self._flip = -self._flip
        mouse_rel(2 * self._flip, 0)
        time.sleep(0.03)
        hdc_s = user32.GetDC(0)
        hdc_m = gdi32.CreateCompatibleDC(hdc_s)
        bmp = gdi32.CreateCompatibleBitmap(hdc_s, w, h)
        old = gdi32.SelectObject(hdc_m, bmp)
        gdi32.BitBlt(hdc_m, 0, 0, w, h, hdc_s, x, y, 0x00CC0020)

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

        bi = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = (ctypes.c_ubyte * (w * h * 4))()
        gdi32.GetDIBits(hdc_m, bmp, 0, h, buf, ctypes.byref(bi), 0)
        gdi32.SelectObject(hdc_m, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc_m)
        user32.ReleaseDC(0, hdc_s)
        a = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
        return a[..., :3].copy()


# ======================= Input =======================
PUL = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", PUL)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", PUL)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


SCAN = {
    "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20, "space": 0x39, "lctrl": 0x1D, "ctrl": 0x1D,
    "lshift": 0x2A, "shift": 0x2A, "t": 0x14, "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "q": 0x10, "e": 0x12,
    "r": 0x13, "f": 0x21, "g": 0x22, "o": 0x18, "i": 0x17, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05,
    "escape": 0x01, "enter": 0x1C, "tab": 0x0F,
    "left": (0x4B, True), "right": (0x4D, True), "up": (0x48, True), "down": (0x50, True),
}


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def key(name: str, down: bool):
    sc = SCAN[name.lower()]
    ext = False
    if isinstance(sc, tuple):
        sc, ext = sc
    flags = 0x0008 | (0x0002 if not down else 0) | (0x0001 if ext else 0)  # SCANCODE | KEYUP | EXTENDED
    _send(INPUT(1, _U(ki=KEYBDINPUT(0, sc, flags, 0, None))))


def tap(name: str, hold_ms: int = 50):
    key(name, True)
    time.sleep(hold_ms / 1000)
    key(name, False)


def _vk(vk: int, down: bool):
    sc = user32.MapVirtualKeyW(vk, 0)
    _send(INPUT(1, _U(ki=KEYBDINPUT(vk, sc, 0 if down else 0x0002, 0, None))))


def vk_combo(vks, hold_ms: int = 60):
    """Presses a shortcut by virtual-key codes, the way a keyboard does (e.g. NVIDIA's Alt+F10:
    [0x12, 0x79]). For programs listening for shortcuts, not for the game."""
    try:
        for vk in vks:
            _vk(vk, True)
            time.sleep(0.02)
        time.sleep(hold_ms / 1000)
    finally:
        for vk in reversed(vks):
            _vk(vk, False)
            time.sleep(0.02)


def close_roblox(hwnd=None) -> bool:
    """Ends the Roblox player: the process behind `hwnd`, and any other RobloxPlayerBeta.exe."""
    import subprocess
    ok = False
    if hwnd:
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x0001, False, pid.value)          # PROCESS_TERMINATE
        if h:
            ok = bool(kernel32.TerminateProcess(h, 1))
            kernel32.CloseHandle(h)
    r = subprocess.run(["taskkill", "/IM", "RobloxPlayerBeta.exe", "/F"], capture_output=True,
                       creationflags=0x08000000)                      # CREATE_NO_WINDOW
    return ok or r.returncode == 0


def open_url(url: str):
    """Opens a link with its registered program (roblox://... starts Roblox and joins)."""
    import os
    os.startfile(url)


def mouse_rel(dx: int, dy: int):
    _send(INPUT(0, _U(mi=MOUSEINPUT(int(dx), int(dy), 0, 0x0001, 0, None))))


def mouse_button(button: str, down: bool):
    flags = {("left", True): 0x0002, ("left", False): 0x0004,
             ("right", True): 0x0008, ("right", False): 0x0010}[(button, down)]
    _send(INPUT(0, _U(mi=MOUSEINPUT(0, 0, 0, flags, 0, None))))


def wheel(notches: int):
    _send(INPUT(0, _U(mi=MOUSEINPUT(0, 0, ctypes.c_ulong(120 * notches & 0xFFFFFFFF).value, 0x0800, 0, None))))


def cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_to(x: int, y: int):
    """Absolute move sent as real mouse input (Roblox sees it), then pinned to the exact pixel."""
    vl, vt = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = max(2, user32.GetSystemMetrics(78)), max(2, user32.GetSystemMetrics(79))
    nx = round((int(x) - vl) * 65535 / (vw - 1))
    ny = round((int(y) - vt) * 65535 / (vh - 1))
    _send(INPUT(0, _U(mi=MOUSEINPUT(nx, ny, 0, 0x0001 | 0x8000 | 0x4000, 0, None))))
    user32.SetCursorPos(int(x), int(y))


def glide_to(x: int, y: int, steps: int = 6, step_ms: float = 6):
    """Moves in small steps so Roblox notices the mouse arriving (it ignores teleports)."""
    cx, cy = cursor_pos()
    for i in range(1, steps + 1):
        move_to(round(cx + (x - cx) * i / steps), round(cy + (y - cy) * i / steps))
        time.sleep(step_ms / 1000)


def wiggle():
    for _ in range(3):
        mouse_rel(4, 0)
        time.sleep(0.015)
        mouse_rel(-4, 0)
        time.sleep(0.015)


def click_screen(x: int, y: int, park=None):
    """Roblox-proof click: glide onto the button, wiggle, press long enough to be seen."""
    move_to(x - 40, y + 40)
    time.sleep(0.01)
    glide_to(x, y)
    wiggle()
    time.sleep(0.06)
    mouse_button("left", True)
    time.sleep(0.07)
    mouse_button("left", False)
    time.sleep(0.15)
    if park:
        move_to(*park)


def right_drag(px: int, chunk: int = 20, step_ms: float = 8):
    """Turns the camera: hold the right button and move the mouse sideways. Roblox sometimes
    misses a right-button press followed straight away by movement (the camera then doesn't
    turn), so: press, a tiny nudge, a longer pause, then the turn."""
    mouse_button("right", True)
    time.sleep(0.03)
    mouse_rel(1, 0)
    time.sleep(0.03)
    mouse_rel(-1, 0)
    time.sleep(0.07)
    steps = max(1, int(np.ceil(abs(px) / chunk)))
    done = 0
    for i in range(1, steps + 1):
        target = round(px * i / steps)
        mouse_rel(target - done, 0)
        done = target
        time.sleep(step_ms / 1000)
    time.sleep(0.06)
    mouse_button("right", False)
    time.sleep(0.05)


def jitter(a, b):
    return random.uniform(a, b)
