"""Transfer: drag-and-drop file sharing between computers on the same network (Windows + macOS).
Open the app on each computer; they find each other automatically. Drop files on a computer to send.
Received files go to ~/Downloads/Transfer Files.
Runs in its own window when pywebview is installed (the built apps), else in the default browser."""
import http.client, ipaddress, json, os, socket, subprocess, sys, threading, time, urllib.parse, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000  # preferred; falls back to any free port
DISCO = 8001  # UDP port computers announce themselves on
# not "Transfer": the downloaded app itself is usually ~/Downloads/Transfer
SHARE = Path.home() / "Downloads" / "Transfer Files"
CHUNK = 1 << 20
ME = uuid.uuid4().hex
NAME = socket.gethostname().removesuffix(".local")
peers = {}  # id -> {"name", "ip", "port", "seen"}
incoming = {}  # upload key -> {"name", "from", "size", "got"}, while a file is arriving
offers = {}  # offer id -> {"from", "files", "event", "ok"}, waiting for Accept/Decline
allowed = {}  # token -> {"from", "files": [[name, size], ...]}: accepted files not yet received
ASK_SECS = 120  # how long a send request waits for an answer

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transfer</title><style>
:root{--bg:#f4f5f7;--card:#fff;--line:#e2e5ea;--text:#15181d;--dim:#6b7380;--acc:#2f6bff;--accbg:#edf2ff;--ok:#1fa971;--bad:#e5484d}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--line:#2a2f38;--text:#e9ecf1;--dim:#8d95a3;--acc:#5b8cff;--accbg:#1b2438}}
*{box-sizing:border-box}html,body{margin:0;min-height:100%}
body{font:14px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);padding:24px;-webkit-user-select:none;user-select:none;cursor:default}
header{display:flex;align-items:center;gap:12px}
.logo{width:42px;height:42px;border-radius:12px;background:var(--acc);display:grid;place-items:center}
h1{font-size:18px;margin:0}.dim{color:var(--dim);font-size:13px}
h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);margin:28px 0 10px;font-weight:600;display:flex;justify-content:space-between;align-items:center}
.peers{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
.peer{background:var(--card);border:2px dashed var(--line);border-radius:16px;padding:22px 14px;text-align:center;cursor:pointer;transition:.15s}
.peer:hover,.peer.over{border-color:var(--acc);background:var(--accbg)}.peer.over{transform:scale(1.03)}
.peer svg{color:var(--acc)}.peer b{display:block;margin-top:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.empty{background:var(--card);border-radius:16px;padding:28px 20px;text-align:center;color:var(--dim)}
.empty b{display:block;color:var(--text);font-size:15px;margin-bottom:4px}
.spin{width:22px;height:22px;border:3px solid var(--line);border-top-color:var(--acc);border-radius:50%;margin:0 auto 12px;animation:r 1s linear infinite}@keyframes r{to{transform:rotate(360deg)}}
.add{margin-top:14px;display:flex;gap:8px;justify-content:center}
input{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);width:170px}
button,.link{font:inherit;border:0;background:none;color:var(--acc);cursor:pointer;padding:6px 8px;border-radius:8px}button:hover{background:var(--accbg)}
.list{background:var(--card);border-radius:12px;overflow:hidden}
.row{display:flex;align-items:center;gap:12px;padding:11px 14px;border-top:1px solid var(--line)}.row:first-child{border:0}
.list.files .row{cursor:pointer}.list.files .row:hover{background:var(--accbg)}
.name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.meta{color:var(--dim);font-size:12px;white-space:nowrap}
.bar{height:5px;background:var(--line);border-radius:3px;flex:0 0 110px;overflow:hidden}.bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .2s}
.ok .bar i{background:var(--ok)}.bad .bar i{background:var(--bad)}.bad .meta{color:var(--bad)}
#toast{position:fixed;left:50%;bottom:20px;transform:translate(-50%,80px);background:var(--text);color:var(--bg);padding:10px 16px;border-radius:10px;transition:.3s;max-width:80%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#toast.show{transform:translate(-50%,0)}
.offer{background:var(--card);border:2px solid var(--acc);border-radius:16px;padding:16px 18px;margin-top:20px;display:flex;gap:10px;align-items:center;box-shadow:0 6px 24px rgba(47,107,255,.15)}
.offer svg{color:var(--acc);flex:none}.offer .txt{flex:1;min-width:0}.offer .txt b{display:block;font-size:15px}.offer .dim{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{padding:9px 18px;border-radius:10px;font-weight:600;background:var(--accbg)}.btn.primary{background:var(--acc);color:#fff}.btn.primary:hover{background:var(--acc);filter:brightness(1.1)}
</style></head><body>
<header><div class="logo"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4v13M3 13l4 4 4-4M17 20V7M13 11l4-4 4 4"/></svg></div>
<div><h1>Transfer</h1><div class="dim" id="me">Starting…</div></div></header>
<div id="offers"></div>
<h2>Send to</h2><div id="peers"></div>
<div id="sendwrap" hidden><h2>Sending</h2><div class="list" id="sending"></div></div>
<div id="recvwrap" hidden><h2>Receiving</h2><div class="list" id="receiving"></div></div>
<h2>Received <button id="folder">Show folder</button></h2><div class="list files" id="files"></div>
<input id="pick" type="file" multiple hidden><div id="toast"></div>
<script>
const $=s=>document.querySelector(s);
const fmt=b=>b<1024?b+" B":b<1<<20?(b/1024).toFixed(0)+" KB":b<1<<30?(b/1048576).toFixed(1)+" MB":(b/1073741824).toFixed(2)+" GB";
const api=(p,o={})=>fetch(p,{...o,headers:{"X-Transfer":"1"}});
const esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const PC='<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>';
let peers=[],peerKey=null,known=null,target=null,toastT;
function toast(t){const e=$("#toast");e.textContent=t;e.classList.add("show");clearTimeout(toastT);toastT=setTimeout(()=>e.classList.remove("show"),3500)}
function drawPeers(){const el=$("#peers");
  if(!peers.length){el.className="";el.innerHTML=`<div class="empty"><div class="spin"></div><b>Looking for other computers…</b>
    Open Transfer on another computer connected to the same Wi-Fi or network.
    <div class="add"><input id="ip" placeholder="Or type its address"><button id="addbtn">Add</button></div></div>`;
    const add=()=>{const v=$("#ip").value.trim();if(v)api("/api/add?ip="+encodeURIComponent(v),{method:"POST"}).then(r=>r.ok?poll():toast("That doesn't look like an address"))};
    $("#addbtn").onclick=add;$("#ip").onkeydown=e=>e.key=="Enter"&&add();return}
  el.className="peers";el.innerHTML="";
  for(const p of peers){const d=document.createElement("div");d.className="peer";
    d.innerHTML=`${PC}<b>${esc(p.name)}</b><span class="dim">Drop files or click</span>`;
    d.ondragover=e=>{e.preventDefault();d.classList.add("over")};d.ondragleave=()=>d.classList.remove("over");
    d.ondrop=e=>{e.preventDefault();e.stopPropagation();d.classList.remove("over");send(p,e.dataTransfer.files)};
    d.onclick=()=>{target=p;$("#pick").click()};el.append(d)}}
$("#pick").onchange=e=>{send(target,e.target.files);e.target.value=""};
addEventListener("dragover",e=>e.preventDefault());
addEventListener("drop",e=>{e.preventDefault();if(peers.length==1)send(peers[0],e.dataTransfer.files);else if(peers.length)toast("Drop the files onto a computer")});
const fail=(r,m)=>{r.className="row bad";r.querySelector("i").style.width="100%";r.querySelector(".meta").textContent=m};
async function send(p,files){files=[...files];if(!files.length)return;$("#sendwrap").hidden=false;
  const rows=files.map(f=>{const r=document.createElement("div");r.className="row";
    r.innerHTML=`<span class="name"></span><span class="meta">Waiting for ${esc(p.name)} to accept…</span><span class="bar"><i></i></span>`;
    r.querySelector(".name").textContent=f.name;$("#sending").prepend(r);return r});
  let res=null;try{res=await api("/api/offer?to="+p.id,{method:"POST",body:JSON.stringify(files.map(f=>({name:f.name,size:f.size})))})}catch(e){}
  if(!res||!res.ok){const m=res?await res.text():"Couldn't reach "+p.name;rows.forEach(r=>fail(r,m||"Failed"));return}
  const {token}=await res.json();rows.forEach(r=>r.querySelector(".meta").textContent="Accepted · queued");
  for(let i=0;i<files.length;i++)await upload(p,files[i],rows[i],token)}  // one at a time, in order
function upload(p,f,r,token){return new Promise(done=>{const x=new XMLHttpRequest(),bar=r.querySelector("i"),meta=r.querySelector(".meta");
  meta.textContent=`to ${p.name} · ${fmt(f.size)}`;
  x.upload.onprogress=e=>bar.style.width=(e.loaded/e.total*100)+"%";
  x.onload=()=>{if(x.status==200){r.className="row ok";bar.style.width="100%";meta.textContent="Sent to "+p.name}else fail(r,x.responseText||"Failed");done()};
  x.onerror=()=>{fail(r,"Couldn't reach "+p.name);done()};
  x.open("POST",`/api/send?to=${p.id}&token=${token}&name=${encodeURIComponent(f.name)}`);x.setRequestHeader("X-Transfer","1");x.send(f)})}
let offerKey="";
function drawOffers(list){const k=list.map(o=>o.id).join();if(k===offerKey)return;offerKey=k;const el=$("#offers");el.innerHTML="";
  for(const o of list){const d=document.createElement("div");d.className="offer";
    const more=o.count>o.files.length?` and ${o.count-o.files.length} more`:"";
    d.innerHTML=`${PC}<div class="txt"><b>${esc(o.from)} wants to send you ${o.count==1?"a file":o.count+" files"} · ${fmt(o.total)}</b>
      <div class="dim">${o.files.map(esc).join(", ")}${more}</div></div><button class="btn">Decline</button><button class="btn primary">Accept</button>`;
    const [no,yes]=d.querySelectorAll("button"),decide=ok=>{d.remove();api(`/api/decide?id=${o.id}&ok=${ok?1:0}`,{method:"POST"})};
    no.onclick=()=>decide(false);yes.onclick=()=>decide(true);el.append(d)}}
function drawFiles(files){const el=$("#files");
  el.innerHTML=files.length?"":'<div class="row dim">Files other computers send you will appear here.</div>';
  for(const f of files){const r=document.createElement("div");r.className="row";r.title="Show in folder";
    r.innerHTML=`<span class="name"></span><span class="meta">${fmt(f.size)} · ${new Date(f.time*1000).toLocaleString([],{dateStyle:"short",timeStyle:"short"})}</span>`;
    r.querySelector(".name").textContent=f.name;r.onclick=()=>api("/api/reveal?name="+encodeURIComponent(f.name),{method:"POST"});el.append(r)}}
function drawIncoming(list){$("#recvwrap").hidden=!list.length;const el=$("#receiving");el.innerHTML="";
  for(const f of list){const r=document.createElement("div");r.className="row";
    r.innerHTML=`<span class="name"></span><span class="meta">from ${esc(f.from)} · ${fmt(f.got)} of ${fmt(f.size)}</span><span class="bar"><i style="width:${f.size?f.got/f.size*100:0}%"></i></span>`;
    r.querySelector(".name").textContent=f.name;el.append(r)}}
$("#folder").onclick=()=>api("/api/reveal",{method:"POST"});
let busy=false;
async function poll(){try{const s=await(await api("/api/state")).json();
  drawOffers(s.offers);drawIncoming(s.incoming);busy=s.incoming.length>0;
  $("#me").textContent=`This computer: ${s.name} · ${s.ip}`;
  const k=JSON.stringify(s.peers);if(k!==peerKey){peerKey=k;peers=s.peers;if(!document.activeElement||document.activeElement.id!="ip"||peers.length)drawPeers()}
  const names=s.files.map(f=>f.name);
  if(known)for(const n of names)if(!known.has(n))toast("Received "+n);
  known=new Set(names);drawFiles(s.files)}catch(e){}
  setTimeout(poll,busy?400:1500)}  // refresh faster while a file is arriving
poll();
</script></body></html>"""


def safe_name(raw):
    # strip any path parts (both / and \) so names can't escape SHARE
    name = os.path.basename(urllib.parse.unquote(raw).replace("\\", "/")).strip()
    return "" if name in ("", ".", "..") else name


def unique(path):
    stem, suf, n = path.stem, path.suffix, 1
    while path.exists():
        path = path.with_name(f"{stem} ({n}){suf}")
        n += 1
    return path


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet sent, just picks the LAN interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def reveal(path):
    # show in Finder/Explorer rather than open: received files come from other people
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)] if path.is_file() else ["explorer", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])


def bring_to_front():
    try:
        import webview
        w = webview.windows[0]
        w.restore()
        w.on_top = True  # flipping on_top is the portable way to raise a window
        w.on_top = False
    except Exception:
        pass  # browser mode, or the window is already gone


def announce():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        msg = json.dumps({"id": ME, "name": NAME, "port": PORT}).encode()
        # ponytail: assumes a /24 home/office subnet; manual "add by address" covers the rest
        for addr in ("255.255.255.255", lan_ip().rsplit(".", 1)[0] + ".255"):
            try:
                s.sendto(msg, (addr, DISCO))
            except OSError:
                pass
        time.sleep(2)


def listen():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    try:
        s.bind(("", DISCO))
    except OSError:
        return  # discovery off; adding by address still works
    while True:
        data, (ip, _) = s.recvfrom(2048)
        try:
            m = json.loads(data)
            if m["id"] != ME:
                peers.pop("manual-" + ip, None)
                peers[str(m["id"])[:64]] = {"name": str(m["name"])[:64], "ip": ip, "port": int(m["port"]), "seen": time.time()}
        except (ValueError, KeyError, TypeError):
            pass


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        body = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def local(self, page=False):
        # app-only routes: loopback + our own Host (blocks DNS rebinding) + custom header (blocks other websites)
        ok = self.client_address[0] in ("127.0.0.1", "::1") and self.headers.get("Host") == f"127.0.0.1:{PORT}"
        return ok and (page or self.headers.get("X-Transfer") == "1")

    def route(self):
        u = urllib.parse.urlsplit(self.path)
        return u.path, {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

    def do_GET(self):
        path, _ = self.route()
        if path == "/" and self.local(page=True):
            return self.reply(200, PAGE, "text/html; charset=utf-8")
        if path == "/api/state" and self.local():
            now = time.time()
            files = [{"name": p.name, "size": p.stat().st_size, "time": p.stat().st_mtime}
                     for p in sorted(SHARE.iterdir(), key=lambda p: -p.stat().st_mtime)
                     if p.is_file() and not p.name.startswith(".")]
            live = [{"id": k, "name": v["name"], "ip": v["ip"]} for k, v in list(peers.items()) if now - v["seen"] < 7]
            asks = [{"id": k, "from": o["from"], "files": [f[0] for f in o["files"][:4]], "count": len(o["files"]),
                     "total": sum(f[1] for f in o["files"])} for k, o in list(offers.items())]
            state = {"name": NAME, "ip": lan_ip(), "peers": sorted(live, key=lambda p: p["name"].lower()),
                     "files": files, "incoming": list(incoming.values()), "offers": asks}
            return self.reply(200, json.dumps(state), "application/json")
        self.reply(404)

    def do_POST(self):
        path, q = self.route()
        if path == "/offer":
            return self.receive_offer()
        if not self.local():
            return self.reply(403)
        if path == "/api/offer":
            return self.offer_to_peer(peers.get(q.get("to", "")))
        if path == "/api/decide":
            o = offers.get(q.get("id", ""))
            if o:
                o["ok"] = q.get("ok") == "1"
                o["event"].set()
            return self.reply(200)
        if path == "/api/send":
            return self.send_to_peer(peers.get(q.get("to", "")), safe_name(q.get("name", "")), q.get("token", ""))
        if path == "/api/reveal":
            name = safe_name(q.get("name", ""))
            target = SHARE / name if name else SHARE
            if target.exists():
                reveal(target)
            return self.reply(200)
        if path == "/api/add":
            try:
                ip = str(ipaddress.ip_address(q.get("ip", "").strip()))
            except ValueError:
                return self.reply(400)
            peers["manual-" + ip] = {"name": ip, "ip": ip, "port": 8000, "seen": float("inf")}
            return self.reply(200)
        self.reply(404)

    def receive_offer(self):
        # another computer asks to send files; hold the request open until the user answers
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 1 << 20)))
            sender = str(body["from"])[:64]
            files = [[safe_name(str(f["name"])), max(0, int(f["size"]))] for f in body["files"]][:1000]
        except (ValueError, KeyError, TypeError):
            return self.reply(400)
        files = [f for f in files if f[0]]
        if not files:
            return self.reply(400)
        oid, event = uuid.uuid4().hex, threading.Event()
        offers[oid] = o = {"from": sender, "files": files, "event": event, "ok": False}
        bring_to_front()
        event.wait(ASK_SECS)
        offers.pop(oid, None)
        if not o["ok"]:
            return self.reply(403, f"{NAME} declined" if event.is_set() else f"{NAME} didn't answer")
        token = uuid.uuid4().hex
        allowed[token] = {"from": sender, "files": files}
        self.reply(200, json.dumps({"token": token}), "application/json")

    def offer_to_peer(self, peer):
        if not peer:
            return self.reply(400, "That computer is no longer available")
        try:
            files = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return self.reply(400, "Bad request")
        conn = http.client.HTTPConnection(peer["ip"], peer["port"], timeout=ASK_SECS + 10)
        try:
            conn.request("POST", "/offer", json.dumps({"from": NAME, "files": files}), {"Content-Type": "application/json"})
            r = conn.getresponse()
            status, data = r.status, r.read()
        except OSError:
            return self.reply(502, f"Couldn't reach {peer['name']}")
        finally:
            conn.close()
        if status == 404:
            return self.reply(502, f"{peer['name']} needs to update Transfer")
        self.reply(status, data, "application/json" if status == 200 else "text/plain; charset=utf-8")

    def send_to_peer(self, peer, name, token):
        # the window uploads to us and we stream it on to the peer, so no cross-origin requests are needed
        if not peer or not name:
            return self.reply(400, "That computer is no longer available")
        conn = http.client.HTTPConnection(peer["ip"], peer["port"], timeout=15)
        try:
            conn.connect()
        except OSError:
            return self.reply(502, f"Couldn't reach {peer['name']}")
        left = int(self.headers.get("Content-Length", 0))
        try:
            conn.putrequest("PUT", "/upload/" + urllib.parse.quote(name))
            conn.putheader("Content-Length", str(left))
            conn.putheader("X-Token", token)
            conn.endheaders()
            while left:
                buf = self.rfile.read(min(CHUNK, left))
                if not buf:
                    raise ConnectionError("window closed mid-send")
                conn.send(buf)
                left -= len(buf)
            status = conn.getresponse().status
        except OSError:
            return self.reply(502, f"Lost connection to {peer['name']}")
        finally:
            conn.close()
        self.reply(200 if status == 200 else 502, "ok" if status == 200 else f"{peer['name']} couldn't save the file")

    def do_PUT(self):
        # receive one file, only if the user accepted it (see receive_offer)
        path, _ = self.route()
        name = safe_name(path[len("/upload/"):]) if path.startswith("/upload/") else ""
        left = int(self.headers.get("Content-Length", 0))
        grant = allowed.get(self.headers.get("X-Token", ""))
        try:
            grant["files"].remove([name, left])  # each accepted file can arrive once
        except (TypeError, ValueError):
            return self.reply(403, "Not accepted")
        if not grant["files"]:
            allowed.pop(self.headers["X-Token"], None)
        key = uuid.uuid4().hex
        incoming[key] = info = {"name": name, "from": grant["from"], "size": left, "got": 0}
        tmp = SHARE / f".{key}.part"
        try:
            with open(tmp, "wb") as f:
                while left:
                    buf = self.rfile.read(min(CHUNK, left))
                    if not buf:
                        raise ConnectionError("sender disconnected")
                    f.write(buf)
                    left -= len(buf)
                    info["got"] += len(buf)
            tmp.rename(unique(SHARE / name))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        finally:
            incoming.pop(key, None)
        self.reply(200, "ok")

    def log_message(self, *args):
        pass  # windowed apps have no console to log to


def main():
    global PORT
    SHARE.mkdir(parents=True, exist_ok=True)
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        srv = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    PORT = srv.server_address[1]
    for fn in (srv.serve_forever, announce, listen):
        threading.Thread(target=fn, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"
    try:
        import webview
    except ImportError:
        print(f"Transfer is open in your browser: {url}  (Ctrl+C to quit)", flush=True)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return
    webview.create_window("Transfer", url, width=760, height=640, min_size=(440, 520))
    webview.start()


if __name__ == "__main__":
    main()
