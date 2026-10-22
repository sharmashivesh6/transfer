"""Drag-and-drop LAN file transfer. Run on every machine: python transfer.py
Open http://<other-machine-ip>:8000 in a browser, drop files, they land in its ~/Downloads/Transfer Files.
Stdlib only, works on Windows and macOS."""
import json, os, socket, sys, urllib.parse, webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
# not "Transfer": the downloaded app itself is usually ~/Downloads/Transfer
SHARE = Path.home() / "Downloads" / "Transfer Files"
CHUNK = 1 << 20

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transfer · %(host)s</title><style>
:root{--bg:#0d0f14;--card:#161a22;--line:#262c38;--text:#e8ecf3;--dim:#8a93a6;--acc:#4f8cff}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);padding:32px 16px}
main{max-width:720px;margin:auto}h1{font-size:22px;margin:0}.sub{color:var(--dim);margin:4px 0 24px}
#drop{border:2px dashed var(--line);border-radius:16px;padding:56px 16px;text-align:center;cursor:pointer;transition:.15s;background:var(--card)}
#drop.over{border-color:var(--acc);background:#1a2233}#drop b{display:block;font-size:18px;margin-bottom:4px}
.row{display:flex;align-items:center;gap:12px;padding:12px 14px;border-bottom:1px solid var(--line)}
.row:last-child{border:0}.name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.size{color:var(--dim);font-size:13px}
.bar{height:4px;background:var(--line);border-radius:2px;flex:0 0 120px;overflow:hidden}.bar i{display:block;height:100%%;width:0;background:var(--acc)}
a{color:var(--acc);text-decoration:none}.list{background:var(--card);border-radius:12px;margin-top:20px}h2{font-size:14px;color:var(--dim);margin:28px 0 0;font-weight:500}
</style></head><body><main>
<h1>%(host)s</h1><p class="sub">Files dropped here are saved on this machine in <code>%(share)s</code></p>
<div id="drop"><b>Drop files here</b><span class="sub">or click to choose</span><input id="pick" type="file" multiple hidden></div>
<div class="list" id="up"></div><h2>On this machine</h2><div class="list" id="files"></div>
<script>
const fmt=b=>b<1024?b+" B":b<1<<20?(b/1024).toFixed(1)+" KB":b<1<<30?(b/1048576).toFixed(1)+" MB":(b/1073741824).toFixed(2)+" GB";
const drop=document.getElementById("drop"),pick=document.getElementById("pick");
drop.onclick=()=>pick.click();pick.onchange=()=>send(pick.files);
["dragenter","dragover"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("over")}));
["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("over")}));
drop.addEventListener("drop",ev=>send(ev.dataTransfer.files));
function send(files){for(const f of files){
  const row=document.createElement("div");row.className="row";
  row.innerHTML=`<span class="name"></span><span class="size">${fmt(f.size)}</span><span class="bar"><i></i></span>`;
  row.querySelector(".name").textContent=f.name;document.getElementById("up").prepend(row);
  const x=new XMLHttpRequest(),bar=row.querySelector("i");
  x.upload.onprogress=e=>bar.style.width=(e.loaded/e.total*100)+"%%";
  x.onload=()=>{bar.style.width="100%%";bar.style.background=x.status==200?"#3ecf8e":"#ff5c5c";load()};
  x.onerror=()=>bar.style.background="#ff5c5c";
  x.open("PUT","/upload/"+encodeURIComponent(f.name));x.send(f);}}
async function load(){const r=await fetch("/api/files"),l=await r.json(),el=document.getElementById("files");
  el.innerHTML=l.length?"":'<div class="row sub">Nothing yet</div>';
  for(const f of l){const row=document.createElement("div");row.className="row";
    const a=document.createElement("a");a.className="name";a.textContent=f.name;a.href="/files/"+encodeURIComponent(f.name);a.download=f.name;
    row.append(a);row.insertAdjacentHTML("beforeend",`<span class="size">${fmt(f.size)}</span>`);el.append(row);}}
load();setInterval(load,3000);
</script></main></body></html>"""


def safe_name(raw):
    # strip any path parts (both / and \) so uploads can't escape SHARE
    name = os.path.basename(urllib.parse.unquote(raw).replace("\\", "/")).strip()
    return "" if name in ("", ".", "..") else name


def unique(path):
    stem, suf, n = path.stem, path.suffix, 1
    while path.exists():
        path = path.with_name(f"{stem} ({n}){suf}")
        n += 1
    return path


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SHARE), **kw)

    def send_body(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            html = PAGE % {"host": socket.gethostname(), "share": SHARE}
            return self.send_body(html.encode(), "text/html; charset=utf-8")
        if self.path == "/api/files":
            files = [{"name": p.name, "size": p.stat().st_size}
                     for p in sorted(SHARE.iterdir(), key=lambda p: -p.stat().st_mtime)
                     if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".part")]
            return self.send_body(json.dumps(files).encode(), "application/json")
        if self.path.startswith("/files/"):
            self.path = self.path[len("/files"):]
            return super().do_GET()
        self.send_error(404)

    def list_directory(self, path):
        self.send_error(404)  # no raw directory listings; the page has its own

    def do_PUT(self):
        name = safe_name(self.path[len("/upload/"):]) if self.path.startswith("/upload/") else ""
        if not name:
            return self.send_error(400, "bad filename")
        left = int(self.headers.get("Content-Length", 0))
        tmp = SHARE / f".{name}.part"
        try:
            with open(tmp, "wb") as f:
                while left:
                    buf = self.rfile.read(min(CHUNK, left))
                    if not buf:
                        raise ConnectionError("client disconnected")
                    f.write(buf)
                    left -= len(buf)
            tmp.rename(unique(SHARE / name))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        self.send_body(b"ok", "text/plain")

    def log_message(self, fmt, *args):
        if self.command == "PUT":
            print(f"  received {safe_name(self.path[8:])} from {self.client_address[0]}")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet sent, just picks the LAN interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    try:
        SHARE.mkdir(parents=True, exist_ok=True)
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError as e:
        # keep the window open so a double-clicked app shows why it failed
        print(f"Could not start: {e}\n(Already running in another window? Close it first.)", flush=True)
        input("Press Enter to close.")
        sys.exit(1)
    url = f"http://{lan_ip()}:{PORT}"
    print(f"Transfer running.\n  This machine:  {url}\n  Saving to:     {SHARE}\n"
          f"Open the OTHER machine's address in your browser to send files to it. Ctrl+C to stop.", flush=True)
    webbrowser.open(f"http://localhost:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
