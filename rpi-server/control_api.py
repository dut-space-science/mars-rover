import subprocess

import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from flask_smorest import Api, Blueprint
from marshmallow import Schema, fields

COLORDETECT = "http://localhost:9003"
MOTION_STREAM = "http://localhost:9002"
PICOCOMS = "http://localhost:8080"
PORT = 8000

SERVICES = ["colordetect", "netconman", "picocoms", "motion", "websockify", "control-api"]
ACTIONS = ["start", "stop", "restart"]

app = Flask(__name__)
app.config.update(
    API_TITLE="Mars Rover Control API",
    API_VERSION="v1",
    OPENAPI_VERSION="3.0.3",
    OPENAPI_URL_PREFIX="/api/docs",
    OPENAPI_SWAGGER_UI_PATH="/",
    OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
)
CORS(app)
api = Api(app)
blp = Blueprint("control", __name__, description="Rover control center endpoints", url_prefix="/api")


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
        return r.content, r.status_code, r.headers.get("Content-Type", "application/json")
    except requests.RequestException as e:
        return Response(jsonify({"error": str(e)}).data, status=502, mimetype="application/json")[0].data, 502, "application/json"


class StatusResponse(Schema):
    programs = fields.Dict(keys=fields.Str(), values=fields.Str())
    active_connections = fields.List(fields.Str())
    error = fields.Str(allow_none=True)


class ServiceActionResponse(Schema):
    ok = fields.Bool()
    output = fields.Str()


class ColordetectConfigQuery(Schema):
    pass


class PicoCommandBody(Schema):
    cmd = fields.Str(required=True, metadata={"description": "Command to send to the Pico", "example": "PING"})
    timeout = fields.Int(load_default=2, metadata={"description": "Seconds to wait for the response"})


class ErrorResponse(Schema):
    error = fields.Str()


class SystemResponse(Schema):
    cpu_percent = fields.Float()
    cpu_temp_c = fields.Float(allow_none=True)
    load_avg = fields.List(fields.Float())
    memory = fields.Dict()
    disk = fields.Dict()
    wifi = fields.Dict()
    uptime_s = fields.Float()


@blp.route("/system", methods=["GET"])
@blp.response(200, SystemResponse)
@blp.doc(summary="CPU, RAM, disk, temperature, wifi signal, uptime")
def system():
    import time

    import psutil

    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    temp = None
    rc, out, _ = run(["vcgencmd", "measure_temp"])
    if rc == 0 and "temp=" in out:
        try:
            temp = float(out.split("temp=")[1].rstrip("'C"))
        except ValueError:
            pass
    wifi = {}
    rc, out, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,BARS", "device", "wifi", "list"])
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(":")
            if parts and parts[0] == "*" and len(parts) >= 4:
                wifi = {"ssid": parts[1], "signal_percent": int(parts[2]), "bars": parts[3]}
                break
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_temp_c": temp,
        "load_avg": list(psutil.getloadavg()),
        "memory": {"total_mb": vm.total // 2**20, "used_mb": vm.used // 2**20, "percent": vm.percent},
        "disk": {"total_gb": round(du.total / 2**30, 1), "used_gb": round(du.used / 2**30, 1), "percent": du.percent},
        "wifi": wifi,
        "uptime_s": round(time.time() - psutil.boot_time(), 1),
    }


@blp.route("/status", methods=["GET"])
@blp.response(200, StatusResponse)
@blp.doc(summary="Supervisor program states and active wifi connections")
def status():
    _, out, err = run(["sudo", "-n", "supervisorctl", "status"])
    programs = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            programs[parts[0]] = parts[1].strip()
    _, wifi_ssid, _ = run(["nmcli", "-t", "-f", "NAME", "con", "show", "--active"])
    return {"programs": programs, "active_connections": wifi_ssid.splitlines(), "error": None if programs else (err or out or "no output from supervisorctl")}


@blp.route("/services/<string:name>/<string:action>", methods=["POST"])
@blp.response(200, ServiceActionResponse)
@blp.doc(summary="Start, stop, or restart a supervisor program. name: one of " + ", ".join(SERVICES) + ". action: start|stop|restart")
def service_action(name, action):
    if name not in SERVICES or action not in ACTIONS:
        return jsonify({"error": "unknown service or action"}), 400
    rc, out, err = run(["sudo", "-n", "supervisorctl", action, name], timeout=30)
    return {"ok": rc == 0, "output": out or err}, 200 if rc == 0 else 500


@blp.route("/colordetect/status", methods=["GET"])
@blp.doc(summary="Color detection health, processing state, motion state")
def colordetect_status():
    content, code, ctype = proxy_json(f"{COLORDETECT}/health")
    return Response(content, status=code, mimetype=ctype)


@blp.route("/colordetect/config", methods=["GET"])
@blp.doc(summary="Get HSV thresholds, min_area, jpeg_quality, resize_width")
def colordetect_config_get():
    content, code, ctype = proxy_json(f"{COLORDETECT}/config")
    return Response(content, status=code, mimetype=ctype)


@blp.route("/colordetect/config", methods=["POST"])
@blp.doc(summary="Update color detection config",
         description="Accepts keys: colours (per-color HSV ranges + bgr), min_area, jpeg_quality, resize_width")
def colordetect_config_post():
    content, code, ctype = proxy_json(f"{COLORDETECT}/config", "POST", request.get_json(force=True))
    return Response(content, status=code, mimetype=ctype)


@blp.route("/colordetect/motion/<string:action>", methods=["POST"])
@blp.doc(summary="Enable, disable, or toggle motion + detection. action: enable|disable|toggle")
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


@blp.route("/colordetect/detect/<string:action>", methods=["POST"])
@blp.doc(summary="Turn colour detection on/off without touching the camera. action: enable|disable")
def colordetect_detect(action):
    if action not in ("enable", "disable"):
        return jsonify({"error": "unknown action"}), 400
    content, code, ctype = proxy_json(f"{COLORDETECT}/detect/{action}", "POST", {})
    return Response(content, status=code, mimetype=ctype)


@blp.route("/camera/stream", methods=["GET"])
@blp.doc(summary="Raw MJPEG camera stream from motion (no detection overlay)")
def camera_stream():
    try:
        r = requests.get(MOTION_STREAM, stream=True, timeout=10)
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

    def generate():
        with r:
            yield from r.iter_content(chunk_size=4096)

    return Response(generate(), content_type=r.headers.get("Content-Type"))


@blp.route("/colordetect/snapshot", methods=["GET"])
@blp.doc(summary="Latest processed JPEG frame")
def colordetect_snapshot():
    try:
        r = requests.get(f"{COLORDETECT}/snapshot", timeout=10)
        return Response(r.content, status=r.status_code, mimetype=r.headers.get("Content-Type"))
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


@blp.route("/colordetect/video_feed", methods=["GET"])
@blp.doc(summary="MJPEG video stream of processed frames")
def colordetect_video_feed():
    def generate():
        with requests.get(f"{COLORDETECT}/video_feed", stream=True, timeout=10) as r:
            for chunk in r.iter_content(chunk_size=4096):
                yield chunk

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@blp.route("/pico/command", methods=["POST"])
@blp.arguments(PicoCommandBody)
@blp.doc(summary="Send a command to the Pico over serial (PING, LED_ON, LED_OFF, HELLO)")
def pico_command(body):
    cmd = body["cmd"]
    timeout = body["timeout"]
    content, code, ctype = proxy_json(f"{PICOCOMS}/", "POST", {"cmd": cmd, "timeout": timeout}, timeout=timeout + 5)
    return Response(content, status=code, mimetype=ctype)


@blp.route("/wifi/status", methods=["GET"])
@blp.doc(summary="nmcli device states")
def wifi_status():
    rc, out, err = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"])
    return {"ok": rc == 0, "devices": out, "error": err if rc else None}


api.register_blueprint(blp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
