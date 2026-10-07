import subprocess

import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

COLORDETECT = "http://localhost:9003"
PICOCOMS = "http://localhost:8080"
PORT = 8000

SERVICES = ["colordetect", "netconman", "picocoms", "motion", "websockify"]
ACTIONS = ["start", "stop", "restart"]

app = Flask(__name__)
CORS(app)


def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def proxy_json(url, method="GET", body=None, timeout=10):
    try:
        if method == "POST":
            r = requests.post(url, json=body or {}, timeout=timeout)
        else:
            r = requests.get(url, timeout=timeout)
        return (r.content, r.status_code, r.headers.get("Content-Type", "application/json"))
    except requests.RequestException as e:
        return jsonify({"error": str(e)})[0].data, 502, "application/json"


@app.get("/api/status")
def status():
    _, out, _ = run(["sudo", "supervisorctl", "status"])
    programs = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            programs[parts[0]] = parts[1].strip()
    _, wifi_ssid, _ = run(["nmcli", "-t", "-f", "NAME", "con", "show", "--active"])
    return jsonify({"programs": programs, "active_connections": wifi_ssid.splitlines()})


@app.post("/api/services/<name>/<action>")
def service_action(name, action):
    if name not in SERVICES or action not in ACTIONS:
        return jsonify({"error": "unknown service or action"}), 400
    rc, out, err = run(["sudo", "supervisorctl", action, name], timeout=30)
    return jsonify({"ok": rc == 0, "output": out or err}), 200 if rc == 0 else 500


@app.get("/api/colordetect/status")
def colordetect_status():
    content, code, ctype = proxy_json(f"{COLORDETECT}/health")
    return Response(content, status=code, mimetype=ctype)


@app.get("/api/colordetect/config")
def colordetect_config_get():
    content, code, ctype = proxy_json(f"{COLORDETECT}/config")
    return Response(content, status=code, mimetype=ctype)


@app.post("/api/colordetect/config")
def colordetect_config_post():
    content, code, ctype = proxy_json(f"{COLORDETECT}/config", "POST", request.get_json(force=True))
    return Response(content, status=code, mimetype=ctype)


@app.post("/api/colordetect/motion/<action>")
def colordetect_motion(action):
    if action in ("enable", "start"):
        path = "/motion/enable"
    elif action in ("disable", "stop"):
        path = "/motion/disable"
    elif action == "toggle":
        path = "/motion/toggle"
    else:
        return jsonify({"error": "unknown action"}), 400
    content, code, ctype = proxy_json(f"{COLORDETECT}{path}", "POST", {}, timeout=30)
    return Response(content, status=code, mimetype=ctype)


@app.get("/api/colordetect/snapshot")
def colordetect_snapshot():
    try:
        r = requests.get(f"{COLORDETECT}/snapshot", timeout=10)
        return Response(r.content, status=r.status_code, mimetype=r.headers.get("Content-Type"))
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/colordetect/video_feed")
def colordetect_video_feed():
    def generate():
        with requests.get(f"{COLORDETECT}/video_feed", stream=True, timeout=10) as r:
            for chunk in r.iter_content(chunk_size=4096):
                yield chunk

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/pico/command")
def pico_command():
    body = request.get_json(force=True) or {}
    cmd = body.get("cmd", "")
    timeout = body.get("timeout", 2)
    if not cmd:
        return jsonify({"error": "cmd required"}), 400
    content, code, ctype = proxy_json(f"{PICOCOMS}/", "POST", {"cmd": cmd, "timeout": timeout}, timeout=timeout + 5)
    return Response(content, status=code, mimetype=ctype)


@app.get("/api/wifi/status")
def wifi_status():
    rc, out, err = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"])
    return jsonify({"ok": rc == 0, "devices": out, "error": err if rc else None})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
