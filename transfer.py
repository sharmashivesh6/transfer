"""Transfer: drag-and-drop file sharing between computers on the same network (Windows + macOS).
Open the app on each computer; they find each other automatically. Drop files on a computer to send;
the other side clicks Accept. Received files go to ~/Downloads/Transfer Files.
Runs in its own window when pywebview is installed (the built apps), else in the default browser."""
import http.client, ipaddress, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, urllib.parse, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000  # preferred; falls back to any free port
DISCO = 8001  # UDP port computers announce themselves on
# not "Transfer": the downloaded app itself is usually ~/Downloads/Transfer
SHARE = Path.home() / "Downloads" / "Transfer Files"
CHUNK = 1 << 20
ME = uuid.uuid4().hex
NAME = socket.gethostname().removesuffix(".local")
OS = {"darwin": "Mac", "win32": "Windows"}.get(sys.platform, "Linux")
peers = {}  # id -> {"name", "ip", "port", "os", "seen"}
offers = {}  # offer id -> {"from", "files", "event", "ok", "t"}, waiting for Accept/Decline
allowed = {}  # token -> {"from", "files": [[name, size], ...], "batch"}: accepted files not yet received
batches = {}  # batch id -> progress of an accepted set of incoming files, for the receiving window
ASK_SECS = 120  # how long a send request waits for an answer
VERSION = "dev"  # the release build replaces this with the git tag, e.g. "v1.1"
REPO = "https://github.com/sharmashivesh6/transfer"
FROZEN = getattr(sys, "frozen", False)  # running as the built app, so it can update itself
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash for curl on Windows
latest = None  # newer release tag, once found

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Transfer</title><style>
:root{--bg:#eef1f6;--card:rgba(255,255,255,.74);--solid:#fff;--line:rgba(16,24,40,.08);--text:#0f1320;--dim:#667085;--acc:#3b6cff;--acc2:#8b5cf6;--accbg:rgba(59,108,255,.09);--ok:#12b76a;--bad:#f04438;--rim:rgba(255,255,255,.75);--shadow:0 1px 2px rgba(16,24,40,.04),0 12px 32px -10px rgba(16,24,40,.14)}
@media (prefers-color-scheme:dark){:root{--bg:#090b11;--card:rgba(22,26,36,.72);--solid:#161a24;--line:rgba(255,255,255,.07);--text:#eef1f7;--dim:#8b93a7;--acc:#6b8cff;--acc2:#a78bfa;--accbg:rgba(107,140,255,.13);--rim:rgba(255,255,255,.06);--shadow:0 12px 32px -10px rgba(0,0,0,.6)}}
*{box-sizing:border-box}html,body{margin:0;min-height:100%}
body{font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);-webkit-user-select:none;user-select:none;cursor:default;overflow-x:hidden}
.bgfx{position:fixed;inset:-20%;z-index:-1;pointer-events:none;background:radial-gradient(40% 35% at 20% 20%,rgba(59,108,255,.16),transparent 70%),radial-gradient(35% 30% at 80% 30%,rgba(139,92,246,.14),transparent 70%),radial-gradient(40% 35% at 60% 90%,rgba(56,189,248,.12),transparent 70%);animation:drift 24s ease-in-out infinite alternate}
@keyframes drift{to{transform:translate(4%,-3%) rotate(6deg) scale(1.05)}}
main{max-width:980px;margin:0 auto;padding:22px 24px 48px}
header{display:flex;align-items:center;gap:14px}
.logo{width:48px;height:48px;border-radius:15px;display:grid;place-items:center;flex:none;background:linear-gradient(135deg,var(--acc),var(--acc2),#38bdf8,var(--acc));background-size:300% 300%;animation:shift 8s ease infinite;box-shadow:0 10px 24px -8px rgba(91,108,255,.7)}
@keyframes shift{50%{background-position:100% 50%}}
h1{font-size:21px;margin:0;letter-spacing:-.02em}
.chip{display:inline-flex;align-items:center;gap:7px;color:var(--dim);font-size:13px}
.live{width:8px;height:8px;border-radius:50%;background:var(--ok);animation:live 2s infinite}
@keyframes live{0%{box-shadow:0 0 0 0 rgba(18,183,106,.55)}70%,100%{box-shadow:0 0 0 7px rgba(18,183,106,0)}}
h2{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);margin:30px 0 12px;font-weight:650;display:flex;justify-content:space-between;align-items:center}
.glass{background:var(--card);backdrop-filter:blur(18px) saturate(1.4);-webkit-backdrop-filter:blur(18px) saturate(1.4);border:1px solid var(--rim);box-shadow:var(--shadow)}
button{font:inherit;border:0;background:none;color:var(--acc);cursor:pointer;padding:7px 10px;border-radius:10px;font-weight:550}button:hover{background:var(--accbg)}
input{font:inherit;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--solid);color:var(--text);width:190px;outline:none}input:focus{border-color:var(--acc)}

/* computers */
.peers{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px}
.peer{position:relative;border-radius:20px;padding:22px 14px 18px;text-align:center;cursor:pointer;transition:transform .25s cubic-bezier(.2,.8,.2,1),box-shadow .25s,border-color .25s;animation:in .5s cubic-bezier(.2,.8,.2,1) backwards}
.peer:hover{transform:translateY(-4px);box-shadow:0 18px 40px -12px rgba(59,108,255,.35)}
.av{width:64px;height:64px;margin:0 auto;border-radius:20px;display:grid;place-items:center;color:#fff;position:relative;background:linear-gradient(135deg,hsl(var(--h) 80% 60%),hsl(calc(var(--h) + 50) 80% 52%));box-shadow:0 10px 24px -8px hsl(var(--h) 80% 50% / .7)}
.av .dot{position:absolute;right:-3px;bottom:-3px;width:16px;height:16px;border-radius:50%;background:var(--ok);border:3px solid var(--solid)}
.peer b{display:block;margin-top:12px;font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.peer .sub{color:var(--dim);font-size:12px}
.peer .hint{display:block;margin-top:10px;font-size:12px;color:var(--dim);transition:.2s}
body.dragging .peer{animation:wig 1.2s ease-in-out infinite;border-color:var(--acc)}
.peer.over,body.dragging .peer.over{animation:none;transform:scale(1.07);border-color:var(--acc);box-shadow:0 0 0 5px var(--accbg),0 22px 50px -10px rgba(59,108,255,.6)}
.peer.over .hint{color:var(--acc);font-weight:650}
.peer.pop{animation:pop .5s}
@keyframes pop{30%{transform:scale(.9)}65%{transform:scale(1.06)}}
@keyframes in{from{opacity:0;transform:translateY(12px) scale(.96)}}
@keyframes wig{50%{transform:translateY(-3px) rotate(-.7deg)}}
#dropHint{position:fixed;left:50%;top:14px;transform:translate(-50%,-90px);background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;padding:10px 20px;border-radius:999px;font-weight:650;box-shadow:0 12px 30px -8px rgba(59,108,255,.8);transition:.35s cubic-bezier(.2,.8,.2,1);z-index:9;pointer-events:none}
body.dragging #dropHint{transform:translate(-50%,0)}
.empty{border-radius:22px;padding:30px 20px;text-align:center;color:var(--dim)}
.empty b{display:block;color:var(--text);font-size:16px;margin:18px 0 4px}
.radar{position:relative;width:132px;height:132px;margin:0 auto;border-radius:50%;background:radial-gradient(circle,var(--accbg),transparent 70%)}
.radar i{position:absolute;inset:0;border-radius:50%;border:2px solid var(--acc);opacity:0;animation:ring 2.4s cubic-bezier(.2,.6,.4,1) infinite}
.radar i:nth-child(2){animation-delay:.8s}.radar i:nth-child(3){animation-delay:1.6s}
@keyframes ring{0%{transform:scale(.3);opacity:.8}100%{transform:scale(1);opacity:0}}
.radar .sweep{position:absolute;inset:0;border-radius:50%;background:conic-gradient(from 0deg,transparent 0 72%,rgba(91,140,255,.4));animation:spin 2.2s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.radar .me{position:absolute;inset:40px;border-radius:16px;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,var(--acc),var(--acc2));box-shadow:0 8px 20px -6px rgba(91,108,255,.8)}
.add{margin-top:16px;display:flex;gap:8px;justify-content:center}

/* accept card */
@property --a{syntax:"<angle>";inherits:false;initial-value:0deg}
.offer{position:relative;margin-top:20px;border-radius:22px;padding:2px;background:conic-gradient(from var(--a),#3b6cff,#8b5cf6,#38bdf8,#f472b6,#3b6cff);animation:rot 3s linear infinite,in .5s cubic-bezier(.2,.8,.2,1);box-shadow:0 18px 50px -14px rgba(91,108,255,.6)}
@keyframes rot{to{--a:360deg}}
.offer .in{border-radius:20px;background:var(--solid);padding:16px 18px;display:flex;gap:14px;align-items:center}
.offer .av{width:52px;height:52px;margin:0;border-radius:16px;flex:none}
.offer .txt{flex:1;min-width:0}.offer .txt b{display:block;font-size:15.5px}
.offer .dim{color:var(--dim);font-size:12.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ring{width:38px;height:38px;flex:none;position:relative;display:grid;place-items:center;font-size:11px;color:var(--dim);font-variant-numeric:tabular-nums}
.ring svg{position:absolute;inset:0;transform:rotate(-90deg)}.ring circle{fill:none;stroke-width:3}.ring .bgc{stroke:var(--line)}
.ring .fg{stroke:var(--acc);stroke-linecap:round;stroke-dasharray:107;transition:stroke-dashoffset 1s linear}
.btn{padding:10px 18px;border-radius:12px;font-weight:650;background:var(--accbg)}
.btn.primary{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;box-shadow:0 8px 20px -6px rgba(91,108,255,.75)}
.btn.primary:hover{filter:brightness(1.1);background:linear-gradient(135deg,var(--acc),var(--acc2))}

/* update banner */
.ver{font-size:11px;font-weight:650;color:var(--dim);background:var(--accbg);padding:2px 7px;border-radius:99px;vertical-align:middle;letter-spacing:0}.ver:empty{display:none}
.update{margin-top:20px;border-radius:18px;padding:14px 16px;display:flex;gap:14px;align-items:center;animation:in .5s cubic-bezier(.2,.8,.2,1)}
.update .uic{width:40px;height:40px;border-radius:12px;flex:none;display:grid;place-items:center;background:linear-gradient(135deg,#12b76a,#38bdf8);box-shadow:0 8px 20px -6px rgba(18,183,106,.7);animation:nudge 2s ease-in-out infinite}
@keyframes nudge{50%{transform:translateY(-3px)}}
.update .txt{flex:1;min-width:0}.update .txt b{display:block;font-size:15px}.update .dim{color:var(--dim);font-size:12.5px}
.update .btn:disabled{opacity:.85;cursor:default}
.uspin{display:inline-block;width:12px;height:12px;margin-right:8px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;vertical-align:-1px;animation:spin .8s linear infinite}

/* transfer stage */
.stage{position:relative;margin-top:22px;border-radius:26px;height:0;opacity:0;overflow:hidden;color:#eef2ff;
  background:radial-gradient(120% 90% at 50% 0%,#1c2753 0%,#0b1022 55%,#05070f 100%);border:1px solid rgba(255,255,255,.08);
  box-shadow:0 30px 60px -22px rgba(20,30,90,.6),inset 0 1px 0 rgba(255,255,255,.08);transition:height .55s cubic-bezier(.2,.8,.2,1),opacity .4s}
.stage.open{height:350px;opacity:1}
.stage::before{content:"";position:absolute;inset:0;background-image:radial-gradient(rgba(255,255,255,.08) 1px,transparent 1px);background-size:22px 22px;-webkit-mask-image:radial-gradient(70% 70% at 50% 40%,#000,transparent);mask-image:radial-gradient(70% 70% at 50% 40%,#000,transparent)}
#fx{position:absolute;inset:0;width:100%;height:100%;z-index:2;pointer-events:none}
.dev{position:absolute;bottom:56px;width:150px;text-align:center;z-index:1}
#ldev{left:7%}#rdev{right:7%}
.screen{height:94px;border-radius:10px 10px 3px 3px;background:#10131c;border:3px solid #2c3343;padding:4px;position:relative;transition:box-shadow .4s,transform .14s}
.display{height:100%;border-radius:4px;background:linear-gradient(160deg,#1e2b52,#0c1222);overflow:hidden;position:relative;display:grid;place-items:center;color:#c7d2fe}
.display svg{position:relative;z-index:1;opacity:.95}
.fill{position:absolute;left:0;right:0;bottom:0;height:0;background:linear-gradient(0deg,rgba(91,140,255,.95),rgba(139,92,246,.55));box-shadow:0 -2px 16px rgba(140,160,255,.9)}
.fill::before{content:"";position:absolute;left:-50%;right:-50%;top:-6px;height:12px;background:radial-gradient(ellipse at center,rgba(255,255,255,.65),transparent 60%);animation:wave 1.6s ease-in-out infinite}
@keyframes wave{50%{transform:translateX(22%)}}
.base{height:9px;margin:0 -16px;background:linear-gradient(#e2e6ee,#8a92a1);clip-path:polygon(0 0,100% 0,97% 100%,3% 100%);border-radius:0 0 10px 10px}
.dname{margin-top:10px;font-size:12.5px;color:#aeb8d6;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stage.waiting .src .screen,.stage.active .src .screen{box-shadow:0 0 30px rgba(91,140,255,.6)}
.stage.active .dst .screen{box-shadow:0 0 36px rgba(139,92,246,.65)}
.stage.done .dst .screen{box-shadow:0 0 40px rgba(18,183,106,.7)}
.screen.bump{transform:translateY(2px) scale(1.025)}
.center{position:absolute;left:50%;top:128px;transform:translateX(-50%);text-align:center;z-index:3;width:44%}
.status{font-size:13px;font-weight:650;color:#c7d2fe;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pctw{position:relative;height:76px;transition:opacity .3s}.stage.waiting .pctw{opacity:.3}
.pct{font-size:66px;font-weight:800;letter-spacing:-.045em;line-height:76px;font-variant-numeric:tabular-nums;background:linear-gradient(180deg,#fff 30%,#a5b4fc);-webkit-background-clip:text;background-clip:text;color:transparent;transition:opacity .3s,transform .45s}
.pct small{font-size:26px;font-weight:700;letter-spacing:0}
.check{position:absolute;left:50%;top:50%;width:68px;height:68px;margin:-34px 0 0 -34px;opacity:0;transform:scale(.4) rotate(-20deg);transition:.5s cubic-bezier(.2,1.5,.4,1)}
.check circle{fill:#12b76a;filter:drop-shadow(0 0 18px rgba(18,183,106,.85))}
.check path{fill:none;stroke:#fff;stroke-width:6;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:60;stroke-dashoffset:60}
.stage.done .pct{opacity:0;transform:scale(.6)}.stage.done .check{opacity:1;transform:none}.stage.done .check path{transition:stroke-dashoffset .5s .25s;stroke-dashoffset:0}
.stats{font-size:12.5px;color:#9fb0dd;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fileline{font-size:12px;color:#7d8bb5;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-height:18px}
.pbar{position:absolute;left:24px;right:24px;bottom:22px;height:8px;border-radius:99px;background:rgba(255,255,255,.08);overflow:hidden;z-index:3}
.pbar i{position:absolute;top:0;bottom:0;left:0;width:0;border-radius:99px;background:linear-gradient(90deg,#3b6cff,#8b5cf6,#38bdf8,#3b6cff);background-size:200% 100%;animation:flow 1.6s linear infinite;box-shadow:0 0 18px rgba(120,140,255,.95)}
.pbar i::after{content:"";position:absolute;inset:0;background:repeating-linear-gradient(115deg,rgba(255,255,255,.2) 0 10px,transparent 10px 20px);background-size:22px 100%;animation:stripes .7s linear infinite}
@keyframes flow{to{background-position:-200% 0}}@keyframes stripes{to{background-position:22px 0}}
.stage.waiting .pbar i{width:28%!important;animation:indet 1.4s ease-in-out infinite}
@keyframes indet{from{left:-28%}to{left:100%}}
.stage.done .pbar i{background:linear-gradient(90deg,#12b76a,#34d399);box-shadow:0 0 18px rgba(18,183,106,.9)}
.stage.fail .pbar i{background:#f04438;box-shadow:none}.stage.fail{animation:shake .5s}
@keyframes shake{20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}
#stageClose{position:absolute;top:12px;right:14px;z-index:4;color:#c7d2fe;opacity:0;pointer-events:none;transition:.2s}
.stage.done #stageClose,.stage.fail #stageClose{opacity:1;pointer-events:auto}#stageClose:hover{background:rgba(255,255,255,.08)}
.spark{position:absolute;left:20px;top:14px;z-index:3;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:#7d8bb5;opacity:0;transition:.3s}.stage.active .spark{opacity:1}
.dots i{display:inline-block;width:4px;height:4px;margin-left:3px;border-radius:50%;background:currentColor;vertical-align:middle;animation:bounce 1.2s infinite}
.dots i:nth-child(2){animation-delay:.15s}.dots i:nth-child(3){animation-delay:.3s}
@keyframes bounce{40%{transform:translateY(-4px)}}

/* lists */
.list{border-radius:18px;overflow:hidden}
.row{display:flex;align-items:center;gap:12px;padding:11px 16px;border-top:1px solid var(--line)}.row:first-child{border:0}
.ficon{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-size:9.5px;font-weight:800;letter-spacing:.02em;color:#fff;flex:none;background:linear-gradient(135deg,hsl(var(--h) 75% 58%),hsl(calc(var(--h) + 40) 75% 48%))}
.files .row{cursor:pointer;transition:background .2s}.files .row:hover{background:var(--accbg)}
.row.new{animation:newrow 1.8s ease-out}
@keyframes newrow{0%{background:rgba(18,183,106,.28);transform:translateX(-10px)}25%{transform:none}100%{background:transparent}}
.name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}.meta{color:var(--dim);font-size:12px;white-space:nowrap}
.bar{height:6px;background:var(--line);border-radius:99px;flex:0 0 120px;overflow:hidden}
.bar i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,var(--acc),var(--acc2));transition:width .25s}
.ok .bar i{background:var(--ok)}.bad .bar i{background:var(--bad)}.bad .meta{color:var(--bad)}
.muted{color:var(--dim)}
#toast{position:fixed;left:50%;bottom:22px;transform:translate(-50%,90px);background:var(--text);color:var(--bg);padding:11px 18px;border-radius:14px;font-weight:550;transition:.35s cubic-bezier(.2,.8,.2,1);max-width:80%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;box-shadow:0 12px 30px -8px rgba(0,0,0,.4);z-index:9}
#toast.show{transform:translate(-50%,0)}
@media (max-width:640px){.dev{width:108px}.screen{height:68px}.pct{font-size:48px}.center{width:50%}.stage.open{height:310px}#ldev{left:4%}#rdev{right:4%}}
@media (prefers-reduced-motion:reduce){*{animation-duration:.01s!important;animation-iteration-count:1!important}}
</style></head><body>
<div class="bgfx"></div><div id="dropHint">Drop onto a computer to send</div>
<main>
<header><div class="logo"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4v13M3 13l4 4 4-4M17 20V7M13 11l4-4 4 4"/></svg></div>
<div><h1>Transfer <span class="ver" id="ver"></span></h1><div class="chip"><span class="live"></span><span id="me">Starting…</span></div></div></header>
<div id="update" class="update glass" hidden><div class="uic"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg></div>
  <div class="txt"><b id="utitle"></b><div class="dim">New features and fixes. Takes a few seconds, then Transfer reopens.</div></div><button class="btn primary" id="ubtn">Update now</button></div>
<div id="offers"></div>
<section id="stage" class="stage" hidden>
  <canvas id="fx"></canvas><div class="spark">Live speed</div><button id="stageClose">Close</button>
  <div class="dev" id="ldev"><div class="screen"><div class="display"><div class="fill"></div><svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg></div></div><div class="base"></div><div class="dname" id="lname">This computer</div></div>
  <div class="dev" id="rdev"><div class="screen"><div class="display"><div class="fill"></div><svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg></div></div><div class="base"></div><div class="dname" id="rname"></div></div>
  <div class="center"><div class="status" id="sstatus"></div>
    <div class="pctw"><div class="pct"><span id="pct">0</span><small id="pctd">%</small></div><svg class="check" viewBox="0 0 70 70"><circle cx="35" cy="35" r="33"/><path d="M21 36l9 9 19-20"/></svg></div>
    <div class="stats" id="stats"></div><div class="fileline" id="fileline"></div></div>
  <div class="pbar"><i id="pfill"></i></div>
</section>
<h2>Send to</h2><div id="peers"></div>
<div id="sendwrap" hidden><h2>Activity</h2><div class="list glass" id="sending"></div></div>
<h2>Received <button id="folder">Show folder</button></h2><div class="list glass files" id="files"></div>
</main>
<input id="pick" type="file" multiple hidden><div id="toast"></div>
<script>
const $=s=>document.querySelector(s);
const RM=matchMedia("(prefers-reduced-motion: reduce)").matches;
const fmt=b=>b<1024?Math.round(b)+" B":b<1<<20?(b/1024).toFixed(0)+" KB":b<1<<30?(b/1048576).toFixed(1)+" MB":(b/1073741824).toFixed(2)+" GB";
const fmtT=s=>!isFinite(s)||s<0?"…":s<60?Math.max(1,Math.ceil(s))+"s":s<3600?Math.floor(s/60)+"m "+Math.floor(s%60)+"s":Math.floor(s/3600)+"h "+Math.floor(s%3600/60)+"m";
const api=(p,o={})=>fetch(p,{...o,headers:{"X-Transfer":"1"}});
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const hue=s=>{let h=7;for(const c of String(s))h=(h*31+c.charCodeAt(0))%360;return h};
const ext=n=>{const m=n.match(/\.([A-Za-z0-9]{1,4})$/);return m?m[1].toUpperCase():"FILE"};
const PC=s=>`<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>`;
let peers=[],peerKey=null,known=null,target=null,toastT,filesKey=null,myName="This computer";
function toast(t){const e=$("#toast");e.textContent=t;e.classList.add("show");clearTimeout(toastT);toastT=setTimeout(()=>e.classList.remove("show"),3500)}
let AC;function chime(kind){try{AC=AC||new(window.AudioContext||window.webkitAudioContext)();const t0=AC.currentTime;
  (kind=="done"?[659.25,987.77,1318.51]:[880,1174.66]).forEach((f,i)=>{const o=AC.createOscillator(),g=AC.createGain(),t=t0+i*.09;
    o.type="sine";o.frequency.value=f;g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.1,t+.015);g.gain.exponentialRampToValueAtTime(.0001,t+.55);
    o.connect(g).connect(AC.destination);o.start(t);o.stop(t+.6)})}catch(e){}}

/* ---------- computers ---------- */
function drawPeers(){const el=$("#peers");
  if(!peers.length){el.className="";el.innerHTML=`<div class="empty glass"><div class="radar"><i></i><i></i><i></i><span class="sweep"></span><div class="me">${PC(26)}</div></div>
    <b>Looking for other computers…</b>Open Transfer on another computer connected to the same Wi-Fi or network.
    <div class="add"><input id="ip" placeholder="Or type its address"><button id="addbtn">Add</button></div></div>`;
    const add=()=>{const v=$("#ip").value.trim();if(v)api("/api/add?ip="+encodeURIComponent(v),{method:"POST"}).then(r=>r.ok?poll():toast("That doesn't look like an address"))};
    $("#addbtn").onclick=add;$("#ip").onkeydown=e=>e.key=="Enter"&&add();return}
  el.className="peers";el.innerHTML="";
  peers.forEach((p,i)=>{const d=document.createElement("div");d.className="peer glass";d.style.animationDelay=i*70+"ms";
    d.innerHTML=`<div class="av" style="--h:${hue(p.name)}">${PC(30)}<span class="dot"></span></div><b>${esc(p.name)}</b>
      <span class="sub">${esc(p.os||"Computer")} · ${esc(p.ip)}</span><span class="hint">Drop files or click</span>`;
    const hint=d.querySelector(".hint");let n=0;
    const off=()=>{n=0;d.classList.remove("over");hint.textContent="Drop files or click"};
    d.ondragenter=e=>{e.preventDefault();n++;d.classList.add("over");hint.textContent="Release to send"};
    d.ondragover=e=>e.preventDefault();d.ondragleave=()=>{if(--n<=0)off()};
    d.ondrop=e=>{e.preventDefault();e.stopPropagation();off();endDrag();pop(d);send(p,e.dataTransfer.files)};
    d.onclick=()=>{target=[p,d];$("#pick").click()};el.append(d)})}
function pop(d){d.classList.remove("pop");void d.offsetWidth;d.classList.add("pop")}
$("#pick").onchange=e=>{if(target){pop(target[1]);send(target[0],e.target.files)}e.target.value=""};
let dragN=0;const endDrag=()=>{dragN=0;document.body.classList.remove("dragging")};
addEventListener("dragenter",e=>{if([...e.dataTransfer.types].includes("Files")&&peers.length){dragN++;document.body.classList.add("dragging")}});
addEventListener("dragleave",()=>{if(--dragN<=0)endDrag()});
addEventListener("dragover",e=>e.preventDefault());
addEventListener("drop",e=>{e.preventDefault();endDrag();if(peers.length==1)send(peers[0],e.dataTransfer.files);else if(peers.length)toast("Drop the files onto a computer")});

/* ---------- sending ---------- */
function row(f){const r=document.createElement("div");r.className="row";
  r.innerHTML=`<span class="ficon" style="--h:${hue(ext(f.name))}">${ext(f.name)}</span><span class="name"></span><span class="meta"></span><span class="bar"><i></i></span>`;
  r.querySelector(".name").textContent=f.name;$("#sending").prepend(r);return r}
const setRow=(r,cls,m,w)=>{if(cls!=null)r.className="row "+cls;if(m!=null)r.querySelector(".meta").textContent=m;if(w!=null)r.querySelector("i").style.width=w+"%"};
async function send(p,files){files=[...files];if(!files.length)return;$("#sendwrap").hidden=false;
  const sid={},mine=()=>st.sid===sid,total=files.reduce((a,f)=>a+f.size,0);
  stageOpen({mode:"send",peer:p.name,count:files.length,total,state:"waiting",sid});
  const rows=files.map(f=>{const r=row(f);setRow(r,"",`Waiting for ${p.name}…`);return r});
  let res=null;try{res=await api("/api/offer?to="+p.id,{method:"POST",body:JSON.stringify(files.map(f=>({name:f.name,size:f.size})))})}catch(e){}
  if(!res||!res.ok){const m=(res&&await res.text())||"Couldn't reach "+p.name;rows.forEach(r=>setRow(r,"bad",m,100));if(mine())stageFail(m);return}
  const {token}=await res.json();rows.forEach(r=>setRow(r,"","Queued"));
  if(mine()){stageState("active");st.t0=performance.now()}
  let base=0,bad=0;
  for(let i=0;i<files.length;i++){const f=files[i];
    if(!await upload(p,f,rows[i],token,l=>{if(mine())stageProg(base+l,f.name,i+1)}))bad++;
    base+=f.size;if(mine())stageProg(base,f.name,i+1)}
  if(mine())bad?stageFail(bad==files.length?`Couldn't send to ${p.name}`:`${bad} of ${files.length} files didn't send`):stageDone()}
function upload(p,f,r,token,prog){return new Promise(done=>{const x=new XMLHttpRequest();setRow(r,"",`to ${p.name} · ${fmt(f.size)}`);
  x.upload.onprogress=e=>{if(e.total){setRow(r,null,null,e.loaded/e.total*100);prog(e.loaded)}};
  x.onload=()=>{const ok=x.status==200;setRow(r,ok?"ok":"bad",ok?"Sent to "+p.name:(x.responseText||"Failed"),100);done(ok)};
  x.onerror=()=>{setRow(r,"bad","Couldn't reach "+p.name,100);done(false)};
  x.open("POST",`/api/send?to=${p.id}&token=${token}&name=${encodeURIComponent(f.name)}`);x.setRequestHeader("X-Transfer","1");x.send(f)})}

/* ---------- the stage: two laptops, a beam, flying folders ---------- */
const stage=$("#stage"),cv=$("#fx"),cx=cv.getContext("2d"),st={on:false};
let parts=[],folders=[],ripples=[],confetti=[],lastSpawn=0,lastFrame=0,raf=0,ping=0;
function stageOpen(o){const was=stage.classList.contains("open");clearTimeout(st.closeT);
  Object.assign(st,{on:true,mode:o.mode,peer:o.peer,count:o.count,total:o.total,done:0,shown:0,idx:1,file:"",sid:o.sid||null,bid:o.bid||null,
    t0:performance.now(),samples:[],speed:0,hist:[],msg:"",doneAt:0,elapsed:0});
  parts=[];folders=[];ripples=[];confetti=[];lastFrame=0;
  const L=$("#ldev"),R=$("#rdev"),send=o.mode=="send";
  L.className="dev "+(send?"src":"dst");R.className="dev "+(send?"dst":"src");
  st.srcFill=(send?L:R).querySelector(".fill");st.dstFill=(send?R:L).querySelector(".fill");st.dstScreen=(send?R:L).querySelector(".screen");
  $("#lname").textContent="You · "+myName;$("#rname").textContent=o.peer;
  stage.hidden=false;stage.className=`stage ${o.mode} ${o.state}`+(was?" open":"");st.state=o.state;
  if(!was)requestAnimationFrame(()=>requestAnimationFrame(()=>stage.classList.add("open")));
  if(!raf)raf=requestAnimationFrame(frame)}
function stageState(s){st.state=s;stage.classList.remove("waiting","active","done","fail");stage.classList.add(s)}
function stageProg(done,file,idx){st.done=Math.max(st.done,done);if(file)st.file=file;if(idx)st.idx=idx;
  const now=performance.now();st.samples.push([now,st.done]);while(st.samples.length>2&&now-st.samples[0][0]>2500)st.samples.shift();
  const [t0,d0]=st.samples[0];if(now-t0>250){const sp=(st.done-d0)/((now-t0)/1000);st.speed=st.speed?st.speed*.75+sp*.25:sp}}
function stageDone(){if(st.state=="done")return;st.done=st.total;st.elapsed=(performance.now()-st.t0)/1000;stageState("done");st.doneAt=performance.now();
  burst();chime("done");st.closeT=setTimeout(stageClose,7000)}
function stageFail(m){st.msg=m;stageState("fail");clearTimeout(st.closeT);st.closeT=setTimeout(stageClose,9000)}
function stageClose(){clearTimeout(st.closeT);stage.classList.remove("open");setTimeout(()=>{if(!stage.classList.contains("open")){stage.hidden=true;st.on=false}},500)}
$("#stageClose").onclick=stageClose;
stage.onmouseenter=()=>{if(st.state=="done"||st.state=="fail")clearTimeout(st.closeT)};
stage.onmouseleave=()=>{if(st.state=="done"||st.state=="fail")st.closeT=setTimeout(stageClose,3000)};

const ease=t=>t<.5?2*t*t:1-(-2*t+2)**2/2;
const bez=(A,C,B,t)=>{const u=1-t;return{x:u*u*A.x+2*u*t*C.x+t*t*B.x,y:u*u*A.y+2*u*t*C.y+t*t*B.y}};
const nrm=(A,C,B,t)=>{const dx=2*(1-t)*(C.x-A.x)+2*t*(B.x-C.x),dy=2*(1-t)*(C.y-A.y)+2*t*(B.y-C.y),l=Math.hypot(dx,dy)||1;return{x:-dy/l,y:dx/l}};
function arc(A,C,B){cx.beginPath();cx.moveTo(A.x,A.y);cx.quadraticCurveTo(C.x,C.y,B.x,B.y)}
function rr(x,y,w,h,r){cx.beginPath();cx.roundRect?cx.roundRect(x,y,w,h,r):cx.rect(x,y,w,h)}
function folder(x,y,s,rot,glow){cx.save();cx.translate(x,y);cx.rotate(rot);cx.scale(s,s);
  if(glow){cx.shadowColor="rgba(96,140,255,.9)";cx.shadowBlur=18}
  cx.fillStyle="#2f6df6";rr(-16,-13,14,6,2);cx.fill();rr(-16,-10,32,23,3);cx.fill();cx.shadowBlur=0;
  cx.fillStyle="#eef3ff";rr(-12,-8,24,15,1.5);cx.fill();
  const g=cx.createLinearGradient(0,-4,0,13);g.addColorStop(0,"#8ab8ff");g.addColorStop(1,"#3b7bf7");cx.fillStyle=g;
  cx.beginPath();cx.moveTo(-17,-3);cx.lineTo(17,-3);cx.lineTo(15,13);cx.lineTo(-15,13);cx.closePath();cx.fill();cx.restore()}
function anchors(){const r=cv.getBoundingClientRect(),L=$("#ldev .screen").getBoundingClientRect(),R=$("#rdev .screen").getBoundingClientRect();
  const a={x:L.left+L.width/2-r.left,y:L.top-r.top+10},b={x:R.left+R.width/2-r.left,y:R.top-r.top+10};return st.mode=="send"?[a,b]:[b,a]}
function bump(){const s=st.dstScreen;if(!s||s._b)return;s._b=1;s.classList.add("bump");setTimeout(()=>{s.classList.remove("bump");s._b=0},130)}
function burst(){if(RM)return;const B=st.B||{x:cv.clientWidth/2,y:120},cols=["#60a5fa","#a78bfa","#34d399","#fbbf24","#f472b6","#ffffff"];
  for(let i=0;i<170;i++){const a=-Math.PI/2+(Math.random()-.5)*Math.PI*1.2,v=220+Math.random()*440;
    confetti.push({x:B.x,y:B.y,vx:Math.cos(a)*v,vy:Math.sin(a)*v,rot:Math.random()*6,vr:(Math.random()-.5)*14,w:4+Math.random()*5,h:6+Math.random()*8,col:cols[i%6],life:1.4+Math.random()*1.3})}
  for(let k=0;k<3;k++)ripples.push({x:B.x,y:B.y+18,r:6+k*16,a:1})}
const _t={};const setT=(id,v)=>{if(_t[id]!==v){_t[id]=v;document.getElementById(id).innerHTML=v}};
function texts(){const pct=st.state=="done"?100:st.total?Math.min(100,st.shown/st.total*100):0,P=esc(st.peer),dots='<span class="dots"><i></i><i></i><i></i></span>';
  setT("pct",String(Math.floor(pct)));setT("pctd",(pct>=100?"":"."+Math.floor(pct*10%10))+"%");
  $("#pfill").style.width=pct+"%";st.srcFill.style.height=(100-pct)+"%";st.dstFill.style.height=pct+"%";
  const n=st.count==1?"1 file":st.count+" files";
  setT("sstatus",st.state=="waiting"?`Waiting for ${P} to accept${dots}`:st.state=="done"?(st.mode=="send"?`Sent to ${P}`:`Received from ${P}`):
    st.state=="fail"?esc(st.msg):(st.mode=="send"?`Sending to ${P}`:`Receiving from ${P}`)+dots);
  setT("stats",st.state=="active"?(st.speed>0?`${fmt(st.speed)}/s · ${fmtT((st.total-st.done)/st.speed)} left · `:"")+`${fmt(st.shown)} of ${fmt(st.total)}`:
    st.state=="done"?`${n} · ${fmt(st.total)} in ${fmtT(st.elapsed)} · ${fmt(st.total/Math.max(st.elapsed,.001))}/s`:`${n} · ${fmt(st.total)}`);
  setT("fileline",st.state=="active"&&st.file?esc(st.file)+(st.count>1?` · ${st.idx} of ${st.count}`:""):"")}
function frame(now){raf=0;if(!st.on)return;const dt=Math.min(.05,(now-(lastFrame||now))/1000);lastFrame=now;
  const w=cv.clientWidth,h=cv.clientHeight,dpr=devicePixelRatio||1;
  if(cv.width!=Math.round(w*dpr)||cv.height!=Math.round(h*dpr)){cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr)}
  cx.setTransform(dpr,0,0,dpr,0,0);cx.clearRect(0,0,w,h);
  const [A,B]=anchors(),C={x:(A.x+B.x)/2,y:Math.max(-10,Math.min(A.y,B.y)-Math.abs(B.x-A.x)*.5)};st.B=B;
  st.shown+=(st.done-st.shown)*Math.min(1,dt*6);
  const active=st.state=="active",fail=st.state=="fail";
  // track
  cx.save();cx.setLineDash([3,9]);cx.lineDashOffset=-now/35;cx.strokeStyle=fail?"rgba(240,68,56,.45)":"rgba(255,255,255,.2)";cx.lineWidth=2;arc(A,C,B);cx.stroke();cx.restore();
  // beam
  const beam=active?.55+.25*Math.sin(now/280):st.state=="done"?Math.max(0,1-(now-st.doneAt)/1400):0;
  if(beam>0){const g=cx.createLinearGradient(A.x,0,B.x,0);g.addColorStop(0,"rgba(91,140,255,.1)");g.addColorStop(.5,"rgba(167,139,250,1)");g.addColorStop(1,"rgba(56,189,248,1)");
    cx.save();cx.globalAlpha=beam;cx.strokeStyle=g;cx.lineWidth=3;cx.shadowColor="rgba(130,140,255,1)";cx.shadowBlur=18;arc(A,C,B);cx.stroke();cx.restore()}
  // waiting ping
  if(st.state=="waiting"){ping=(ping+dt*.55)%2;const t=ease(ping<1?ping:2-ping),p=bez(A,C,B,t),g=cx.createRadialGradient(p.x,p.y,0,p.x,p.y,16);
    g.addColorStop(0,"rgba(191,219,254,1)");g.addColorStop(1,"rgba(96,165,250,0)");cx.fillStyle=g;cx.beginPath();cx.arc(p.x,p.y,16,0,7);cx.fill()}
  // spawn folders + sparks while data flows
  if(active&&!RM){const rate=Math.min(9,1.4+st.speed/4194304);
    if(now-lastSpawn>1000/rate){lastSpawn=now;folders.push({t:0,dur:1050+Math.random()*350,rot:(Math.random()-.5)*.7,off:(Math.random()-.5)*28})}
    for(let i=0;i<3;i++)parts.push({t:0,v:.45+Math.random()*.75,off:(Math.random()-.5)*16,r:.6+Math.random()*1.9,ph:Math.random()*6})}
  cx.save();cx.globalCompositeOperation="lighter";
  parts=parts.filter(p=>(p.t+=dt*p.v)<1);
  for(const p of parts){const q=bez(A,C,B,p.t),n=nrm(A,C,B,p.t),o=p.off*Math.sin(p.t*Math.PI)+Math.sin(now/180+p.ph)*2.5,a=Math.sin(p.t*Math.PI);
    cx.fillStyle=`rgba(150,175,255,${a*.85})`;cx.beginPath();cx.arc(q.x+n.x*o,q.y+n.y*o,p.r,0,7);cx.fill()}
  cx.restore();
  folders=folders.filter(f=>{f.t+=dt*1000/f.dur;if(f.t>=1){ripples.push({x:B.x,y:B.y+16,r:5,a:.9});bump();return false}return true});
  for(const f of folders){const e=ease(f.t),n=nrm(A,C,B,e),o=f.off*Math.sin(e*Math.PI),s=.5+.7*Math.sin(e*Math.PI),al=Math.min(1,f.t*6,(1-f.t)*5);
    for(let k=5;k>=1;k--){const q=bez(A,C,B,ease(Math.max(0,f.t-k*.022)));cx.globalAlpha=al*(.2-k*.033);folder(q.x+n.x*o,q.y+n.y*o,s*.92,f.rot*e,false)}
    const q=bez(A,C,B,e);cx.globalAlpha=al;folder(q.x+n.x*o,q.y+n.y*o,s,f.rot*Math.sin(e*Math.PI*2),true)}
  cx.globalAlpha=1;
  ripples=ripples.filter(r=>(r.r+=dt*95,r.a-=dt*1.5)>0);
  for(const r of ripples){cx.strokeStyle=st.state=="done"?`rgba(52,211,153,${r.a})`:`rgba(130,165,255,${r.a})`;cx.lineWidth=2;cx.beginPath();cx.ellipse(r.x,r.y,r.r*1.7,r.r*.55,0,0,7);cx.stroke()}
  confetti=confetti.filter(c=>(c.life-=dt)>0);
  for(const c of confetti){c.vy+=620*dt;c.vx*=.985;c.x+=c.vx*dt;c.y+=c.vy*dt;c.rot+=c.vr*dt;
    cx.save();cx.translate(c.x,c.y);cx.rotate(c.rot);cx.globalAlpha=Math.min(1,c.life*2);cx.fillStyle=c.col;cx.fillRect(-c.w/2,-c.h/2,c.w,c.h*Math.abs(Math.cos(c.rot*1.7)));cx.restore()}
  // live speed sparkline
  if(active&&now-(st.lastH||0)>200){st.lastH=now;st.hist.push(st.speed);if(st.hist.length>60)st.hist.shift()}
  if(active&&st.hist.length>1){const x0=20,y0=34,W=130,H=30,mx=Math.max(...st.hist,1),X=i=>x0+i/59*W,Y=v=>y0+H-v/mx*H;
    cx.beginPath();st.hist.forEach((v,i)=>i?cx.lineTo(X(i),Y(v)):cx.moveTo(X(i),Y(v)));cx.strokeStyle="rgba(147,197,253,.95)";cx.lineWidth=1.6;cx.stroke();
    cx.lineTo(X(st.hist.length-1),y0+H);cx.lineTo(x0,y0+H);cx.closePath();const g=cx.createLinearGradient(0,y0,0,y0+H);
    g.addColorStop(0,"rgba(99,140,255,.4)");g.addColorStop(1,"rgba(99,140,255,0)");cx.fillStyle=g;cx.fill()}
  texts();raf=requestAnimationFrame(frame)}

/* ---------- receiving ---------- */
const seen=new Set();
function trackBatches(list){for(const b of list){if(seen.has(b.id))continue;
  const shown=st.on&&st.bid===b.id,free=!st.on||st.state=="done"||st.state=="fail";
  if(!shown&&!free)continue;
  if(!shown){if(b.failed){seen.add(b.id);continue}stageOpen({mode:"recv",peer:b.from,count:b.count,total:b.total,state:"active",bid:b.id})}
  stageProg(b.got,b.current,Math.min(b.count,b.received+1));
  if(b.done){seen.add(b.id);stageDone()}else if(b.failed){seen.add(b.id);stageFail(`Transfer from ${b.from} was interrupted`)}
  break}}
const offerEls={};
function drawOffers(list){const ids=new Set(list.map(o=>o.id));
  for(const id in offerEls)if(!ids.has(id)){offerEls[id].remove();delete offerEls[id]}
  for(const o of list){let d=offerEls[o.id];
    if(!d){d=offerEls[o.id]=document.createElement("div");d.className="offer";
      const more=o.count>o.files.length?` and ${o.count-o.files.length} more`:"";
      d.innerHTML=`<div class="in"><div class="av" style="--h:${hue(o.from)}">${PC(26)}</div><div class="txt"><b>${esc(o.from)} wants to send you ${o.count==1?"a file":o.count+" files"}</b>
        <div class="dim">${fmt(o.total)} · ${o.files.map(esc).join(", ")}${more}</div></div>
        <div class="ring"><svg viewBox="0 0 38 38"><circle class="bgc" cx="19" cy="19" r="17"/><circle class="fg" cx="19" cy="19" r="17"/></svg><span></span></div>
        <button class="btn">Decline</button><button class="btn primary">Accept</button></div>`;
      const [no,yes]=d.querySelectorAll("button"),decide=ok=>{d.style.display="none";api(`/api/decide?id=${o.id}&ok=${ok?1:0}`,{method:"POST"})};
      no.onclick=()=>decide(false);yes.onclick=()=>decide(true);$("#offers").append(d);chime("ask")}
    d.querySelector(".ring span").textContent=o.left;d.querySelector(".fg").style.strokeDashoffset=107*(1-o.left/o.ask)}}
function drawFiles(files){const k=files.map(f=>f.name+f.time).join("|");if(k===filesKey)return;filesKey=k;const el=$("#files");
  el.innerHTML=files.length?"":'<div class="row muted">Files other computers send you will appear here.</div>';
  for(const f of files.slice(0,100)){const r=document.createElement("div");r.className="row"+(known&&!known.has(f.name)?" new":"");r.title="Show in folder";
    r.innerHTML=`<span class="ficon" style="--h:${hue(ext(f.name))}">${ext(f.name)}</span><span class="name"></span><span class="meta">${fmt(f.size)} · ${new Date(f.time*1000).toLocaleString([],{dateStyle:"short",timeStyle:"short"})}</span>`;
    r.querySelector(".name").textContent=f.name;r.onclick=()=>api("/api/reveal?name="+encodeURIComponent(f.name),{method:"POST"});el.append(r)}}
$("#folder").onclick=()=>api("/api/reveal",{method:"POST"});
$("#ubtn").onclick=async()=>{const b=$("#ubtn");if(b.dataset.manual)return api("/api/release-page",{method:"POST"});
  b.disabled=true;b.innerHTML='<span class="uspin"></span>Updating…';let r=null;try{r=await api("/api/update",{method:"POST"})}catch(e){}
  if(r&&r.ok){b.innerHTML='<span class="uspin"></span>Restarting…';$("#update .dim").textContent="Transfer will reopen in a moment."}
  else{b.disabled=false;b.dataset.manual=1;b.textContent="Download it";$("#update .dim").textContent=(r&&await r.text())||"Couldn't update automatically."}};
let busy=false;
async function poll(){try{const s=await(await api("/api/state")).json();
  myName=s.name;$("#me").textContent=`${s.name} · ${s.ip}`;$("#ver").textContent=s.version=="dev"?"":s.version;
  if(s.update&&$("#update").hidden){$("#update").hidden=false;$("#utitle").textContent=`Transfer ${s.update} is available`}
  drawOffers(s.offers);trackBatches(s.batches);busy=s.offers.length>0||s.batches.some(b=>!b.done&&!b.failed);
  const k=JSON.stringify(s.peers);if(k!==peerKey){peerKey=k;peers=s.peers;if(document.activeElement?.id!="ip"||peers.length)drawPeers()}
  drawFiles(s.files);const names=s.files.map(f=>f.name);
  if(known)for(const n of names)if(!known.has(n))toast("Received "+n);known=new Set(names)}catch(e){}
  setTimeout(poll,busy?300:1200)}  // refresh faster while something is happening
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


def ver(tag):
    try:
        return tuple(int(x) for x in tag.lstrip("v").split("."))
    except ValueError:
        return ()


def curl(*args, timeout=30):
    # curl ships with macOS and Windows 10+ and uses the system's certificates, unlike a bundled Python
    return subprocess.run(["curl", "-fsSL", *args], capture_output=True, text=True, check=True, timeout=timeout, creationflags=NOWIN).stdout


def check_updates():
    global latest
    while True:
        try:
            tag = curl("-I", "-o", os.devnull, "-w", "%{url_effective}", REPO + "/releases/latest").rsplit("/", 1)[-1]
            if ver(tag) > ver(VERSION):
                latest = tag
        except (OSError, subprocess.SubprocessError):
            pass  # offline; try again later
        time.sleep(6 * 3600)


def app_paths():
    # (what the update replaces, where the replaced copy is parked until next start)
    if sys.platform == "win32":
        exe = Path(sys.executable)
        return exe, exe.with_name("Transfer.old.exe")
    app = Path(sys.executable).parents[2]  # .../Transfer.app/Contents/MacOS/Transfer
    if app.suffix != ".app":
        raise RuntimeError("Transfer isn't running as an app")
    return app, app.with_name("Transfer.old.app")


def self_update():
    # download the latest release, swap it in, start it, and quit this copy
    cur, old = app_paths()
    tmp = Path(tempfile.mkdtemp())
    url = f"{REPO}/releases/download/{latest}/"
    if sys.platform == "win32":
        new = tmp / "Transfer.exe"
        curl("-o", str(new), url + "Transfer.exe", timeout=900)
    else:
        curl("-o", str(tmp / "t.zip"), url + "Transfer-mac.zip", timeout=900)
        subprocess.run(["ditto", "-x", "-k", str(tmp / "t.zip"), str(tmp)], check=True)
        new = tmp / "Transfer.app"
    if old.is_dir():
        shutil.rmtree(old)
    elif old.exists():
        old.unlink()
    cur.rename(old)  # a running app can be renamed (Windows and macOS), just not overwritten
    try:
        shutil.move(str(new), str(cur))
    except Exception:
        old.rename(cur)  # put the working copy back
        raise
    if sys.platform == "win32":
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")  # start fresh, not inside this copy's unpacked files
        subprocess.Popen([str(cur)], env=env, close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        subprocess.Popen(["open", "-n", str(cur)])
    threading.Timer(1.5, os._exit, [0]).start()


def remove_old_copy():
    # the copy replaced by the last update may still be closing, so retry for a bit
    try:
        old = app_paths()[1]
    except RuntimeError:
        return
    for _ in range(15):
        try:
            if old.is_dir():
                shutil.rmtree(old)
            elif old.exists():
                old.unlink()
            return
        except OSError:
            time.sleep(2)


def announce():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        msg = json.dumps({"id": ME, "name": NAME, "port": PORT, "os": OS}).encode()
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
                peers[str(m["id"])[:64]] = {"name": str(m["name"])[:64], "ip": ip, "port": int(m["port"]),
                                            "os": str(m.get("os", ""))[:16], "seen": time.time()}
        except (ValueError, KeyError, TypeError, AttributeError):
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
            live = [{"id": k, "name": v["name"], "ip": v["ip"], "os": v.get("os", "")}
                    for k, v in list(peers.items()) if now - v["seen"] < 7]
            asks = [{"id": k, "from": o["from"], "files": [f[0] for f in o["files"][:4]], "count": len(o["files"]),
                     "total": sum(f[1] for f in o["files"]), "left": max(0, int(ASK_SECS - (now - o["t"]))), "ask": ASK_SECS}
                    for k, o in list(offers.items())]
            for k, b in list(batches.items()):
                if not b["done"] and now - b["seen"] > 30:
                    b["failed"] = True  # sender stopped sending
                if (b["done"] or b["failed"]) and now - b["seen"] > 20:
                    batches.pop(k, None)
            state = {"name": NAME, "ip": lan_ip(), "peers": sorted(live, key=lambda p: p["name"].lower()),
                     "files": files, "offers": asks, "batches": list(batches.values()),
                     "version": VERSION, "update": latest if FROZEN else None}
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
        if path == "/api/update":
            if not (FROZEN and latest):
                return self.reply(400, "No update available")
            try:
                self_update()
            except Exception as e:
                return self.reply(500, f"Couldn't update automatically ({e}). Click to download it instead.")
            return self.reply(200, "Restarting")
        if path == "/api/release-page":
            webbrowser.open(REPO + "/releases/latest")
            return self.reply(200)
        if path == "/api/add":
            try:
                ip = str(ipaddress.ip_address(q.get("ip", "").strip()))
            except ValueError:
                return self.reply(400)
            peers["manual-" + ip] = {"name": ip, "ip": ip, "port": 8000, "os": "", "seen": float("inf")}
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
        offers[oid] = o = {"from": sender, "files": files, "event": event, "ok": False, "t": time.time()}
        bring_to_front()
        event.wait(ASK_SECS)
        offers.pop(oid, None)
        if not o["ok"]:
            return self.reply(403, f"{NAME} declined" if event.is_set() else f"{NAME} didn't answer")
        token, bid = uuid.uuid4().hex, uuid.uuid4().hex
        allowed[token] = {"from": sender, "files": [f[:] for f in files], "batch": bid}
        batches[bid] = {"id": bid, "from": sender, "total": sum(f[1] for f in files), "got": 0, "count": len(files),
                        "received": 0, "current": "", "seen": time.time(), "done": False, "failed": False}
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
        b = batches.get(grant["batch"], {})
        b["current"] = name
        tmp = SHARE / f".{uuid.uuid4().hex}.part"
        try:
            with open(tmp, "wb") as f:
                while left:
                    buf = self.rfile.read(min(CHUNK, left))
                    if not buf:
                        raise ConnectionError("sender disconnected")
                    f.write(buf)
                    left -= len(buf)
                    b["got"] = b.get("got", 0) + len(buf)
                    b["seen"] = time.time()
            tmp.rename(unique(SHARE / name))
        except Exception:
            tmp.unlink(missing_ok=True)
            b["failed"] = True
            raise
        b["received"] = b.get("received", 0) + 1
        b["seen"] = time.time()
        b["done"] = b["received"] >= b.get("count", 0)
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
    if FROZEN and ver(VERSION):  # only release builds update themselves
        for fn in (check_updates, remove_old_copy):
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
    webview.create_window("Transfer", url, width=900, height=780, min_size=(560, 640))
    webview.start()


if __name__ == "__main__":
    main()
