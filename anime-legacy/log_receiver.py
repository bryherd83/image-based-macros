"""Collects the farm logs of your other PCs (e.g. a laptop) on this PC, over your home network.

Run on the PC that should collect them (it keeps running in the background):
    .venv\\Scripts\\pythonw.exe log_receiver.py

The farm on the other PCs finds it by itself (a "where are you?" message on the local network,
port 9120) and sends its log-py.txt plus its problem screenshots (not the every-5-minute ones)
to port 9121. They land in
    %USERPROFILE%\\Pictures\\Screenshots\\anime-legacy-log\\from-<PC name>\\

Safety: it only accepts text appended to that log and .jpg pictures, from private (home network)
addresses, with size limits. Nothing can be read back except how much of the log it already has,
and nothing is ever run. Pictures older than 3 days are deleted.
"""
from __future__ import annotations

import datetime as dt
import glob
import http.server
import ipaddress
import os
import socket
import sys
import threading
import time
import urllib.parse

UDP_PORT, HTTP_PORT = 9120, 9121
HELLO, REPLY = b"anime-legacy-log?", b"anime-legacy-log-here"
ROOT = os.path.expandvars(r"%USERPROFILE%\Pictures\Screenshots\anime-legacy-log")
MAX_CHUNK = 1_000_000          # bytes of log per request
MAX_SHOT = 3_000_000
KEEP_SHOTS_H = 72
lock = threading.Lock()


def note(msg):
    try:
        os.makedirs(ROOT, exist_ok=True)
        with open(os.path.join(ROOT, "log-receiver.txt"), "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%m-%d %H:%M:%S}  {msg}\n")
    except OSError:
        pass


def safe_name(s, maxlen=40):
    s = "".join(c for c in (s or "") if c.isalnum() or c in "-_")[:maxlen]
    return s or None


def folder(sender):
    d = os.path.join(ROOT, "from-" + sender)
    os.makedirs(d, exist_ok=True)
    return d


def allowed(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_private or a.is_loopback


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "anime-legacy-log/1"

    def log_message(self, format, *args):
        pass

    def _send(self, code, text=""):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _args(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        return u.path, q, safe_name(q.get("from"))

    def do_GET(self):
        if not allowed(self.client_address[0]):
            return self._send(403)
        path, q, sender = self._args()
        if not sender:
            return self._send(400)
        d = folder(sender)
        if path == "/size":
            p = os.path.join(d, "log-py.txt")
            return self._send(200, str(os.path.getsize(p) if os.path.exists(p) else 0))
        if path == "/shots":
            return self._send(200, "\n".join(os.path.basename(p) for p in glob.glob(os.path.join(d, "*.jpg"))))
        return self._send(404)

    def do_POST(self):
        if not allowed(self.client_address[0]):
            return self._send(403)
        path, q, sender = self._args()
        n = int(self.headers.get("Content-Length") or 0)
        if not sender or n <= 0:
            return self._send(400)
        if n > (MAX_SHOT if path == "/shot" else MAX_CHUNK):
            return self._send(413)
        data = self.rfile.read(n)
        d = folder(sender)
        if path == "/log":
            p = os.path.join(d, "log-py.txt")
            at = int(q.get("at", -1))
            with lock:
                have = os.path.getsize(p) if os.path.exists(p) else 0
                if at == 0 and have > 0:      # their log started over (it is renamed at 2 MB)
                    os.replace(p, os.path.join(d, "log-py-old.txt"))
                    have = 0
                if at != have:
                    return self._send(409, str(have))
                with open(p, "ab") as f:
                    f.write(data)
                return self._send(200, str(have + len(data)))
        if path == "/shot":
            name = q.get("name", "")
            stem = safe_name(name[:-4] if name.lower().endswith(".jpg") else "", 60)
            if not stem or not data.startswith(b"\xff\xd8"):
                return self._send(400)
            with open(os.path.join(d, stem + ".jpg"), "wb") as f:
                f.write(data)
            return self._send(200, "ok")
        return self._send(404)


def answer_hellos():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", UDP_PORT))
    me = socket.gethostname().encode()
    while True:
        try:
            data, addr = s.recvfrom(256)
            if data.strip() == HELLO and allowed(addr[0]):
                s.sendto(REPLY + b" %d " % HTTP_PORT + me, addr)
        except OSError:
            time.sleep(1)


def prune():
    while True:
        cut = time.time() - KEEP_SHOTS_H * 3600
        for p in glob.glob(os.path.join(ROOT, "from-*", "*.jpg")):
            try:
                if os.path.getmtime(p) < cut:
                    os.remove(p)
            except OSError:
                pass
        time.sleep(3600)


def main():
    try:
        srv = http.server.ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    except OSError as e:          # already running
        note(f"not started: port {HTTP_PORT} in use ({e})")
        return 1
    threading.Thread(target=answer_hellos, daemon=True).start()
    threading.Thread(target=prune, daemon=True).start()
    note(f"log receiver running on {socket.gethostname()} (ports {UDP_PORT}/{HTTP_PORT})")
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
