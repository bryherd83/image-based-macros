"""Offline check of winio.Capture's DXGI path with a fake dxcam camera: grabbing one region right
after another must not come back empty when the screen hasn't changed (that made the dungeon
stop and say "can't read the minimap"). Nothing here touches the screen or the game.

    python test_capture.py
"""
import numpy as np

import winio


class FakeCam:
    """Stands in for dxcam: hands out queued frames, None = no new frame since the last grab."""

    def __init__(self):
        self.frames = []
        self.calls = []

    def grab(self, region=None, copy=True, new_frame_only=True):
        self.calls.append((region, new_frame_only))
        return self.frames.pop(0) if self.frames else None


def capture(frames=()):
    cap = winio.Capture(log=lambda m: None)
    cap.mode, cap.cam, cap.cam_rect = "dxgi", FakeCam(), (0, 0, 1920, 1080)
    cap.cam.frames = list(frames)
    cap._gdi = lambda *a: (_ for _ in ()).throw(AssertionError("GDI fallback used"))
    return cap


if __name__ == "__main__":
    rng = np.random.default_rng(1)
    full = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    MAP = (1678, 67, 190, 190)

    cap = capture([full])
    a = cap.grab((0, 0, 1920, 1080))
    b = cap.grab(MAP)                     # no new frame since: comes from the kept picture
    assert a is not None and b is not None, "a grab came back empty"
    assert (a == full).all() and (b == full[67:257, 1678:1868]).all(), "wrong pixels"
    for _ in range(50):                   # and keeps doing so, whatever the region
        assert cap.grab(MAP) is not None and cap.grab((1753, 142, 40, 40)) is not None
    assert all(r is None and nfo for r, nfo in cap.cam.calls), "should always ask for the whole display"

    b[:] = 0                              # callers get their own copy
    assert (cap.grab(MAP) == full[67:257, 1678:1868]).all(), "caller changed the kept picture"

    cap.cam.frames = [np.full_like(full, 7)]
    assert (cap.grab((10, 10, 5, 5)) == 7).all(), "a newer frame should replace the kept one"

    edge = cap.grab((1900, 1070, 50, 50))     # partly off the display: clipped, not empty
    assert edge is not None and edge.shape == (10, 20, 3), edge.shape

    cap2 = capture()                      # nothing captured yet: None, and no GDI switch
    assert cap2.grab(MAP) is None and cap2.mode == "dxgi"

    # no new frames for over 1.5 s (monitor switched off?): reads the screen via GDI meanwhile,
    # back to DXGI as soon as a new frame comes, and never switches for good
    logs = []
    cap3 = capture([full])
    cap3.log = logs.append
    cap3.grab(MAP)
    gdi_calls = []
    cap3._gdi = lambda x, y, w, h: gdi_calls.append((x, y, w, h)) or np.zeros((h, w, 3), np.uint8)
    cap3._full_t -= 2.0
    g = cap3.grab(MAP)
    assert gdi_calls == [MAP] and g.shape == (190, 190, 3) and (g == 0).all(), "stale DXGI should read via GDI"
    assert any("monitor off" in m for m in logs)
    cap3.cam.frames = [full.copy()]        # a "new frame" with the same frozen picture (the
    g2 = cap3.grab(MAP)                    # GDI nudge moved the mouse): stays on GDI
    assert len(gdi_calls) == 2 and (g2 == 0).all() and cap3._stale, "same picture must not end GDI"
    live = full.copy()
    live[::2] = 255 - live[::2]            # the game really drawing again
    cap3.cam.frames = [live]
    b = cap3.grab(MAP)
    assert len(gdi_calls) == 2 and (b == live[67:257, 1678:1868]).all() and cap3.mode == "dxgi"
    assert any("back to the fast capture" in m for m in logs)
    print("capture: ok (no empty grabs when the screen hasn't changed; copies; clipping; "
          "falls back to GDI while no new frames come, e.g. monitor off)")
