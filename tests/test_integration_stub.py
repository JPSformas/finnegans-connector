# tests/test_integration_stub.py
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import server
from finnegans import swagger_catalog as sc
from finnegans.audit import AuditLog
from finnegans.client import FinnegansClient
from finnegans.config import Settings


class _Handler(BaseHTTPRequestHandler):
    creado = {}

    def _send(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode("utf-8"))

    def log_message(self, *a):  # silenciar
        pass

    def do_GET(self):
        if self.path.startswith("/api/oauth/token"):
            self._send(200, {"access_token": "x" * 36})
        elif "/api/cliente/" in self.path:
            base = self.creado if self.creado else {"_leido": True}
            self._send(200, {**base, "_via_get": "READBACK"})
        else:
            self._send(404, {"error": "no encontrado"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        _Handler.creado = {"Codigo": "77", **body}
        self._send(200, _Handler.creado)


class TestIntegracionStub(unittest.TestCase):
    def setUp(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.port}"

        s = Settings(load_env=False)
        s.base_url = base
        s.client_id = "id"
        s.client_secret = "sec"
        self.dir = tempfile.TemporaryDirectory()

        server._client = FinnegansClient(settings=s)
        server._audit = AuditLog(str(Path(self.dir.name) / "a.jsonl"), "TEST")
        server._changes.__init__()

        class _S:
            allow_delete = False
            high_risk_patterns = []
            swagger_url = "http://x/swaggerGlobal"
            swagger_key = "k"

            def require_swagger_config(self):
                pass
        self._orig_get_settings = server.get_settings
        server.get_settings = lambda: _S()

        sc._SPEC_CACHE.clear()
        fake_spec = {"paths": {"/cliente": {"post": {
            "parameters": [{"name": "body", "in": "body", "required": True,
                            "schema": {"required": ["Nombre"],
                                       "properties": {"Nombre": {"type": "string"}}}}]}}}}
        self._orig_fetch_spec = sc._fetch_spec
        sc._fetch_spec = lambda url, key, timeout=60: fake_spec

    def tearDown(self):
        sc._fetch_spec = self._orig_fetch_spec
        sc._SPEC_CACHE.clear()
        server.get_settings = self._orig_get_settings
        server._client = None
        self.httpd.shutdown()
        self.httpd.server_close()
        self.dir.cleanup()

    def test_ciclo_completo_crear_cliente(self):
        out = server.preparar_cambio("cliente", "POST", datos={"Nombre": "ACME"})
        cid = [l for l in out.splitlines() if l.startswith("confirmacion_id:")][0].split(":")[1].strip()
        codigo = list(server._changes._pending.values())[0].codigo

        res = server.ejecutar_cambio(cid, codigo)
        self.assertIn("EJECUTADO", res)
        readback = res.split("Verificacion posterior:", 1)[1]
        self.assertIn("_via_get", readback)  # prueba que _read_back re-leyo via GET
        self.assertIn("77", readback)  # y que leyo el registro creado


if __name__ == "__main__":
    unittest.main()
