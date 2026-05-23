import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.analytics_db import get_dashboard_data


ROOT_DIR = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT_DIR / "web" / "analytics.html"


class AnalyticsHandler(BaseHTTPRequestHandler):
    def _write(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/analytics", "/analytics.html"):
            body = HTML_PATH.read_bytes()
            self._write(200, "text/html; charset=utf-8", body)
            return

        if parsed.path == "/api/dashboard":
            query = parse_qs(parsed.query)
            limit = 100
            raw_limit = query.get("limit", [None])[0]
            if raw_limit:
                try:
                    limit = max(1, min(int(raw_limit), 1000))
                except ValueError:
                    limit = 100
            payload = json.dumps(get_dashboard_data(limit=limit), ensure_ascii=False).encode("utf-8")
            self._write(200, "application/json; charset=utf-8", payload)
            return

        self._write(404, "text/plain; charset=utf-8", b"Not Found")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), AnalyticsHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
