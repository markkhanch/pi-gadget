"""
remote_ui.py v3 — long polling, zero one-frame delay.

Browser sends GET /frame?last_id=N
Server holds the connection open until a frame with id > N appears,
then returns it immediately. Browser gets the frame right after push_frame().
"""

import io
import threading
import queue
import time
from flask import Flask, Response, request, jsonify, make_response

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>Pi Gadget Remote</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700&display=swap');
  :root {
    --bg:#080b10;--border:#1a2030;--accent:#00e5ff;--accent2:#8b5cf6;
    --btn:#111722;--btn-h:#1a2438;--text:#b0c4d8;--dim:#3a4a5e;
    --glow:rgba(0,229,255,.12);
  }
  *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
  body{
    background:var(--bg);color:var(--text);
    font-family:'Share Tech Mono',monospace;
    min-height:100dvh;display:flex;flex-direction:column;
    align-items:center;justify-content:center;gap:18px;padding:20px 16px;
    background-image:radial-gradient(ellipse at 15% 15%,rgba(0,229,255,.03) 0%,transparent 55%),
      radial-gradient(ellipse at 85% 85%,rgba(139,92,246,.03) 0%,transparent 55%);
  }
  header{display:flex;align-items:center;gap:10px}
  .dot{width:7px;height:7px;border-radius:50%;background:var(--accent);
    box-shadow:0 0 8px var(--accent);animation:blink 2s infinite}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
  .logo{font-family:'Orbitron',sans-serif;font-size:15px;font-weight:700;
    letter-spacing:.18em;color:var(--accent)}
  .screen-frame{position:relative;border:1px solid var(--border);border-radius:6px;
    overflow:hidden;box-shadow:0 0 0 1px rgba(0,229,255,.08),0 0 32px rgba(0,229,255,.05)}
  .screen-frame::after{content:'';position:absolute;inset:0;
    background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.07) 2px,rgba(0,0,0,.07) 4px);
    pointer-events:none}
  #screen{display:block;width:240px;height:240px;image-rendering:pixelated}
  .controls{display:flex;flex-direction:column;align-items:center;gap:12px;width:100%;max-width:300px}
  .lbl{font-size:9px;letter-spacing:.22em;color:var(--dim);text-transform:uppercase}
  .div{width:100%;height:1px;background:linear-gradient(90deg,transparent,var(--border),transparent)}
  .key-row{display:flex;gap:9px;width:100%;justify-content:center}
  .key-btn{flex:1;max-width:88px;padding:11px 4px 9px;background:var(--btn);
    border:1px solid var(--border);border-radius:6px;color:var(--text);
    font-family:'Share Tech Mono',monospace;font-size:10px;cursor:pointer;
    text-align:center;user-select:none;transition:all .08s}
  .key-btn .k{font-family:'Orbitron',sans-serif;font-size:8px;letter-spacing:.1em;
    color:var(--dim);display:block;margin-bottom:4px}
  .key-btn:hover{background:var(--btn-h);border-color:rgba(0,229,255,.25)}
  .key-btn.active{background:rgba(0,229,255,.07);border-color:var(--accent);
    color:var(--accent);box-shadow:0 0 10px var(--glow);transform:scale(.95)}
  .joy{display:grid;grid-template-columns:repeat(3,58px);grid-template-rows:repeat(3,58px);gap:5px}
  .jb{width:58px;height:58px;background:var(--btn);border:1px solid var(--border);
    border-radius:6px;color:var(--text);font-size:20px;cursor:pointer;
    display:flex;align-items:center;justify-content:center;user-select:none;transition:all .08s}
  .jb:hover{background:var(--btn-h);border-color:rgba(0,229,255,.25)}
  .jb.active{background:rgba(0,229,255,.07);border-color:var(--accent);
    box-shadow:0 0 10px var(--glow);transform:scale(.92)}
  .jb.center{background:rgba(139,92,246,.08);border-color:rgba(139,92,246,.25);
    color:var(--accent2);font-size:12px;font-family:'Orbitron',sans-serif;letter-spacing:.05em}
  .jb.center.active{background:rgba(139,92,246,.15);border-color:var(--accent2);
    box-shadow:0 0 10px rgba(139,92,246,.2)}
  .je{visibility:hidden}
  #fb{font-size:10px;color:var(--dim);height:14px;letter-spacing:.05em;transition:color .15s}
  #fb.ok{color:var(--accent)} #fb.err{color:#f87171}
</style>
</head>
<body>
<header><div class="dot"></div><div class="logo">Pi Gadget Remote</div></header>
<div class="screen-frame">
  <img id="screen" width="240" height="240" alt="display">
</div>
<div class="controls">
  <div class="lbl">Keys</div>
  <div class="key-row">
    <button class="key-btn" data-key="KEY1"><span class="k">K1</span></button>
    <button class="key-btn" data-key="KEY2"><span class="k">K2</span></button>
    <button class="key-btn" data-key="KEY3"><span class="k">K3</span></button>
  </div>
  <div class="div"></div>
  <div class="lbl">Joystick</div>
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
<div id="fb">connecting...</div>

<script>
  const fb = document.getElementById('fb');
  const screen = document.getElementById('screen');
  let currentId = -1;
  let active = true;

  // Long polling: send request with last_id,
  // server holds it until a new frame appears, then responds immediately.
  async function fetchNextFrame() {
    try {
      const res = await fetch('/next_frame?last_id=' + currentId);
      if (!res.ok) throw new Error('bad status');
      const blob = await res.blob();
      const newId = parseInt(res.headers.get('X-Frame-Id') || '-1');
      
      // Показываем кадр
      const url = URL.createObjectURL(blob);
      const old = screen.src;
      screen.src = url;
      screen.onload = () => { if(old.startsWith('blob:')) URL.revokeObjectURL(old); };
      
      currentId = newId;
      fb.textContent = 'live';
      fb.className = 'ok';
    } catch(e) {
      fb.textContent = 'reconnecting...';
      fb.className = 'err';
      await new Promise(r => setTimeout(r, 500));
    }
    if (active) fetchNextFrame(); // immediately request the next frame
  }

  fetchNextFrame();

  // Кнопки
  function send(key) {
    fetch('/key', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key})
    }).catch(() => { fb.textContent = 'connection lost'; fb.className = 'err'; });
  }

  document.querySelectorAll('[data-key]').forEach(el => {
    el.addEventListener('mousedown',  () => { el.classList.add('active');    send(el.dataset.key); });
    el.addEventListener('mouseup',    () =>   el.classList.remove('active'));
    el.addEventListener('mouseleave', () =>   el.classList.remove('active'));
    el.addEventListener('touchstart', e  => { e.preventDefault(); el.classList.add('active'); send(el.dataset.key); });
    el.addEventListener('touchend',   e  => { e.preventDefault(); el.classList.remove('active'); });
  });
  document.addEventListener('contextmenu', e => e.preventDefault());
</script>
</body>
</html>"""


class RemoteUI:
    def __init__(self, button_queue: queue.Queue, host='0.0.0.0', port=5000):
        self.button_queue = button_queue  # public — shared by singleton in hw.py
        self.host = host
        self.port = port

        self._lock = threading.Lock()
        self._frame_data: bytes = b''
        self._frame_id: int = 0
        self._frame_event = threading.Event()  # signals that a new frame is available

        self._app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self):
        app = self._app

        @app.route('/')
        def index():
            return HTML

        @app.route('/next_frame')
        def next_frame():
            """
            Long polling: wait until frame_id > last_id, then return the frame.
            Browser gets the response immediately after push_frame() — no delay.
            """
            try:
                last_id = int(request.args.get('last_id', -1))
            except (ValueError, TypeError):
                last_id = -1

            timeout = 5.0  # максимум ждём 5 секунд (для screensaver и т.п.)
            deadline = time.time() + timeout

            while True:
                with self._lock:
                    fid = self._frame_id
                    data = self._frame_data

                if fid > last_id and data:
                    resp = make_response(data)
                    resp.headers['Content-Type'] = 'image/jpeg'
                    resp.headers['Cache-Control'] = 'no-store'
                    resp.headers['X-Frame-Id'] = str(fid)
                    return resp

                # Wait for new frame signal (or timeout)
                remaining = deadline - time.time()
                if remaining <= 0:
                    # Return current frame on timeout (screensaver etc.)
                    with self._lock:
                        data = self._frame_data
                        fid = self._frame_id
                    if not data:
                        time.sleep(0.1)
                        continue
                    resp = make_response(data)
                    resp.headers['Content-Type'] = 'image/jpeg'
                    resp.headers['Cache-Control'] = 'no-store'
                    resp.headers['X-Frame-Id'] = str(fid)
                    return resp

                self._frame_event.wait(timeout=min(remaining, 0.1))
                self._frame_event.clear()

        @app.route('/key', methods=['POST'])
        def key():
            data = request.get_json(force=True)
            k = data.get('key', '')
            if k:
                self.button_queue.put(k)
            resp = make_response(jsonify({'ok': True}))
            resp.headers['Cache-Control'] = 'no-store'
            return resp

    def push_frame(self, img):
        """Accept PIL.Image — call after every hw.show()."""
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=75)
        with self._lock:
            self._frame_data = buf.getvalue()
            self._frame_id += 1
        # Signal all waiting threads that a new frame is ready
        self._frame_event.set()

    def start(self):
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        t = threading.Thread(
            target=lambda: self._app.run(host=self.host, port=self.port, threaded=True),
            daemon=True
        )
        t.start()
        print(f"[RemoteUI] Open in browser → http://<IP_PI>:{self.port}")
        print(f"[RemoteUI] Get IP with: hostname -I")
