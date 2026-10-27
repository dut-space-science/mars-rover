"""Minimal stdio MCP client for `solidcraft-cli mcp`."""
import base64, json, subprocess, itertools

class SolidCraftMCP:
    def __init__(self, design, allow, extra=()):
        self.p = subprocess.Popen(
            ["solidcraft-cli", "mcp", "--headless", "--in", design, "--allow-path", allow, *extra],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.ids = itertools.count(1)
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "rover-video", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n"); self.p.stdin.flush()

    def _rpc(self, method, params):
        i = next(self.ids)
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line: raise RuntimeError("MCP server closed")
            m = json.loads(line)
            if m.get("id") == i:
                if "error" in m: raise RuntimeError(m["error"])
                return m["result"]

    def tool(self, name, **args):
        r = self._rpc("tools/call", {"name": name, "arguments": args})
        texts = [c["text"] for c in r.get("content", []) if c["type"] == "text"]
        if r.get("isError"): raise RuntimeError(" ".join(texts))
        for t in texts:
            try: return json.loads(t)
            except Exception: pass
        return texts

    def cmd(self, command, **params):
        return self.tool("execute", command=command, params=params, verbose=False)

    def close(self):
        self.p.stdin.close(); self.p.wait(timeout=10)
