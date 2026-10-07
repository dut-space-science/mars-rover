import cv2
import numpy as np
import threading
import time
import subprocess
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9003
MOTION_STREAM = "http://localhost:9002"
MOTION_WEBCONTROL = "http://localhost:9001"

latest_frame = None
latest_lock = threading.Lock()
processing = False
proc_lock = threading.Lock()

config_lock = threading.Lock()
config = {
    "colours": {
        "red": {"low1": [0, 120, 70], "high1": [10, 255, 255], "low2": [170, 120, 70], "high2": [180, 255, 255], "bgr": [0, 0, 255]},
        "green": {"low": [36, 50, 70], "high": [89, 255, 255], "bgr": [0, 255, 0]},
        "blue": {"low": [90, 50, 70], "high": [128, 255, 255], "bgr": [255, 0, 0]},
        "yellow": {"low": [20, 100, 100], "high": [30, 255, 255], "bgr": [0, 255, 255]}
    },
    "min_area": 800,
    "jpeg_quality": 80,
    "resize_width": 640
}

def log(msg):
    print(f"[colordetect] {msg}", flush=True)

def run_cmd(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def motion_status():
    rc, out, err = run_cmd(["sudo", "supervisorctl", "status", "motion"])
    if "RUNNING" in out:
        return "running"
    if "STOPPED" in out:
        return "stopped"
    return out.strip() or err.strip() or "unknown"

def motion_start():
    rc, out, err = run_cmd(["sudo", "supervisorctl", "start", "motion"])
    log(f"motion start rc={rc} out={out} err={err}")
    return rc == 0, out or err

def motion_stop():
    rc, out, err = run_cmd(["sudo", "supervisorctl", "stop", "motion"])
    log(f"motion stop rc={rc} out={out} err={err}")
    return rc == 0, out or err

def detect_and_draw(frame):
    with config_lock:
        colours = dict(config["colours"])
        min_area = int(config["min_area"])
        resize_w = int(config.get("resize_width", 640))

    h, w = frame.shape[:2]
    if w != resize_w:
        scale = resize_w / w
        frame = cv2.resize(frame, (resize_w, int(h * scale)))

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    kernel = np.ones((5, 5), np.uint8)

    detections = []
    for name, c in colours.items():
        bgr = c.get("bgr", [255, 255, 255])
        if name == "red" and "low1" in c:
            low1 = np.array(c["low1"], dtype=np.uint8)
            high1 = np.array(c["high1"], dtype=np.uint8)
            low2 = np.array(c["low2"], dtype=np.uint8)
            high2 = np.array(c["high2"], dtype=np.uint8)
            mask = cv2.bitwise_or(cv2.inRange(hsv, low1, high1), cv2.inRange(hsv, low2, high2))
        else:
            low = np.array(c["low"], dtype=np.uint8)
            high = np.array(c["high"], dtype=np.uint8)
            mask = cv2.inRange(hsv, low, high)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            detections.append((name, x, y, bw, bh, bgr))
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), bgr, 2)
            cv2.putText(frame, f"{name}", (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, bgr, 2, cv2.LINE_AA)
            cv2.putText(frame, f"{int(area)}px", (x, y + bh + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, bgr, 1, cv2.LINE_AA)
    return frame, detections

def capture_loop():
    global latest_frame, processing
    cap = None
    while True:
        with proc_lock:
            do_proc = processing
        if not do_proc:
            if cap is not None:
                try:
                    cap.release()
                except:
                    pass
                cap = None
            time.sleep(0.5)
            continue
        if cap is None:
            log(f"opening motion stream {MOTION_STREAM}")
            cap = cv2.VideoCapture(MOTION_STREAM)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                log("failed to open motion stream, retry in 2s (ensure motion is running)")
                cap = None
                time.sleep(2)
                continue
        ret, frame = cap.read()
        if not ret or frame is None:
            log("read failed, reopening stream")
            try:
                cap.release()
            except:
                pass
            cap = None
            time.sleep(1)
            continue
        processed, _ = detect_and_draw(frame)
        with config_lock:
            q = int(config.get("jpeg_quality", 80))
        ok, buf = cv2.imencode(".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if ok:
            with latest_lock:
                latest_frame = buf.tobytes()
        time.sleep(0.03)

class Handler(BaseHTTPRequestHandler):
    def _reply(self, obj, code=200):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, html, code=200):
        payload = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            st = motion_status()
            with proc_lock:
                en = processing
            with latest_lock:
                has = latest_frame is not None
            with config_lock:
                cols = list(config["colours"].keys())
            html = f"""<!doctype html><html><head><title>colordetect</title></head>
<body style="font-family:sans-serif;max-width:900px;margin:20px auto">
<h2>colordetect :9003</h2>
<p>motion: <b>{st}</b> | processing: <b>{'on' if en else 'off'}</b> | frame: {'yes' if has else 'no'}</p>
<p>
<button onclick="fetch('/motion/enable',{{method:'POST'}}).then(r=>r.json()).then(j=>alert(JSON.stringify(j)))">Enable motion + start</button>
<button onclick="fetch('/motion/disable',{{method:'POST'}}).then(r=>r.json()).then(j=>alert(JSON.stringify(j)))">Disable motion + stop</button>
<button onclick="fetch('/motion/toggle',{{method:'POST'}}).then(r=>r.json()).then(j=>alert(JSON.stringify(j)))">Toggle</button>
</p>
<p><a href="/video_feed" target="_blank">/video_feed (MJPEG)</a> | <a href="/snapshot" target="_blank">/snapshot</a> | <a href="/config">/config</a> | <a href="/ping">/ping</a></p>
<img src="/video_feed" style="width:100%;max-width:640px;border:1px solid #ccc" />
<p>colours: {', '.join(cols)} — POST /config to update HSV thresholds. Example: {{"colours":{{"red":{{"low1":[0,120,70]}}}}}}</p>
<pre>curl -s http://localhost:9003/ping
curl -s -X POST http://localhost:9003/motion/enable
curl http://localhost:9003/video_feed | ffplay -
</pre>
</body></html>"""
            self._html(html)
            return
        if self.path == "/ping":
            self._reply({"status": "ok", "processing": processing, "motion": motion_status()})
            return
        if self.path == "/health":
            self._reply({"status": "ok", "processing": processing, "motion": motion_status()})
            return
        if self.path == "/config":
            with config_lock:
                self._reply(dict(config))
            return
        if self.path == "/motion/status":
            self._reply({"motion": motion_status(), "processing": processing})
            return
        if self.path == "/snapshot":
            with latest_lock:
                frame = latest_frame
            if frame is None:
                self._reply({"error": "no frame yet, enable motion first"}, 503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(frame)
            return
        if self.path == "/video_feed":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    with latest_lock:
                        frame = latest_frame
                    if frame is None:
                        placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(placeholder, "no frame - POST /motion/enable", (30, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2, cv2.LINE_AA)
                        ok, buf = cv2.imencode(".jpg", placeholder, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                        frame = buf.tobytes() if ok else b""
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    time.sleep(0.07)
            except Exception:
                pass
            return
        self._reply({"error": "not found"}, 404)

    def do_POST(self):
        if self.path in ("/motion/enable", "/motion/start"):
            ok, msg = motion_start()
            if ok:
                time.sleep(2)
                with proc_lock:
                    global processing
                    processing = True
                log("processing enabled")
            self._reply({"ok": ok, "msg": msg, "motion": motion_status(), "processing": processing}, 200 if ok else 500)
            return
        if self.path in ("/motion/disable", "/motion/stop"):
            with proc_lock:
                processing = False
            ok, msg = motion_stop()
            self._reply({"ok": ok, "msg": msg, "motion": motion_status(), "processing": False})
            return
        if self.path == "/motion/toggle":
            st = motion_status()
            if st == "running":
                with proc_lock:
                    processing = False
                motion_stop()
                self._reply({"motion": motion_status(), "processing": False})
            else:
                motion_start()
                time.sleep(2)
                with proc_lock:
                    processing = True
                self._reply({"motion": motion_status(), "processing": True})
            return
        if self.path == "/config":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) if length else b"{}")
                with config_lock:
                    if "colours" in body:
                        for k, v in body["colours"].items():
                            config["colours"][k] = v
                    if "min_area" in body:
                        config["min_area"] = int(body["min_area"])
                    if "jpeg_quality" in body:
                        config["jpeg_quality"] = int(body["jpeg_quality"])
                    snapshot = dict(config)
                self._reply(snapshot)
            except Exception as e:
                self._reply({"error": str(e)}, 400)
            return
        self._reply({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        print(f"[http] {self.address_string()} {fmt % args}", flush=True)

if __name__ == "__main__":
    t = threading.Thread(target=capture_loop, daemon=True)
    t.start()
    log(f"colordetect listening on :{PORT} motion={MOTION_STREAM}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
