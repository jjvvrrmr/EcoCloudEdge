import urllib.request
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

OLLAMA_URL = "http://ollama-svc:11434/api/generate"
OLLAMA_TIMEOUT = 120


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[middleware] {format % args}")

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": "No body"}).encode("utf-8")
            )
            return

        post_data = self.rfile.read(content_length)

        try:
            data = json.loads(post_data)
            prompt = data.get("prompt", "Resume este texto brevemente.")

            ollama_payload = {
                "model": "tinyllama",
                "prompt": prompt,
                "stream": False,
            }

            req = urllib.request.Request(
                OLLAMA_URL,
                data=json.dumps(ollama_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8"))

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "status": "success",
                        "respuesta": result.get("response", ""),
                    }
                ).encode("utf-8")
            )

        except json.JSONDecodeError as e:
            self.send_response(400)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": f"JSON inválido: {str(e)}"}).encode("utf-8")
            )

        except Exception as e:
            print(f"[middleware] ERROR: {e}")
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": str(e)}).encode("utf-8")
            )


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 5000), WebhookHandler)
    print("[middleware] Activo en puerto 5000...")
    server.serve_forever()