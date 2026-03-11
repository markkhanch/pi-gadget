# remote ui

The Remote UI lets you see and control the device from a browser over Wi-Fi — useful for demos, development, and operating the device without looking at the physical screen.

***

## How to enable

{% stepper %}
{% step %}
### Make sure the Pi is connected to Wi-Fi

Open **Settings → Wi-Fi Manager** on the device and connect to a network.
{% endstep %}

{% step %}
### Open WebUI settings

Open **Settings → WebUI** on the device.
{% endstep %}

{% step %}
### Start the WebUI

Press CENTER to start.
{% endstep %}

{% step %}
### Note the URL

The screen shows: `http://<device-ip>:5000`
{% endstep %}

{% step %}
### Open in a browser

Open that URL in any browser on the same network.
{% endstep %}
{% endstepper %}

***

## What the browser shows

* **Live display stream** — MJPEG stream of the device screen at \~20 fps
* **Button controls** — clickable buttons for `UP`, `DOWN`, `LEFT`, `RIGHT`, `CENTER`, `K1`, `K2`, `K3`
* **App launcher** — a list of available apps that can be launched remotely

Button clicks from the browser are placed into `hw._remote_queue` and processed by the main loop identically to physical button presses.

***

## Architecture

```
core/remote_ui.py
└── RemoteUI(button_queue, port=5000)
    ├── Flask server (background thread)
    ├── MJPEG stream endpoint: GET /stream
    ├── Button event endpoint: POST /key
    └── App launch endpoint: POST /launch
```

`RemoteUI` is started once by `HWDisplay.__init__()` and stored as a module-level singleton (`_remote_instance`). All subsequent `HWDisplay` instantiations reuse the same instance and its queue.

Every call to `hw.show(img)` automatically forwards the frame to RemoteUI via `_DisplayProxy.ShowImage()` → `remote.push_frame(img)`. No app code needs to know about RemoteUI.

***

## Start / stop behavior

* **Start:** sets internal `_started = True`, resumes MJPEG frame emission
* **Stop:** sets `_stopped = True`, pauses frame emission — Flask server stays alive
* The underlying Flask process is never killed during a session. Stopping and restarting from the Settings app does not trigger "Address already in use" errors.

***

## Remote app launch

The WebUI can launch an app on the physical device directly from the browser. The main loop checks `hw._remote.pop_launch_request()` every frame. If a launch request is present:

1. The currently running app is exited cleanly (`on_exit()` called)
2. The requested module is loaded via `apps/loader.py`
3. `on_enter()` is called and the app takes over the screen

***

## Security

There is no authentication on the WebUI. Anyone on the same network can control the device. Use only on trusted networks (your own hotspot or lab).

***

## Troubleshooting

<details>

<summary>Browser shows no stream</summary>

* Confirm WebUI status shows RUNNING in the Settings app
* Confirm the device IP is correct — check via **System → Device Info**
* Make sure both devices are on the same subnet

</details>

<details>

<summary>Buttons in browser not responding</summary>

* Check browser console for fetch errors
* If the Flask server crashed, toggle WebUI off/on from the Settings app

</details>

<details>

<summary>Port 5000 conflict</summary>

* Default port is 5000. If another service is using it, edit `remote_port` in `core/hw.py` HWDisplay constructor (no config.json key exists for this yet).

</details>
