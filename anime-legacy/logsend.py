"""Sends this PC's farm log (and problem screenshots) to log_receiver.py on another PC on your
home network, so one PC can look at the logs of all of them. Runs in the background of the
farm, about once a minute. Nothing goes to the internet: it asks the local network once in a
while "is a log receiver there?" (port 9120) and only sends if one answers. If the receiver is
this same PC, or none answers, it sends nothing. Off with "log_send": false in settings.json.
"""
from __future__ import annotations

import glob
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UDP_PORT = 9120
HELLO, REPLY = b"anime-legacy-log?", b"anime-legacy-log-here"
SKIP_SHOTS = ("-every-",)          # the every-5-minute pictures stay on this PC
CHUNK = 500_000


def broadcast_addrs():
    """255.255.255.255 plus x.y.z.255 for each of this PC's home-network addresses (Windows
    sends the first only through one network adapter)."""
    out = ["255.255.255.255"]
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith(("192.168.", "10.")) or ip.startswith(tuple(f"172.{n}." for n in range(16, 32))):
                b = ip.rsplit(".", 1)[0] + ".255"
                if b not in out:
                    out.append(b)
    except OSError:
        pass
    return out


def find_receiver(timeout=1.5, addrs=None):
    """(ip, port, its PC name) of a receiver on the local network, or None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(timeout)
        for a in addrs or broadcast_addrs():
            try:
                s.sendto(HELLO, (a, UDP_PORT))
            except OSError:
                pass
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            data, addr = s.recvfrom(256)
            parts = data.split()
            if len(parts) == 3 and parts[0] == REPLY:
                return addr[0], int(parts[1]), parts[2].decode(errors="replace")
    except OSError:
        return None
    finally:
        s.close()
    return None


class Sender:
    def __init__(self, settings, log_dir, me=None):
        self.S, self.dir = settings, log_dir
        self.me = me or socket.gethostname()
        self.target = None
        self.next_look = 0.0
        self.sent_shots = None

    def _url(self, path, **q):
        ip, port, _ = self.target
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in {"from": self.me, **q}.items())
        return f"http://{ip}:{port}{path}?{qs}"

    def _get(self, path, **q):
        with urllib.request.urlopen(self._url(path, **q), timeout=5) as r:
            return r.read().decode()

    def _post(self, path, data, **q):
        req = urllib.request.Request(self._url(path, **q), data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def once(self):
        """One round: find the receiver if needed, send new log lines and new problem pictures.
        Returns what it did, for the tests."""
        if self.target is None:
            if time.monotonic() < self.next_look:
                return "waiting"
            self.next_look = time.monotonic() + 60
            self.target = find_receiver()
            if self.target is None:
                return "no receiver"
        if self.target[2].lower() == self.me.lower():
            return "receiver is this PC"
        try:
            sent = self._send_log()
            shots = self._send_shots()
        except (OSError, ValueError):
            self.target, self.sent_shots = None, None    # PC off / moved: look again later
            return "lost receiver"
        return f"sent {sent} bytes, {shots} picture(s)"

    def _send_log(self):
        p = os.path.join(self.dir, "log-py.txt")
        if not os.path.exists(p):
            return 0
        local = os.path.getsize(p)
        have = int(self._get("/size") or 0)
        if have > local:                    # this log was renamed and started over
            have = 0
        sent = 0
        with open(p, "rb") as f:
            while have < local:
                f.seek(have)
                data = f.read(min(CHUNK, local - have))
                code, body = self._post("/log", data, at=have)
                if code == 409:             # it has a different amount: go from there
                    have = int(body or 0)
                    if have > local:
                        have = 0
                    continue
                if code != 200:
                    raise OSError(f"receiver said {code}")
                have += len(data)
                sent += len(data)
        return sent

    def _send_shots(self):
        if self.sent_shots is None:
            self.sent_shots = set(self._get("/shots").split())
        cut = time.time() - 24 * 3600
        n = 0
        for p in sorted(glob.glob(os.path.join(self.dir, "*.jpg"))):
            name = os.path.basename(p)
            if name in self.sent_shots or any(s in name for s in SKIP_SHOTS):
                continue
            try:
                if os.path.getmtime(p) < cut or time.time() - os.path.getmtime(p) < 2:
                    continue
                with open(p, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            code, _ = self._post("/shot", data, name=name)
            if code != 200:
                raise OSError(f"receiver said {code}")
            self.sent_shots.add(name)
            n += 1
        return n


    def send_live(self, status, frame=None):
        """The farm's current state (and every so often a small picture of the screen) for the
        receiver's live status page."""
        if self.target is None or self.target[2].lower() == self.me.lower():
            return False
        body = json.dumps(status, default=str).encode()[:20000]
        code, _ = self._post("/status", body)
        if code != 200:
            raise OSError(f"receiver said {code}")
        if frame is not None:
            try:
                import cv2
                h, w = frame.shape[:2]
                small = cv2.resize(frame, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
                ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    self._post("/live", jpg.tobytes())
            except Exception:
                pass
        return True


def start(settings, log_dir, every=15, status_fn=None):
    """Background threads for the farm: the log every `every` s; the live state every 5 s and
    a picture of the screen every 20 s (status_fn() -> (dict, frame or None))."""
    if settings.get("log_send", True) is False:
        return None
    snd = Sender(settings, log_dir)

    def loop():
        time.sleep(20)
        while settings.get("log_send", True) is not False:
            try:
                snd.once()
            except Exception:
                snd.target = None
            time.sleep(every)

    def live():
        last_pic = 0.0
        while settings.get("log_send", True) is not False:
            time.sleep(5)
            try:
                status, frame = status_fn()
                pic = time.monotonic() - last_pic >= 20 and frame is not None
                if snd.send_live(status, frame if pic else None) and pic:
                    last_pic = time.monotonic()
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True, name="logsend").start()
    if status_fn is not None:
        threading.Thread(target=live, daemon=True, name="logsend-live").start()
    return snd

