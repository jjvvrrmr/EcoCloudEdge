"""
EcoCloud Edge — Middleware Python
Hito 5: Conecta webhooks de Nextcloud con la API de Ollama.

Flujo:
  Nextcloud (evento de subida) → POST /webhook → Este script →
  → HTTP POST a Ollama API → tinyllama → respuesta JSON

Uso en desarrollo local:
  pip install flask requests
  OLLAMA_URL=http://localhost:11434/api/generate python main.py

Uso en Kubernetes:
  Desplegado como Deployment, Ollama accesible via ollama-svc:11434
"""

import json
import os
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

# URL del servicio Ollama dentro del clúster k3s
OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://ollama-svc:11434/api/generate"
)

# Modelo a usar — tinyllama por limitación de RAM en Raspberry Pi 4B
MODEL = os.environ.get("OLLAMA_MODEL", "tinyllama")

PORT = int(os.environ.get("PORT", 5000))


def query_ollama(prompt: str) -> dict:
    """
    Envía un prompt a la API de Ollama y devuelve el resultado.
    Usa urllib para no necesitar dependencias externas (imagen Alpine).
    """
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


class WebhookHandler(BaseHTTPRequestHandler):
    """
    Servidor HTTP mínimo que recibe webhooks de Nextcloud.
    Endpoint: POST /webhook
    Body JSON esperado: {"prompt": "texto a procesar"}
    """

    def do_GET(self):
        """Health-check endpoint para kubectl readinessProbe."""
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)

            prompt = data.get("prompt", "Resume este texto brevemente.")

            result = query_ollama(prompt)
            response_text = result.get("response", "")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({
                    "status": "success",
                    "model": MODEL,
                    "respuesta": response_text
                }).encode("utf-8")
            )

        except json.JSONDecodeError as e:
            self._error(400, f"JSON inválido: {e}")
        except urllib.error.URLError as e:
            self._error(503, f"No se puede conectar a Ollama: {e}")
        except Exception as e:
            self._error(500, str(e))

    def _error(self, code: int, msg: str):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode("utf-8"))

    def log_message(self, fmt, *args):
        """Override para formato de log más limpio."""
        print(f"[middleware] {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"[middleware] Activo en puerto {PORT}, modelo: {MODEL}")
    print(f"[middleware] Ollama URL: {OLLAMA_URL}")
    server.serve_forever()
