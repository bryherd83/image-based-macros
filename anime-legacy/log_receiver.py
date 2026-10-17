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

Live status page (phone or any browser on the home network): http://<this PC's address>:9121/
It shows what each farm is doing right now, a picture of its screen (every 20 s), today's
dungeons and trials, problems and the latest log lines. Read-only.
"""
from __future__ import annotations

import datetime as dt
import glob
import http.server
import ipaddress
import json
import os
import re
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
    # home network, this PC, or your own devices through Tailscale (100.64.0.0/10)
    return a.is_private or a.is_loopback or a in ipaddress.ip_network("100.64.0.0/10")


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

    def _send_bytes(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not allowed(self.client_address[0]):
            return self._send(403)
        path, q, sender = self._args()
        if path in ("/", "/index.html"):
            return self._send_bytes(200, PAGE.encode(), "text/html; charset=utf-8")
        if path == "/api":
            return self._send_bytes(200, json.dumps(overview()).encode(), "application/json")
        if path == "/live.jpg" and sender:
            p = os.path.join(ROOT, "from-" + sender, "live.jpg")
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return self._send_bytes(200, f.read(), "image/jpeg")
            return self._send(404)
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
        if n > (MAX_SHOT if path in ("/shot", "/live") else MAX_CHUNK):
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
        if path == "/status":
            try:
                st = json.loads(data.decode("utf-8"))
                assert isinstance(st, dict)
            except Exception:
                return self._send(400)
            st = {str(k)[:30]: str(v)[:300] for k, v in list(st.items())[:30]}
            with lock:
                LIVE[sender] = (time.time(), st)
            return self._send(200, "ok")
        if path == "/live":
            if not data.startswith(b"\xff\xd8"):
                return self._send(400)
            tmp = os.path.join(d, "live.tmp")
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, os.path.join(d, "live.jpg"))
            return self._send(200, "ok")
        if path == "/shot":
            name = q.get("name", "")
            stem = safe_name(name[:-4] if name.lower().endswith(".jpg") else "", 60)
            if not stem or not data.startswith(b"\xff\xd8"):
                return self._send(400)
            with open(os.path.join(d, stem + ".jpg"), "wb") as f:
                f.write(data)
            return self._send(200, "ok")
        return self._send(404)


LIVE = {}                      # sender -> (time received, status dict)
LINE = re.compile(r"^(\d\d-\d\d) (\d\d:\d\d:\d\d)  (.*)$")
PROBLEM_WORDS = ("pressing Spawn", "error", "couldn't reach", "frozen", "didn't show up",
                 "reconnect", "stuck over and over", "won't clear", "Roblox didn't open", "no new frames")


def summary(sender):
    """Today's dungeons / trials / problems and the latest lines, from the received log."""
    p = os.path.join(ROOT, "from-" + sender, "log-py.txt")
    try:
        with open(p, "rb") as f:
            f.seek(max(0, os.path.getsize(p) - 600_000))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {}
    today = dt.datetime.now().strftime("%m-%d")
    rows = []
    for ln in text.splitlines():
        m = LINE.match(ln.rstrip("\r"))
        if m and m.group(1) == today and not m.group(3).startswith("screenshot:"):
            rows.append((m.group(2), m.group(3)))
    dmins = [float(x) for _, msg in rows for x in re.findall(r"dungeon finished · \d+ rooms cleared by the macro in ([\d.]+) min", msg)]
    trials = sum(1 for _, msg in rows if msg.startswith("trial: left after wave"))
    problems, last = [], None
    for t, msg in rows:
        if any(w in msg for w in PROBLEM_WORDS) and not msg.startswith("saving an Instant Replay"):
            if msg.startswith("trial: nothing hit") and last and last.startswith("trial: nothing hit"):
                continue
            problems.append(f"{t[:5]}  {msg[:120]}")
        last = msg
    return {"dungeons": len(dmins), "dungeon_avg": round(sum(dmins) / len(dmins), 1) if dmins else None,
            "trials": trials, "problems": problems[-6:],
            "lines": [f"{t}  {msg[:140]}" for t, msg in rows[-18:]],
            "last_line": rows[-1][0] if rows else None}


def overview():
    out = []
    for d in sorted(glob.glob(os.path.join(ROOT, "from-*"))):
        sender = os.path.basename(d)[5:]
        t, st = LIVE.get(sender, (None, {}))
        live = os.path.join(d, "live.jpg")
        out.append({"pc": sender, "age": round(time.time() - t) if t else None, "status": st,
                    "pic_age": round(time.time() - os.path.getmtime(live)) if os.path.exists(live) else None,
                    **summary(sender)})
    return {"now": dt.datetime.now().strftime("%H:%M:%S"), "farms": out}


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anime Legacy farm</title>
<style>
body{margin:0;background:#111;color:#eee;font:15px system-ui,sans-serif}
.card{margin:10px;padding:12px;background:#1d1d1d;border-radius:12px}
h2{margin:0 0 6px;font-size:18px} .big{font-size:20px;font-weight:600;margin:4px 0}
.ok{color:#5d5} .warn{color:#fc4} .bad{color:#f55} .dim{color:#999;font-size:13px}
img{width:100%;border-radius:8px;margin-top:8px} pre{white-space:pre-wrap;font-size:12px;color:#bbb;margin:6px 0 0}
.row{display:flex;gap:14px;flex-wrap:wrap;margin-top:6px}
</style></head><body><div id="app">Loading...</div>
<script>
function esc(s){return String(s==null?"":s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
// every value from a farm goes through esc() (or is a number / encodeURIComponent; PC names are
// letters and digits only), so nothing a farm sends can add HTML to the page
async function tick(){
 try{
  const r=await fetch("/api",{cache:"no-store"}); const j=await r.json(); let h="";
  if(!j.farms.length) h='<div class="card">No farm has sent anything yet.</div>';
  for(const f of j.farms){
   const s=f.status||{}; let state,cls;
   if(f.age==null||f.age>60){state="Not reporting"+(f.age!=null?" for "+Math.round(f.age/60)+" min":"")+" (macro closed, laptop asleep, or update not installed)";cls="bad"}
   else if(s.on!=="True"){state="Farm is OFF (press F6 on the laptop)";cls="warn"}
   else if(s.roblox_in_front==="False"){state="Paused: Roblox isn't the window in front";cls="warn"}
   else if(s.run==="dungeon"){state="Dungeon";cls="ok"}
   else if(s.run==="trial"){state="Trial · wave "+esc(s.wave);cls="ok"}
   else if(s.run==="defense"){state="Defense (the game plays it) · waiting for the next dungeon / trial";cls="ok"}
   else{state="Waiting for the next dungeon / trial";cls="ok"}
   h+='<div class="card"><h2>'+esc(f.pc)+'</h2><div class="big '+cls+'">'+state+'</div>';
   if(f.age!=null&&f.age<=60){
    h+='<div>'+esc(s.doing)+'</div><div class="row dim"><span>enemies '+esc(s.enemies)+'</span>';
    if(s.run==="dungeon") h+='<span>rooms '+esc(s.rooms)+'</span>';
    h+='<span>updated '+f.age+' s ago</span></div>';
   }
   if(f.pic_age!=null&&f.pic_age<300) h+='<img src="/live.jpg?from='+encodeURIComponent(f.pc)+'&t='+Date.now()+'"><div class="dim">screen '+f.pic_age+' s ago</div>';
   h+='<div class="row"><span>Today: <b>'+(f.dungeons||0)+'</b> dungeons'+(f.dungeon_avg?' (avg '+f.dungeon_avg+' min)':'')+', <b>'+(f.trials||0)+'</b> trials</span></div>';
   if(f.problems&&f.problems.length) h+='<div class="warn" style="margin-top:6px">Problems today:</div><pre>'+f.problems.map(esc).join("\n")+'</pre>';
   else h+='<div class="ok dim" style="margin-top:6px">No problems today</div>';
   h+='<details><summary class="dim">Latest log lines</summary><pre>'+(f.lines||[]).map(esc).join("\n")+'</pre></details></div>';
  }
  h+='<div class="dim" style="margin:10px">Page updated '+j.now+' · refreshes by itself</div>';
  document.getElementById("app").innerHTML=h;
 }catch(e){document.getElementById("app").innerHTML='<div class="card bad">Cannot reach the gaming PC (is it on and on the home Wi-Fi?)</div>'}
}
tick(); setInterval(tick,5000);
</script></body></html>"""


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
