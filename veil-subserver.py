#!/usr/bin/env python3
"""veil-subserver — минимальная раздача профилей подписки.
Отдаёт ТОЛЬКО /sub/<token> если такой файл есть в SUB_DIR. Никакого листинга каталога,
никаких других путей — чтобы случайные токены нельзя было перечислить.
Порт и каталог берутся из окружения (VEIL_SUB_PORT, VEIL_SUB_DIR).
"""
import os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUB_DIR  = os.environ.get("VEIL_SUB_DIR", "/etc/veil/sub")
PORT     = int(os.environ.get("VEIL_SUB_PORT", "8080"))
TOKEN_RE = re.compile(r"^/sub/([A-Za-z0-9_-]{8,64})$")

class H(BaseHTTPRequestHandler):
    server_version = "veil"
    def _deny(self, code=404):
        self.send_response(code); self.send_header("Content-Length", "0"); self.end_headers()
    def do_GET(self):
        m = TOKEN_RE.match(self.path)
        if not m:
            return self._deny(404)
        path = os.path.join(SUB_DIR, m.group(1))
        # защита от path traversal: файл обязан лежать прямо в SUB_DIR
        if os.path.dirname(os.path.realpath(path)) != os.path.realpath(SUB_DIR) or not os.path.isfile(path):
            return self._deny(404)
        data = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Profile-Update-Interval", "12")
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):  # тихо
        pass

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
