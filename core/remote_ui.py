"""
core/remote_ui.py
Pi Gadget — unified web dashboard.

Routes:
  GET    /                      -> Dashboard SPA
  GET    /next_frame            -> Long-poll frame stream
  POST   /key                   -> Button press
  GET    /api/apps              -> List apps + bgm status
  POST   /api/apps/stop         -> Stop running app       {name}
  POST   /api/apps/launch       -> Enqueue app launch     {module, name}
  GET    /api/files             -> List files             ?path=
  GET    /api/files/download    -> Download file          ?path=
  POST   /api/files/upload      -> Upload file            ?path=  multipart
  DELETE /api/files             -> Delete file            {path}
  GET    /api/system            -> CPU / RAM / temp / uptime
  GET    /api/ips               -> Active interfaces
  GET    /api/settings          -> Read config.json
  POST   /api/settings          -> Write config.json      {key, value}
  GET    /dns/api               -> DNS rules
  POST   /dns/api               -> Update DNS rules

Launch integration with main.py:
  In main loop, call remote.pop_launch_request() each tick.
  Returns {name, module} or None.
  Use importlib to load the module and run it in background via bgm.
"""

import io
import json
import os
import threading
import queue
import time

from flask import Flask, request, jsonify, make_response, send_file
from werkzeug.utils import secure_filename

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE       = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.dirname(_HERE)
MENU_DIR    = os.path.join(BASE_DIR, "menu_fs")
FILES_DIR   = os.path.join(MENU_DIR, "02_files")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


# ── System helpers ─────────────────────────────────────────────────────────────

def _sys_stats() -> dict:
    """Return CPU %, RAM MB, temperature C, uptime seconds."""
    s = {"cpu": 0.0, "ram_used": 0, "ram_total": 0, "temp": 0.0, "uptime": 0}
    try:
        def _times():
            with open("/proc/stat") as f:
                p = f.readline().split()
            v = list(map(int, p[1:]))
            idle = v[3] + (v[4] if len(v) > 4 else 0)
            return idle, sum(v)
        i1, t1 = _times()
        time.sleep(0.15)
        i2, t2 = _times()
        dt = t2 - t1
        s["cpu"] = round(100 * (1 - (i2 - i1) / dt), 1) if dt else 0
    except Exception:
        pass
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k.strip()] = int(v.split()[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        s["ram_total"] = total // 1024
        s["ram_used"]  = (total - avail) // 1024
    except Exception:
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            s["temp"] = round(int(f.read()) / 1000, 1)
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            s["uptime"] = int(float(f.read().split()[0]))
    except Exception:
        pass
    return s


def _fmt_uptime(secs: int) -> str:
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m    = r // 60
    if d:  return f"{d}d {h}h {m}m"
    if h:  return f"{h}h {m}m"
    return f"{m}m"


def _get_ips() -> dict:
    import subprocess
    ips = {}
    for iface in ("wlan0", "eth0", "usb0"):
        try:
            r = subprocess.run(["ip", "-4", "addr", "show", iface],
                               capture_output=True, timeout=3)
            for line in r.stdout.decode().splitlines():
                if line.strip().startswith("inet "):
                    ips[iface] = line.strip().split()[1].split("/")[0]
        except Exception:
            pass
    return ips


def _fmt_size(n: int) -> str:
    if n < 1024:    return f"{n} B"
    if n < 1048576: return f"{n // 1024} KB"
    return f"{n / 1048576:.1f} MB"


# ── Config helpers ─────────────────────────────────────────────────────────────

# Whitelisted config keys visible and editable via WebUI
_CONFIG_WHITELIST = {
    "brightness":     {"label": "Brightness",      "type": "int",    "min": 10,   "max": 100},
    "dim_timeout":    {"label": "Dim Timeout (s)",  "type": "int",    "min": 0,    "max": 600},
    "volume":         {"label": "Volume",           "type": "int",    "min": 0,    "max": 100},
    "wifi_ssid":      {"label": "Wi-Fi SSID",       "type": "string"},
    "hostname":       {"label": "Hostname",         "type": "string"},
    "timezone":       {"label": "Timezone",         "type": "string"},
    "remote_ui_port": {"label": "WebUI Port",       "type": "int",    "min": 1024, "max": 65535},
    "theme":          {"label": "Theme",            "type": "choice", "choices": ["dark", "light"]},
    "show_fps":       {"label": "Show FPS",         "type": "bool"},
    "language":       {"label": "Language",         "type": "string"},
}


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(data: dict):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ── App discovery ──────────────────────────────────────────────────────────────

def _scan_apps() -> list:
    """Recursively scan menu_fs/ for .app files and return parsed list."""
    apps = []
    if not os.path.isdir(MENU_DIR):
        return apps
    for root, dirs, files in os.walk(MENU_DIR):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fname in sorted(files):
            if not fname.endswith(".app"):
                continue
            full = os.path.join(root, fname)
            try:
                with open(full) as f:
                    meta = json.load(f)
                rel = os.path.relpath(root, MENU_DIR).replace("\\", "/")
                apps.append({
                    "name":           meta.get("name", fname[:-4]),
                    "module":         meta.get("module", ""),
                    "category":       rel,
                    "category_label": _category_label(rel),
                    "bg_capable":     bool(meta.get("background", False)),
                    "description":    meta.get("description", ""),
                    "usage":          meta.get("usage", ""),
                })
            except Exception:
                pass
    apps.sort(key=lambda a: (a["category"], a["name"]))
    return apps


def _category_label(cat: str) -> str:
    parts = cat.split("/")
    clean = []
    for p in parts:
        p = p.lstrip("0123456789").lstrip("_")
        clean.append(p.replace("_", " ").title())
    return " / ".join(clean)


# ── File browser ───────────────────────────────────────────────────────────────

def _list_files(subpath: str = "") -> list:
    base   = os.path.realpath(FILES_DIR)
    target = os.path.realpath(os.path.join(base, subpath)) if subpath else base
    if not target.startswith(base):
        return []
    entries = []
    try:
        for name in sorted(os.listdir(target)):
            if name.startswith("."):
                continue
            full = os.path.join(target, name)
            rel  = os.path.relpath(full, base)
            if os.path.isdir(full):
                try:
                    count = sum(1 for x in os.listdir(full) if not x.startswith("."))
                except Exception:
                    count = 0
                entries.append({"type": "dir", "name": name,
                                 "path": rel, "size": f"{count} files", "mtime": 0})
            else:
                try:
                    st = os.stat(full)
                    entries.append({
                        "type":  "file", "name": name, "path": rel,
                        "size":  _fmt_size(st.st_size),
                        "mtime": int(st.st_mtime),
                        "ext":   os.path.splitext(name)[1].lower(),
                    })
                except Exception:
                    pass
    except Exception:
        pass
    return entries


# ── DNS helpers ────────────────────────────────────────────────────────────────

def _dns_rules_path() -> str:
    return os.path.join(FILES_DIR, "dns_spoof", "rules.json")


def _load_dns_rules() -> list:
    try:
        with open(_dns_rules_path()) as f:
            return json.load(f).get("rules", [])
    except Exception:
        return [{"domain": "*", "ip": "", "enabled": False}]


def _save_dns_rules(rules: list):
    try:
        path = _dns_rules_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"rules": rules}, f, indent=2)
    except Exception:
        pass


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Pi Gadget</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700&display=swap');
:root{
  --bg:#080b10;--bg2:#0c1018;--border:#1a2030;--border2:#232d40;
  --accent:#00e5ff;--accent2:#8b5cf6;
  --green:#4ade80;--red:#f87171;--yellow:#fbbf24;
  --btn:#111722;--btn-h:#1a2438;--text:#b0c4d8;--dim:#3a4a5e;--dim2:#2a3548;
  --sidebar-w:188px;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}

html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--text);font-family:'Share Tech Mono',monospace;
  display:flex;flex-direction:row}

/* Sidebar */
.sidebar{
  width:var(--sidebar-w);height:100vh;
  background:var(--bg2);border-right:1px solid var(--border);
  display:flex;flex-direction:column;flex-shrink:0;
  overflow-y:auto;overflow-x:hidden;
}
.sidebar::-webkit-scrollbar{width:3px}
.sidebar::-webkit-scrollbar-thumb{background:var(--border2)}
.logo{padding:15px 14px 11px;border-bottom:1px solid var(--border);flex-shrink:0}
.logo-title{font-family:'Orbitron',sans-serif;font-size:11px;font-weight:700;
  letter-spacing:.18em;color:var(--accent)}
.logo-sub{font-size:9px;color:var(--dim);letter-spacing:.1em;margin-top:3px}
.nav{flex:1;padding:6px 0}
.nav-item{
  display:flex;align-items:center;gap:9px;padding:10px 14px;
  cursor:pointer;font-size:11px;letter-spacing:.05em;color:var(--dim);
  border-left:2px solid transparent;transition:all .12s;user-select:none;white-space:nowrap;
}
.nav-item:hover{color:var(--text);background:rgba(255,255,255,.025)}
.nav-item.active{color:var(--accent);border-left-color:var(--accent);background:rgba(0,229,255,.04)}
.nav-item .icon{font-size:14px;width:20px;text-align:center;flex-shrink:0}
.nav-sep{height:1px;background:var(--border);margin:4px 10px}
.sidebar-foot{padding:10px 14px;border-top:1px solid var(--border);
  font-size:9px;color:var(--dim);letter-spacing:.06em;flex-shrink:0}
.live-dot{display:inline-block;width:6px;height:6px;border-radius:50%;
  background:var(--dim);margin-right:5px;vertical-align:middle;transition:all .3s}
.live-dot.on{background:var(--green);box-shadow:0 0 6px var(--green)}

/* Main column */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0;height:100vh}
.topbar{
  padding:11px 18px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;flex-shrink:0;
}
.page-title{font-family:'Orbitron',sans-serif;font-size:12px;letter-spacing:.14em;color:var(--text)}
.topbar-meta{font-size:10px;color:var(--dim);text-align:right}

/* Scrollable content area */
.content{
  flex:1;overflow-y:auto;overflow-x:hidden;
  padding:16px;scrollbar-gutter:stable;
}
.content::-webkit-scrollbar{width:5px}
.content::-webkit-scrollbar-track{background:rgba(255,255,255,.02)}
.content::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}
.content::-webkit-scrollbar-thumb:hover{background:var(--dim)}

/* Cards */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;
  padding:14px;margin-bottom:14px}
.card-title{font-size:9px;letter-spacing:.18em;color:var(--dim);
  text-transform:uppercase;margin-bottom:12px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
.stat-box{background:var(--btn);border:1px solid var(--border2);border-radius:6px;
  padding:12px 8px;text-align:center}
.stat-val{font-family:'Orbitron',sans-serif;font-size:20px;font-weight:700;
  color:var(--accent);line-height:1}
.stat-lbl{font-size:9px;color:var(--dim);margin-top:5px;letter-spacing:.08em}

/* Tables with horizontal scroll */
.tbl-wrap{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
.tbl-wrap::-webkit-scrollbar{height:3px}
.tbl-wrap::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
table{width:100%;border-collapse:collapse;font-size:11px;min-width:300px}
th{text-align:left;padding:7px 10px;color:var(--dim);font-size:9px;
  letter-spacing:.12em;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--dim2);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.012)}

/* Badges */
.badge{display:inline-block;padding:2px 9px;border-radius:10px;font-size:9px;
  letter-spacing:.1em;border:1px solid;white-space:nowrap}
.badge.green{color:var(--green);border-color:rgba(74,222,128,.35);background:rgba(74,222,128,.07)}
.badge.red{color:var(--red);border-color:rgba(248,113,113,.35);background:rgba(248,113,113,.07)}
.badge.dim{color:var(--dim);border-color:var(--border)}
.badge.cyan{color:var(--accent);border-color:rgba(0,229,255,.35);background:rgba(0,229,255,.07)}

/* Buttons */
.btn{
  display:inline-flex;align-items:center;gap:5px;padding:6px 12px;
  border-radius:5px;font-family:'Share Tech Mono',monospace;font-size:10px;
  cursor:pointer;border:1px solid;transition:all .1s;user-select:none;
  white-space:nowrap;text-decoration:none;
}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-primary{background:rgba(0,229,255,.08);border-color:rgba(0,229,255,.3);color:var(--accent)}
.btn-primary:hover{background:rgba(0,229,255,.15)}
.btn-success{background:rgba(74,222,128,.07);border-color:rgba(74,222,128,.3);color:var(--green)}
.btn-success:hover{background:rgba(74,222,128,.14)}
.btn-danger{background:rgba(248,113,113,.07);border-color:rgba(248,113,113,.3);color:var(--red)}
.btn-danger:hover{background:rgba(248,113,113,.14)}
.btn-dim{background:transparent;border-color:var(--border);color:var(--dim)}
.btn-dim:hover{border-color:var(--border2);color:var(--text)}
.btn-sm{padding:4px 9px;font-size:9px}

/* Inputs */
.inp-group{display:flex;flex-direction:column;gap:4px}
.inp-lbl{font-size:9px;letter-spacing:.12em;color:var(--dim)}
input[type=text],input[type=number],select{
  background:var(--btn);border:1px solid var(--border);border-radius:4px;
  color:var(--text);font-family:'Share Tech Mono',monospace;
  font-size:11px;padding:7px 10px;width:100%;outline:none;
}
input[type=text]:focus,input[type=number]:focus,select:focus{border-color:rgba(0,229,255,.35)}
input::placeholder{color:var(--dim)}
select option{background:var(--bg2)}

/* ── REMOTE TAB ── */
/* Screen on top, controls below, centered column */
.remote-layout{
  display:flex;flex-direction:column;align-items:center;gap:14px;
}
.screen-frame{
  position:relative;border:1px solid var(--border);border-radius:6px;overflow:hidden;
  flex-shrink:0;box-shadow:0 0 0 1px rgba(0,229,255,.06),0 0 24px rgba(0,229,255,.04);
}
.screen-frame::after{
  content:'';position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,
    rgba(0,0,0,.06) 2px,rgba(0,0,0,.06) 4px);
}
#screen{display:block;width:240px;height:240px;image-rendering:pixelated}
#conn-status{font-size:10px;color:var(--dim);text-align:center}
#conn-status.ok{color:var(--accent)} #conn-status.err{color:var(--red)}

/* Controls block */
.ctrl-area{width:100%;max-width:340px;display:flex;flex-direction:column;gap:10px}
.ctrl-lbl{font-size:9px;letter-spacing:.2em;color:var(--dim);text-align:center}
.ctrl-row{display:flex;gap:8px;justify-content:center}

.key-btn{
  flex:1;max-width:100px;padding:10px 4px 8px;
  background:var(--btn);border:1px solid var(--border);border-radius:6px;
  color:var(--text);font-family:'Share Tech Mono',monospace;font-size:9px;
  cursor:pointer;text-align:center;user-select:none;transition:all .08s;
}
.key-btn .k{font-family:'Orbitron',sans-serif;font-size:7px;letter-spacing:.1em;
  color:var(--dim);display:block;margin-bottom:3px}
.key-btn:hover,.jb:hover{background:var(--btn-h);border-color:rgba(0,229,255,.2)}
.key-btn.active,.jb.active{
  background:rgba(0,229,255,.07);border-color:var(--accent);color:var(--accent);
  box-shadow:0 0 8px rgba(0,229,255,.1);transform:scale(.93);
}
.joy{
  display:grid;grid-template-columns:repeat(3,62px);
  grid-template-rows:repeat(3,54px);gap:5px;
}
.jb{
  width:62px;height:54px;background:var(--btn);border:1px solid var(--border);
  border-radius:6px;color:var(--text);font-size:20px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  user-select:none;transition:all .08s;
}
.jb.center{
  background:rgba(139,92,246,.08);border-color:rgba(139,92,246,.2);
  color:var(--accent2);font-size:11px;font-family:'Orbitron',sans-serif;letter-spacing:.05em;
}
.jb.center.active{border-color:var(--accent2);background:rgba(139,92,246,.15)}
.je{visibility:hidden}

/* ── FILES TAB ── */
.breadcrumb{display:flex;align-items:center;gap:5px;font-size:11px;
  color:var(--dim);margin-bottom:12px;flex-wrap:wrap}
.crumb{cursor:pointer;transition:color .1s}
.crumb:hover{color:var(--accent)}
.bc-sep{color:var(--dim2)}
.upload-zone{
  border:2px dashed var(--border);border-radius:8px;padding:20px;
  text-align:center;font-size:11px;color:var(--dim);cursor:pointer;
  transition:all .2s;margin-bottom:12px;
}
.upload-zone:hover,.upload-zone.drag{
  border-color:rgba(0,229,255,.5);color:var(--accent);background:rgba(0,229,255,.03);
}
.upload-zone input[type=file]{display:none}
.up-prog{display:none;height:3px;background:var(--border);border-radius:2px;
  margin-top:8px;overflow:hidden}
.up-bar{height:100%;background:var(--accent);width:0%;
  transition:width .2s;border-radius:2px}

/* ── DNS TAB ── */
.inp-row{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;
  padding:14px;background:rgba(255,255,255,.015);
  border:1px solid var(--border);border-radius:6px;margin-top:12px}
.toggle-badge{cursor:pointer;user-select:none}
.hint-box{font-size:10px;color:var(--dim);line-height:1.7;
  padding:10px 12px;border:1px solid var(--border);border-radius:6px;margin-top:10px}
.hint-box b{color:var(--yellow)}

/* ── SETTINGS TAB ── */
.setting-row{
  display:flex;align-items:center;justify-content:space-between;
  padding:10px 0;border-bottom:1px solid var(--dim2);gap:12px;flex-wrap:wrap;
}
.setting-row:last-child{border-bottom:none}
.setting-lbl{font-size:11px;color:var(--text);min-width:130px}
.setting-lbl small{display:block;font-size:9px;color:var(--dim);margin-top:2px}
.setting-val{display:flex;align-items:center;gap:8px;flex:1;justify-content:flex-end;flex-wrap:wrap}
.setting-val input,.setting-val select{max-width:180px}
.setting-saved{color:var(--green);font-size:9px;opacity:0;transition:opacity .3s;white-space:nowrap}
.setting-saved.show{opacity:1}

/* ── TOAST ── */
.toast{
  position:fixed;bottom:18px;left:50%;transform:translateX(-50%);
  background:#1a2438;border:1px solid rgba(0,229,255,.3);border-radius:6px;
  padding:8px 18px;font-size:11px;color:var(--accent);
  opacity:0;transition:opacity .2s;pointer-events:none;z-index:9999;white-space:nowrap;
}
.toast.show{opacity:1}
.empty{color:var(--dim);font-size:11px;padding:20px;text-align:center}

/* ── MOBILE (<=600px) ── */
@media(max-width:600px){
  :root{--sidebar-w:46px}
  .nav-item .label,.logo-title,.logo-sub,.sidebar-foot{display:none}
  .nav-item{padding:12px;justify-content:center}
  .nav-item .icon{width:auto}
  .topbar-meta{display:none}
  .grid-3{grid-template-columns:1fr 1fr}
  .content{padding:10px}
  .joy{grid-template-columns:repeat(3,56px);grid-template-rows:repeat(3,50px);gap:4px}
  .jb{width:56px;height:50px}
  .key-btn{max-width:80px}
}
</style>
</head>
<body>

<!-- Sidebar -->
<nav class="sidebar">
  <div class="logo">
    <div class="logo-title">Pi Gadget</div>
    <div class="logo-sub">Dashboard</div>
  </div>
  <div class="nav" id="nav">
    <div class="nav-item active" data-tab="remote">
      <span class="icon">📺</span><span class="label">Remote</span>
    </div>
    <div class="nav-sep"></div>
    <div class="nav-item" data-tab="apps">
      <span class="icon">🎯</span><span class="label">Apps</span>
    </div>
    <div class="nav-item" data-tab="files">
      <span class="icon">📁</span><span class="label">Files</span>
    </div>
    <div class="nav-sep"></div>
    <div class="nav-item" data-tab="dns">
      <span class="icon">⚡</span><span class="label">DNS Rules</span>
    </div>
    <div class="nav-sep"></div>
    <div class="nav-item" data-tab="system">
      <span class="icon">⚙️</span><span class="label">System</span>
    </div>
    <div class="nav-item" data-tab="settings">
      <span class="icon">🔧</span><span class="label">Settings</span>
    </div>
  </div>
  <div class="sidebar-foot">
    <span class="live-dot" id="live-dot"></span>
    <span id="live-lbl">connecting</span>
  </div>
</nav>

<!-- Main -->
<div class="main">
  <div class="topbar">
    <div class="page-title" id="page-title">Remote</div>
    <div class="topbar-meta" id="topbar-meta"></div>
  </div>
  <div class="content" id="content"><div class="empty">Loading...</div></div>
</div>

<div id="toast" class="toast"></div>

<script>
/* ── State ──────────────────────────────────────── */
let activeTab = 'remote';
let frameId   = -1;
let frameOn   = false;
let sysTimer  = null;
let dnsRules  = [];
let filePath  = '';

const TITLES = {
  remote:'Remote', apps:'Apps', files:'Files',
  dns:'DNS Rules', system:'System', settings:'Settings'
};

function esc(s){
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Toast ──────────────────────────────────────── */
function toast(msg, err=false){
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.borderColor = err ? 'rgba(248,113,113,.4)' : 'rgba(0,229,255,.3)';
  t.style.color = err ? '#f87171' : 'var(--accent)';
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(()=>t.classList.remove('show'), 2400);
}

/* ── Navigation ─────────────────────────────────── */
document.getElementById('nav').addEventListener('click', e=>{
  const item = e.target.closest('[data-tab]');
  if (item) switchTab(item.dataset.tab);
});

function switchTab(tab){
  activeTab = tab;
  frameOn   = (tab === 'remote');
  clearInterval(sysTimer); sysTimer = null;
  document.querySelectorAll('.nav-item').forEach(el=>
    el.classList.toggle('active', el.dataset.tab===tab));
  document.getElementById('page-title').textContent = TITLES[tab]||tab;
  document.getElementById('topbar-meta').textContent = '';
  document.getElementById('content').innerHTML = '<div class="empty">Loading...</div>';
  if (tab==='remote')   renderRemote();
  if (tab==='apps')     loadApps();
  if (tab==='files')    loadFiles('');
  if (tab==='dns')      loadDns();
  if (tab==='system')   loadSystem();
  if (tab==='settings') loadSettings();
}

/* ════════════════════════════════════════════════
   REMOTE
════════════════════════════════════════════════ */
function renderRemote(){
  document.getElementById('content').innerHTML = `
  <div class="remote-layout">
    <div class="screen-frame">
      <img id="screen" width="240" height="240" alt="Pi display">
    </div>
    <div id="conn-status">connecting...</div>
    <div class="ctrl-area">
      <div class="ctrl-lbl">Keys</div>
      <div class="ctrl-row">
        <button class="key-btn" data-key="KEY1"><span class="k">K1</span></button>
        <button class="key-btn" data-key="KEY2"><span class="k">K2</span></button>
        <button class="key-btn" data-key="KEY3"><span class="k">K3</span></button>
      </div>
      <div class="ctrl-lbl" style="margin-top:6px">Joystick</div>
      <div style="display:flex;justify-content:center">
        <div class="joy">
          <div class="je"></div>
          <div class="jb" data-key="UP">↑</div>
          <div class="je"></div>
          <div class="jb" data-key="LEFT">←</div>
          <div class="jb center" data-key="CENTER">OK</div>
          <div class="jb" data-key="RIGHT">→</div>
          <div class="je"></div>
          <div class="jb" data-key="DOWN">↓</div>
          <div class="je"></div>
        </div>
      </div>
    </div>
  </div>`;

  frameOn = true; frameId = -1;
  fetchFrame();

  document.querySelectorAll('[data-key]').forEach(el=>{
    el.addEventListener('mousedown',  ()=>{ el.classList.add('active'); sendKey(el.dataset.key); });
    el.addEventListener('mouseup',    ()=>  el.classList.remove('active'));
    el.addEventListener('mouseleave', ()=>  el.classList.remove('active'));
    el.addEventListener('touchstart', e=>{ e.preventDefault(); el.classList.add('active'); sendKey(el.dataset.key); },{passive:false});
    el.addEventListener('touchend',   e=>{ e.preventDefault(); el.classList.remove('active'); },{passive:false});
  });
}

async function fetchFrame(){
  if (!frameOn) return;
  const screen = document.getElementById('screen');
  const status = document.getElementById('conn-status');
  try {
    const res = await fetch('/next_frame?last_id='+frameId);
    if (!res.ok) throw new Error('bad');
    const blob = await res.blob();
    const nid  = parseInt(res.headers.get('X-Frame-Id')||'-1');
    const url  = URL.createObjectURL(blob);
    const old  = screen.src;
    screen.src = url;
    screen.onload = ()=>{ if(old.startsWith('blob:')) URL.revokeObjectURL(old); };
    frameId = nid;
    if(status){ status.textContent='live'; status.className='ok'; }
    document.getElementById('live-dot').className='live-dot on';
    document.getElementById('live-lbl').textContent='live';
  } catch(e){
    if(status){ status.textContent='reconnecting...'; status.className='err'; }
    await new Promise(r=>setTimeout(r,700));
  }
  if (frameOn) fetchFrame();
}

function sendKey(key){
  fetch('/key',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key})}).catch(()=>{});
}

/* ════════════════════════════════════════════════
   APPS
════════════════════════════════════════════════ */
async function loadApps(){
  const c = document.getElementById('content');
  try {
    const r = await fetch('/api/apps');
    const d = await r.json();
    const apps   = d.apps   || [];
    const active = d.active || [];
    if (!apps.length){ c.innerHTML='<div class="empty">No apps found</div>'; return; }

    let html = '';

    if (active.length){
      html += `<div class="card" style="border-color:rgba(74,222,128,.25)">
        <div class="card-title" style="color:var(--green)">● Running Background Tasks</div>
        <div style="display:flex;flex-wrap:wrap;gap:4px">
          ${active.map(a=>`<span class="badge green">${esc(a.name)}</span>`).join('')}
        </div></div>`;
    }

    // Group by category label
    const cats = {};
    apps.forEach(a=>{
      if (!cats[a.category_label]) cats[a.category_label]=[];
      cats[a.category_label].push(a);
    });

    for (const [cat, list] of Object.entries(cats)){
      const rows = list.map(app=>{
        const run   = active.find(a=>a.name===app.name);
        const appId = 'app-' + app.module.replace(/\./g,'-');

        // Status badge
        let badge = '';
        if (run) {
          badge = `<span class="badge green">● BG ${_fmtUp(run.uptime)}</span>`;
        } else if (app.bg_capable) {
          badge = `<span class="badge dim" title="Supports background mode">bg</span>`;
        }

        // Expandable info panel
        const hasInfo = app.description || app.usage;
        const usageLines = app.usage
          ? app.usage.split('\n').map(l=>`<div>${esc(l)}</div>`).join('')
          : '';
        const infoPanel = hasInfo ? `
          <tr id="${appId}-info" style="display:none">
            <td colspan="3" style="padding:0 10px 14px 10px;background:rgba(251,191,36,.03);border-bottom:1px solid var(--border2)">
              ${app.description ? `<div style="color:var(--text);font-size:11px;margin-bottom:8px;line-height:1.6">${esc(app.description)}</div>` : ''}
              ${app.usage ? `<div style="color:var(--dim);font-size:10px;border-top:1px solid var(--border2);padding-top:8px;line-height:1.8">${usageLines}</div>` : ''}
            </td>
          </tr>` : '';

        const infoBtn = hasInfo
          ? `<button id="${appId}-infobtn" class="btn btn-sm"
               onclick="event.stopPropagation();toggleInfo('${appId}')"
               style="margin-right:4px;background:rgba(251,191,36,.08);border-color:rgba(251,191,36,.35);color:#fbbf24">ℹ Info</button>`
          : '';

        // Actions
        let actions = '';
        if (!app.module) {
          actions = `<span style="color:var(--dim2);font-size:9px">no module</span>`;
        } else {
          if (run) {
            actions += `<button class="btn btn-danger btn-sm"
              onclick="event.stopPropagation();stopApp('${esc(app.name)}')" style="margin-right:4px">■ Stop</button>`;
          }
          actions += infoBtn;
          actions += `<button class="btn btn-primary btn-sm"
            onclick="event.stopPropagation();launchApp('${esc(app.name)}','${esc(app.module)}')">▶ Launch</button>`;
        }

        return `<tr>
          <td>
            <div style="color:var(--text)">${esc(app.name)}</div>
            <div style="font-size:9px;color:var(--dim);margin-top:1px">${esc(app.module)}</div>
          </td>
          <td>${badge}</td>
          <td style="white-space:nowrap;text-align:right">${actions}</td>
        </tr>${infoPanel}`;
      }).join('');

      html += `<div class="card">
        <div class="card-title">${esc(cat)}</div>
        <div class="tbl-wrap"><table>
          <thead><tr><th>APP</th><th>STATUS</th><th style="width:160px;text-align:right">ACTIONS</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div></div>`;
    }

    c.innerHTML = html;
    document.getElementById('topbar-meta').textContent =
      `${apps.length} apps · ${active.length} running`;
  } catch(e){
    c.innerHTML='<div class="empty">Failed to load apps</div>';
  }
}

function toggleInfo(id){
  const row = document.getElementById(id+'-info');
  const btn = document.getElementById(id+'-infobtn');
  if (!row) return;
  const open = row.style.display !== 'none';
  row.style.display = open ? 'none' : 'table-row';
  if (btn) btn.textContent = open ? 'ℹ Info' : '✕ Close';
}

function _fmtUp(s){
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;
  if(h) return `${h}h ${m}m`;
  if(m) return `${m}m ${sec}s`;
  return `${sec}s`;
}
async function stopApp(name){
  if (!confirm(`Stop "${name}"?`)) return;
  try {
    const r = await fetch('/api/apps/stop',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
    const d = await r.json();
    if(d.ok){ toast(`Stopped: ${name}`); loadApps(); }
    else toast(d.error||'Error',true);
  } catch(e){ toast('Failed',true); }
}

async function launchApp(name, module){
  try {
    const r = await fetch('/api/apps/launch',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name, module})});
    const d = await r.json();
    if(d.ok){ toast(`Opening on device: ${name}`); setTimeout(loadApps,1200); }
    else toast(d.error||'Error',true);
  } catch(e){ toast('Failed',true); }
}

/* ════════════════════════════════════════════════
   FILES
════════════════════════════════════════════════ */
async function loadFiles(path){
  filePath = path;
  const c = document.getElementById('content');
  try {
    const r = await fetch('/api/files?path='+encodeURIComponent(path));
    const d = await r.json();
    const entries = d.entries || [];

    // Breadcrumb
    const parts = path ? path.split('/') : [];
    let bc = `<div class="breadcrumb">
      <span class="crumb" onclick="loadFiles('')">📁 files</span>`;
    let built='';
    parts.forEach(p=>{
      built += (built?'/':'')+p;
      const snap=built;
      bc += `<span class="bc-sep">/</span>
             <span class="crumb" onclick="loadFiles('${esc(snap)}')">${esc(p)}</span>`;
    });
    bc += '</div>';

    // Upload zone (always visible)
    const upZone = `
    <div class="upload-zone" id="up-zone"
      ondragover="event.preventDefault();this.classList.add('drag')"
      ondragleave="this.classList.remove('drag')"
      ondrop="handleDrop(event)"
      onclick="document.getElementById('file-pick').click()">
      📤 Drop files here or tap to upload
      <div style="font-size:9px;margin-top:3px;color:inherit">Saves to current folder</div>
      <div class="up-prog" id="up-prog"><div class="up-bar" id="up-bar"></div></div>
      <input type="file" id="file-pick" multiple onchange="handleFilePick(this.files)">
    </div>`;

    if (!entries.length){
      c.innerHTML = bc + upZone + '<div class="empty">Empty folder</div>'; return;
    }

    const rows = entries.map(e=>{
      if (e.type==='dir'){
        return `<tr>
          <td style="font-size:15px;width:26px">📂</td>
          <td><span class="crumb" onclick="loadFiles('${esc(e.path)}')"
            style="color:var(--accent)">${esc(e.name)}</span></td>
          <td style="color:var(--dim);font-size:10px">${esc(e.size)}</td>
          <td></td><td></td></tr>`;
      }
      const icon = {'.pcap':'🕵️','.pcapng':'🕵️','.log':'📝','.json':'📋','.txt':'📄'}[e.ext]||'📄';
      const date = e.mtime ? new Date(e.mtime*1000).toLocaleDateString('en-GB',
        {day:'2-digit',month:'short'}) : '';
      return `<tr>
        <td style="font-size:13px;width:26px">${icon}</td>
        <td style="color:var(--text);word-break:break-all">${esc(e.name)}</td>
        <td style="color:var(--dim);font-size:10px;white-space:nowrap">${esc(e.size)}</td>
        <td style="color:var(--dim);font-size:10px;white-space:nowrap">${date}</td>
        <td style="white-space:nowrap">
          <a class="btn btn-dim btn-sm"
            href="/api/files/download?path=${encodeURIComponent(e.path)}"
            download="${esc(e.name)}">↓</a>
          <button class="btn btn-danger btn-sm" style="margin-left:4px"
            onclick="delFile('${esc(e.path)}','${esc(e.name)}')">×</button>
        </td></tr>`;
    }).join('');

    c.innerHTML = bc + upZone + `<div class="card"><div class="tbl-wrap"><table>
      <thead><tr><th></th><th>NAME</th><th>SIZE</th><th>DATE</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div></div>`;

    const fc = entries.filter(e=>e.type==='file').length;
    document.getElementById('topbar-meta').textContent = `${fc} files`;
  } catch(e){
    c.innerHTML='<div class="empty">Failed to load files</div>';
  }
}

async function delFile(path, name){
  if (!confirm(`Delete "${name}"?`)) return;
  try {
    const r = await fetch('/api/files',{method:'DELETE',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
    const d = await r.json();
    if(d.ok){ toast(`Deleted: ${name}`); loadFiles(filePath); }
    else toast(d.error||'Error',true);
  } catch(e){ toast('Failed',true); }
}

function handleDrop(e){
  e.preventDefault();
  document.getElementById('up-zone').classList.remove('drag');
  uploadFiles(e.dataTransfer.files);
}
function handleFilePick(files){ uploadFiles(files); }

async function uploadFiles(files){
  if (!files.length) return;
  const prog = document.getElementById('up-prog');
  const bar  = document.getElementById('up-bar');
  prog.style.display='block';
  for (let i=0; i<files.length; i++){
    bar.style.width = Math.round((i/files.length)*100)+'%';
    const fd = new FormData();
    fd.append('file', files[i]);
    try {
      const r = await fetch('/api/files/upload?path='+encodeURIComponent(filePath),
        {method:'POST',body:fd});
      const d = await r.json();
      if(!d.ok) toast(`Failed: ${files[i].name}`,true);
    } catch(e){ toast(`Error: ${files[i].name}`,true); }
  }
  bar.style.width='100%';
  setTimeout(()=>{
    prog.style.display='none'; bar.style.width='0%';
    toast(`Uploaded ${files.length} file(s) ✓`);
    loadFiles(filePath);
  }, 400);
}

/* ════════════════════════════════════════════════
   DNS RULES
════════════════════════════════════════════════ */
async function loadDns(){
  const c = document.getElementById('content');
  try {
    const r = await fetch('/dns/api');
    const d = await r.json();
    dnsRules = d.rules||[];
    renderDns(d);
  } catch(e){ c.innerHTML='<div class="empty">Failed</div>'; }
}

function renderDns(d){
  const c=document.getElementById('content');
  const col = d.running?'var(--green)':'var(--dim)';
  const txt = d.running
    ? `● Running — victim: ${esc(d.victim_ip||'?')} — queries: ${d.total_queries}`
    : '○ Stopped — start DNS Spoofer on device first';

  const rows = dnsRules.length
    ? dnsRules.map((r,i)=>`<tr>
        <td style="color:var(--text)">${esc(r.domain)}</td>
        <td style="color:var(--dim)">→</td>
        <td style="color:var(--accent)">${esc(r.ip||'(Pi IP)')}</td>
        <td><span class="badge toggle-badge ${r.enabled?'green':'dim'}"
          onclick="dnsToggle(${i})">${r.enabled?'ON':'OFF'}</span></td>
        <td><button class="btn btn-danger btn-sm" onclick="dnsDel(${i})">×</button></td>
      </tr>`).join('')
    : `<tr><td colspan="5" class="empty">No rules yet</td></tr>`;

  c.innerHTML=`
  <div class="card" style="border-color:${d.running?'rgba(74,222,128,.2)':'var(--border)'}">
    <div class="card-title">Status</div>
    <div style="font-size:11px;color:${col}">${txt}</div>
  </div>
  <div class="card">
    <div class="card-title">Rules — first match wins</div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>DOMAIN</th><th></th><th>REDIRECT TO</th><th>STATE</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="inp-row">
      <div class="inp-group" style="flex:1;min-width:120px">
        <div class="inp-lbl">DOMAIN</div>
        <input type="text" id="dns-domain" placeholder="* or google.com">
      </div>
      <div class="inp-group" style="flex:1;max-width:160px">
        <div class="inp-lbl">REDIRECT IP (blank = Pi)</div>
        <input type="text" id="dns-ip" placeholder="leave blank">
      </div>
      <button class="btn btn-primary" onclick="dnsAdd()" style="align-self:flex-end">+ Add</button>
    </div>
  </div>
  <div class="hint-box">
    <b>*</b> catch-all &nbsp;·&nbsp;
    <b>google.com</b> exact + subdomains &nbsp;·&nbsp;
    <b>*.google.com</b> subdomains only
  </div>`;

  document.getElementById('topbar-meta').textContent =
    `${dnsRules.length} rules · ${dnsRules.filter(r=>r.enabled).length} active`;
}

async function dnsSave(){
  try{
    const r=await fetch('/dns/api',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({rules:dnsRules})});
    const d=await r.json();
    if(d.ok) toast(d.applied_live?'Saved & applied ✓':'Saved ✓');
    else toast(d.error||'Error',true);
  }catch(e){ toast('Failed',true); }
}

function dnsToggle(i){
  dnsRules[i].enabled=!dnsRules[i].enabled; dnsSave();
  renderDns({running:false,rules:dnsRules,victim_ip:'',total_queries:0});
}
function dnsDel(i){ dnsRules.splice(i,1); dnsSave();
  renderDns({running:false,rules:dnsRules,victim_ip:'',total_queries:0}); }
async function dnsAdd(){
  const domain=document.getElementById('dns-domain').value.trim();
  const ip=document.getElementById('dns-ip').value.trim();
  if(!domain){ toast('Enter a domain',true); return; }
  dnsRules.push({domain,ip,enabled:true});
  document.getElementById('dns-domain').value='';
  document.getElementById('dns-ip').value='';
  await dnsSave(); loadDns();
}

/* ════════════════════════════════════════════════
   SYSTEM
════════════════════════════════════════════════ */
async function loadSystem(){
  await refreshSystem();
  sysTimer=setInterval(()=>{ if(activeTab==='system') refreshSystem(); },3000);
}

async function refreshSystem(){
  const c=document.getElementById('content');
  try {
    const [sysR,ipsR]=await Promise.all([fetch('/api/system'),fetch('/api/ips')]);
    const sys=await sysR.json(); const ips=await ipsR.json();
    const rp   = sys.ram_total?Math.round(sys.ram_used/sys.ram_total*100):0;
    const tCol = sys.temp>70?'var(--red)':sys.temp>55?'var(--yellow)':'var(--green)';
    const cCol = sys.cpu>85?'var(--red)':sys.cpu>60?'var(--yellow)':'var(--accent)';
    const ipRows=Object.entries(ips.ips||{}).map(([iface,ip])=>`<tr>
      <td style="color:var(--dim)">${esc(iface)}</td>
      <td><span class="badge cyan">${esc(ip)}</span>
        <button class="btn btn-dim btn-sm" style="margin-left:8px"
          onclick="navigator.clipboard.writeText('${esc(ip)}').then(()=>toast('Copied!'))">
          copy</button></td></tr>`).join('')||
      `<tr><td colspan="2" class="empty">No interfaces</td></tr>`;

    c.innerHTML=`
    <div class="grid-3">
      <div class="stat-box"><div class="stat-val" style="color:${cCol}">${sys.cpu}%</div>
        <div class="stat-lbl">CPU</div></div>
      <div class="stat-box"><div class="stat-val">${rp}%</div>
        <div class="stat-lbl">${sys.ram_used}/${sys.ram_total} MB</div></div>
      <div class="stat-box"><div class="stat-val" style="color:${tCol}">${sys.temp}°</div>
        <div class="stat-lbl">Temp °C</div></div>
    </div>
    <div class="card"><div class="card-title">Network</div>
      <div class="tbl-wrap"><table><tbody>${ipRows}</tbody></table></div></div>
    <div class="card"><div class="card-title">Device</div>
      <div class="tbl-wrap"><table><tbody>
        <tr><td style="color:var(--dim)">Uptime</td><td>${esc(sys.uptime_str)}</td></tr>
        <tr><td style="color:var(--dim)">RAM</td><td>${sys.ram_used} MB / ${sys.ram_total} MB</td></tr>
        <tr><td style="color:var(--dim)">Temp</td><td style="color:${tCol}">${sys.temp} C</td></tr>
      </tbody></table></div></div>`;

    document.getElementById('topbar-meta').textContent=
      `CPU ${sys.cpu}% · ${sys.temp}°C · up ${sys.uptime_str}`;
  }catch(e){
    if(c.innerHTML.includes('Loading')) c.innerHTML='<div class="empty">Failed</div>';
  }
}

/* ════════════════════════════════════════════════
   SETTINGS
════════════════════════════════════════════════ */
async function loadSettings(){
  const c=document.getElementById('content');
  try {
    const r=await fetch('/api/settings');
    const d=await r.json();
    renderSettings(d);
  }catch(e){ c.innerHTML='<div class="empty">Failed to load settings</div>'; }
}

function renderSettings(d){
  const c=document.getElementById('content');
  const cfg=d.config||{}; const meta=d.meta||{}; const known=d.known||[];

  let knownRows='';
  known.forEach(key=>{
    const m=meta[key]||{}; const val=cfg[key];
    if(val===undefined) return;
    const lbl=m.label||key; const type=m.type||'string';
    const savedEl=`<span class="setting-saved" id="sv-${esc(key)}">✓</span>`;
    let inp='';
    if(type==='bool'){
      inp=`<label style="display:flex;align-items:center;gap:8px;cursor:pointer">
        <input type="checkbox" ${val?'checked':''} style="width:auto;accent-color:var(--accent)"
          onchange="saveSetting('${esc(key)}',this.checked)">
        <span style="font-size:11px;color:var(--text)">${val?'On':'Off'}</span></label>`;
    } else if(type==='choice'){
      const opts=(m.choices||[]).map(ch=>`<option ${ch===val?'selected':''}>${esc(ch)}</option>`).join('');
      inp=`<select style="max-width:150px" onchange="saveSetting('${esc(key)}',this.value)">${opts}</select>`;
    } else if(type==='int'){
      inp=`<input type="number" value="${esc(val)}" style="max-width:90px"
        min="${m.min||0}" max="${m.max||9999}"
        onchange="saveSetting('${esc(key)}',parseInt(this.value))">`;
    } else {
      inp=`<input type="text" value="${esc(val)}" style="max-width:180px"
        onchange="saveSetting('${esc(key)}',this.value)">`;
    }
    knownRows+=`<div class="setting-row">
      <div class="setting-lbl">${esc(lbl)}<small>${esc(key)}</small></div>
      <div class="setting-val">${inp} ${savedEl}</div></div>`;
  });

  let otherRows='';
  Object.entries(cfg).forEach(([k,v])=>{
    if(known.includes(k)||typeof v==='object') return;
    otherRows+=`<div class="setting-row">
      <div class="setting-lbl">${esc(k)}<small style="color:var(--dim)">${typeof v}</small></div>
      <div class="setting-val">
        <input type="text" value="${esc(String(v))}" style="max-width:180px"
          onchange="saveSetting('${esc(k)}',this.value)">
        <span class="setting-saved" id="sv-${esc(k)}">✓</span>
      </div></div>`;
  });

  c.innerHTML=`
  <div class="card">
    <div class="card-title">Device Settings</div>
    ${knownRows||'<div class="empty" style="padding:10px">No known keys in config</div>'}
  </div>
  ${otherRows?`<div class="card"><div class="card-title">All Config Keys</div>${otherRows}</div>`:''}
  <div class="hint-box">
    <b>Note:</b> Saved instantly to config.json.
    Some settings require restart to apply.
  </div>`;
}

async function saveSetting(key,value){
  try{
    const r=await fetch('/api/settings',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({key,value})});
    const d=await r.json();
    if(d.ok){
      const el=document.getElementById('sv-'+key);
      if(el){ el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),1800); }
    } else toast(d.error||'Error',true);
  }catch(e){ toast('Save failed',true); }
}

/* ── Boot ─────────────────────────────────────── */
switchTab('remote');
</script>
</body>
</html>"""


# ── RemoteUI class ─────────────────────────────────────────────────────────────

class RemoteUI:
    def __init__(self, button_queue: queue.Queue, host='0.0.0.0', port=5000):
        self.button_queue = button_queue
        self.host = host
        self.port = port

        self._lock        = threading.Lock()
        self._frame_data: bytes = b''
        self._frame_id: int     = 0
        self._frame_event       = threading.Event()

        self._started = False
        self._stopped = False

        # Launch queue — main.py polls via pop_launch_request()
        self._launch_queue: queue.Queue = queue.Queue()

        self._app = Flask(__name__)
        self._setup_routes()

    def pop_launch_request(self):
        """
        Return next pending launch request as {name, module} or None.
        Call this from the main loop each tick.
        Use importlib.import_module(module) to load and launch the app.
        """
        try:
            return self._launch_queue.get_nowait()
        except queue.Empty:
            return None

    def _setup_routes(self):
        app = self._app

        @app.route('/')
        def index():
            return DASHBOARD_HTML

        # Frame long-poll
        @app.route('/next_frame')
        def next_frame():
            if self._stopped:
                return make_response('paused', 503)
            try:
                last_id = int(request.args.get('last_id', -1))
            except (ValueError, TypeError):
                last_id = -1
            timeout  = 5.0
            deadline = time.time() + timeout
            while True:
                if self._stopped:
                    return make_response('paused', 503)
                with self._lock:
                    fid  = self._frame_id
                    data = self._frame_data
                if fid > last_id and data:
                    resp = make_response(data)
                    resp.headers.update({'Content-Type': 'image/jpeg',
                                         'Cache-Control': 'no-store',
                                         'X-Frame-Id': str(fid)})
                    return resp
                remaining = deadline - time.time()
                if remaining <= 0:
                    with self._lock:
                        data = self._frame_data
                        fid  = self._frame_id
                    if data:
                        resp = make_response(data)
                        resp.headers.update({'Content-Type': 'image/jpeg',
                                             'Cache-Control': 'no-store',
                                             'X-Frame-Id': str(fid)})
                        return resp
                    time.sleep(0.1)
                    continue
                self._frame_event.wait(timeout=min(remaining, 0.1))
                self._frame_event.clear()

        # Key input
        @app.route('/key', methods=['POST'])
        def key():
            if self._stopped:
                return make_response(jsonify({'ok': False, 'reason': 'paused'}), 503)
            data = request.get_json(force=True) or {}
            k = data.get('key', '')
            if k:
                self.button_queue.put(k)
            resp = make_response(jsonify({'ok': True}))
            resp.headers['Cache-Control'] = 'no-store'
            return resp

        # Apps
        @app.route('/api/apps')
        def api_apps():
            from core.background import bgm
            apps = _scan_apps()
            active = [{'name': n, 'uptime': bgm.uptime(n),
                        'module': bgm.get_task_info(n).get('module', '')}
                      for n in bgm.active_tasks()]
            return jsonify({'apps': apps, 'active': active})

        @app.route('/api/apps/stop', methods=['POST'])
        def api_apps_stop():
            from core.background import bgm
            name = (request.get_json(force=True) or {}).get('name', '')
            if not name:
                return jsonify({'ok': False, 'error': 'name required'})
            if name not in bgm.active_tasks():
                return jsonify({'ok': False, 'error': f'"{name}" not running'})
            try:
                bgm.stop(name)
                return jsonify({'ok': True})
            except Exception as e:
                return jsonify({'ok': False, 'error': str(e)})

        @app.route('/api/apps/launch', methods=['POST'])
        def api_apps_launch():
            # Queue a request for main.py to open this app on the device screen.
            # main.py reads pop_launch_request() each tick and navigates to the app.
            data   = request.get_json(force=True) or {}
            name   = str(data.get('name', '')).strip()
            module = str(data.get('module', '')).strip()
            if not module:
                return jsonify({'ok': False, 'error': 'module required'})
            self._launch_queue.put({'name': name, 'module': module})
            return jsonify({'ok': True})

        # Files
        @app.route('/api/files')
        def api_files():
            return jsonify({'entries': _list_files(request.args.get('path', ''))})

        @app.route('/api/files/download')
        def api_files_download():
            rel    = request.args.get('path', '')
            base   = os.path.realpath(FILES_DIR)
            target = os.path.realpath(os.path.join(base, rel))
            if not target.startswith(base) or not os.path.isfile(target):
                return make_response('not found', 404)
            return send_file(target, as_attachment=True,
                             download_name=os.path.basename(target))

        @app.route('/api/files/upload', methods=['POST'])
        def api_files_upload():
            sub    = request.args.get('path', '')
            base   = os.path.realpath(FILES_DIR)
            target = os.path.realpath(os.path.join(base, sub)) if sub else base
            if not target.startswith(base):
                return jsonify({'ok': False, 'error': 'invalid path'})
            if 'file' not in request.files:
                return jsonify({'ok': False, 'error': 'no file in request'})
            saved = []
            for f in request.files.getlist('file'):
                fname = secure_filename(f.filename or '')
                if not fname:
                    continue
                try:
                    os.makedirs(target, exist_ok=True)
                    f.save(os.path.join(target, fname))
                    saved.append(fname)
                except Exception as e:
                    return jsonify({'ok': False, 'error': str(e)})
            return jsonify({'ok': True, 'saved': saved})

        @app.route('/api/files', methods=['DELETE'])
        def api_files_delete():
            rel    = (request.get_json(force=True) or {}).get('path', '')
            base   = os.path.realpath(FILES_DIR)
            target = os.path.realpath(os.path.join(base, rel))
            if not target.startswith(base):
                return jsonify({'ok': False, 'error': 'invalid path'})
            if not os.path.isfile(target):
                return jsonify({'ok': False, 'error': 'not found'})
            try:
                os.remove(target)
                return jsonify({'ok': True})
            except Exception as e:
                return jsonify({'ok': False, 'error': str(e)})

        # System
        @app.route('/api/system')
        def api_system():
            s = _sys_stats()
            s['uptime_str'] = _fmt_uptime(s['uptime'])
            return jsonify(s)

        @app.route('/api/ips')
        def api_ips():
            return jsonify({'ips': _get_ips()})

        # Settings
        @app.route('/api/settings', methods=['GET'])
        def api_settings_get():
            cfg   = _load_config()
            known = [k for k in _CONFIG_WHITELIST if k in cfg]
            return jsonify({'config': cfg, 'meta': _CONFIG_WHITELIST, 'known': known})

        @app.route('/api/settings', methods=['POST'])
        def api_settings_post():
            data  = request.get_json(force=True) or {}
            key   = str(data.get('key', '')).strip()
            value = data.get('value')
            if not key:
                return jsonify({'ok': False, 'error': 'key required'})
            cfg  = _load_config()
            meta = _CONFIG_WHITELIST.get(key, {})
            t    = meta.get('type', 'string')
            try:
                if t == 'int':
                    value = int(value)
                    mn = meta.get('min')
                    mx = meta.get('max')
                    if mn is not None and value < mn: value = mn
                    if mx is not None and value > mx: value = mx
                elif t == 'bool':
                    value = bool(value)
                elif t == 'choice':
                    if value not in meta.get('choices', [value]):
                        return jsonify({'ok': False, 'error': 'invalid choice'})
                else:
                    value = str(value)
            except Exception as e:
                return jsonify({'ok': False, 'error': str(e)})
            cfg[key] = value
            _save_config(cfg)
            return jsonify({'ok': True})

        # DNS rules
        @app.route('/dns')
        def dns_redirect():
            return '<meta http-equiv="refresh" content="0;url=/">'

        @app.route('/dns/api', methods=['GET'])
        def dns_api_get():
            from core.background import bgm
            info     = bgm.get_task_info('DNS Spoofer')
            instance = info.get('instance') if info else None
            if instance:
                return jsonify({
                    'rules':         list(instance._rules),
                    'running':       True,
                    'victim_ip':     getattr(instance, '_victim_ip', ''),
                    'total_queries': getattr(instance, '_total_queries', 0),
                })
            return jsonify({'rules': _load_dns_rules(), 'running': False,
                            'victim_ip': '', 'total_queries': 0})

        @app.route('/dns/api', methods=['POST'])
        def dns_api_post():
            rules = (request.get_json(force=True) or {}).get('rules')
            if not isinstance(rules, list):
                return jsonify({'ok': False, 'error': 'rules must be a list'})
            clean = [{'domain': str(r.get('domain', '')).strip(),
                      'ip':     str(r.get('ip', '')).strip(),
                      'enabled': bool(r.get('enabled', True))}
                     for r in rules
                     if isinstance(r, dict) and str(r.get('domain', '')).strip()]
            _save_dns_rules(clean)
            from core.background import bgm
            info     = bgm.get_task_info('DNS Spoofer')
            instance = info.get('instance') if info else None
            if instance:
                instance._rules = clean
            return jsonify({'ok': True, 'applied_live': instance is not None})

    # ── Public API ────────────────────────────────────────────

    def push_frame(self, img):
        """Push PIL.Image to long-poll clients. No-op when paused."""
        if self._stopped:
            return
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=75)
        with self._lock:
            self._frame_data = buf.getvalue()
            self._frame_id  += 1
        self._frame_event.set()

    def start(self):
        """Start Flask in background thread. If already running, resume streaming."""
        if self._started:
            self._stopped = False
            return
        self._started = True
        self._stopped = False
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        threading.Thread(
            target=lambda: self._app.run(
                host=self.host, port=self.port,
                threaded=True, use_reloader=False),
            daemon=True
        ).start()

    def stop(self):
        """Pause streaming. Flask stays alive; clients receive 503."""
        self._stopped = True
        self._frame_event.set()

    @property
    def is_running(self) -> bool:
        return self._started and not self._stopped
