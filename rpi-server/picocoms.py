import json
import serial
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080

ser = serial.Serial("/dev/serial0", baudrate=115200, timeout=2)
lock = threading.Lock()

def send_command(cmd, timeout):
    with lock:
        ser.timeout = timeout
        ser.reset_input_buffer()
        ser.write((cmd + "\n").encode())
        lines = []
        while True:
            line = ser.readline()
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text:
                lines.append(text)
        return lines

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

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) if length else b"{}")
            cmd = body.get("cmd", "")
            timeout = body.get("timeout", 2)
            lines = send_command(cmd, timeout) if cmd else []
            self._reply({"cmd": cmd, "response": lines})
        except Exception as exc:
            self._reply({"error": str(exc)}, 500)

    def do_GET(self):
        if self.path == "/ping":
            self._reply({"status": "ok"})
        else:
            self._reply({"error": "not found", "use": "POST {'cmd': 'PING'}"}, 404)

    def log_message(self, fmt, *args):
        print(f"[http] {self.address_string()} {fmt % args}", flush=True)

if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"picocoms HTTP server listening on :{PORT}", flush=True)
    server.serve_forever()
