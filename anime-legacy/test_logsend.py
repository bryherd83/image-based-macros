"""Log sending between PCs, for real over this PC's own network connection (127.0.0.1 and a
test port), into temporary folders. Never touches the real log folder.

    python test_logsend.py
"""
import os
import socket
import tempfile
import threading
import time
import http.server

import log_receiver as rc
import logsend

tmp = tempfile.mkdtemp(prefix="logsend-test-")
rc.ROOT = os.path.join(tmp, "pc")
laptop = os.path.join(tmp, "laptop")
os.makedirs(laptop)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), rc.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]

log = os.path.join(laptop, "log-py.txt")
with open(log, "w", encoding="utf-8") as f:
    f.write("10-15 22:45:01  joining the trial\n" * 3)
for name in ("1015-224521-py-trial-spawn-mismatch.jpg", "1015-224845-py-every-5min.jpg"):
    with open(os.path.join(laptop, name), "wb") as f:
        f.write(b"\xff\xd8 fake jpeg")
    os.utime(os.path.join(laptop, name), (time.time() - 60, time.time() - 60))

snd = logsend.Sender({}, laptop, me="LAPTOP-1")
snd.target = ("127.0.0.1", port, "ThePC")
print("round 1:", snd.once())
got = os.path.join(rc.ROOT, "from-LAPTOP-1")
assert open(os.path.join(got, "log-py.txt"), "rb").read() == open(log, "rb").read()
assert os.listdir(got) == ["1015-224521-py-trial-spawn-mismatch.jpg", "log-py.txt"], os.listdir(got)

with open(log, "a", encoding="utf-8") as f:
    f.write("10-15 22:48:33  trial: left after wave 24\n")
print("round 2:", snd.once())
assert open(os.path.join(got, "log-py.txt"), "rb").read() == open(log, "rb").read()
print("round 3:", r := snd.once())
assert r == "sent 0 bytes, 0 picture(s)"

# the farm restarts (forgets what it sent): nothing is sent twice
snd2 = logsend.Sender({}, laptop, me="LAPTOP-1")
snd2.target = snd.target
assert snd2.once() == "sent 0 bytes, 0 picture(s)"

# the laptop's log got renamed at 2 MB and started over: the PC keeps the old one as -old
os.replace(log, log.replace(".txt", "-old.txt"))
with open(log, "w", encoding="utf-8") as f:
    f.write("10-16 08:00:00  Anime Legacy auto farm loaded\n")
print("log started over:", snd.once())
assert open(os.path.join(got, "log-py.txt"), "rb").read() == open(log, "rb").read()
assert os.path.exists(os.path.join(got, "log-py-old.txt"))

# bad requests are refused
import urllib.request, urllib.error
def post(q, data):
    try:
        return urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{q}", data=data, method="POST")).status
    except urllib.error.HTTPError as e:
        return e.code
assert post("/shot?from=x&name=..%2F..%2Fevil.jpg", b"\xff\xd8x") == 200      # name is cleaned...
assert not os.path.exists(os.path.join(rc.ROOT, "evil.jpg"))                     # ...stays in from-x
assert post("/shot?from=x&name=a.jpg", b"MZ not a jpeg") == 400
assert post("/shot?from=x&name=a.exe", b"\xff\xd8x") == 400
assert post("/log?from=x&at=5", b"x") == 409
assert rc.allowed("192.168.1.50") and rc.allowed("127.0.0.1") and rc.allowed("100.77.102.84") and not rc.allowed("8.8.8.8")

# the receiver is this same PC: nothing is sent
snd3 = logsend.Sender({}, laptop, me="ThePC")
snd3.target = ("127.0.0.1", port, "ThePC")
assert snd3.once() == "receiver is this PC"

# PC switched off: the sender lets go and looks again later
srv.shutdown(); srv.server_close()
assert snd.once() == "lost receiver" and snd.target is None

# finding the receiver on the network (test port, so a real receiver isn't disturbed)
logsend.UDP_PORT = rc.UDP_PORT = 39120
threading.Thread(target=rc.answer_hellos, daemon=True).start()
time.sleep(0.3)
print("broadcast to:", logsend.broadcast_addrs())
found = logsend.find_receiver(timeout=2, addrs=["127.0.0.1"])   # (the firewall rule lets the real one in)
print("found:", found)
assert found and found[1] == rc.HTTP_PORT and found[2] == socket.gethostname()
print("logsend: ok")


# ---- live status page: state + screen picture in, page + /api out
import json as _json
import numpy as np
rc.ROOT = os.path.join(tmp, "pc2")
srv2 = http.server.ThreadingHTTPServer(("127.0.0.1", 0), rc.Handler)
threading.Thread(target=srv2.serve_forever, daemon=True).start()
port2 = srv2.server_address[1]
snd4 = logsend.Sender({}, laptop, me="LAPTOP-1")
snd4.target = ("127.0.0.1", port2, "ThePC")
snd4.once()
frame = np.zeros((1080, 1920, 3), np.uint8)
assert snd4.send_live({"on": True, "run": "trial", "wave": "14/50", "doing": "<b>trial</b> wave 14"}, frame)
api = _json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port2}/api").read())
farm_ = api["farms"][0]
print("api:", {k: farm_[k] for k in ("pc", "age", "pic_age", "dungeons", "trials")}, farm_["status"]["wave"])
assert farm_["pc"] == "LAPTOP-1" and farm_["age"] <= 2 and farm_["status"]["run"] == "trial" and farm_["pic_age"] <= 2
img = urllib.request.urlopen(f"http://127.0.0.1:{port2}/live.jpg?from=LAPTOP-1").read()
assert img[:2] == b"\xff\xd8"
page = urllib.request.urlopen(f"http://127.0.0.1:{port2}/").read().decode()
assert "<script>" in page and "/api" in page
open(os.path.join(tmp, "page.js"), "w", encoding="utf-8").write(page.split("<script>")[1].split("</script>")[0])
print("page.js:", os.path.join(tmp, "page.js"))
print("live page: ok")
