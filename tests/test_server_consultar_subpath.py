import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import server
from finnegans.client import FinnegansClient


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio
        pass

    def do_GET(self):
        if self.path.startswith("/api/cliente/list"):
            body = json.dumps([{"codigo": "P01093", "nombre": "FORMAS PUBLICITARIAS S.A."}])
            self.send_response(200)
        elif self.path.startswith("/api/cliente?") or self.path == "/api/cliente":
            body = json.dumps({"error": "Bad Request: id missing", "status": 400})
            self.send_response(400)
        else:
            body = json.dumps({"error": "Not Found", "status": 404})
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())


class TestConsultarSubpath(unittest.TestCase):
    def setUp(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        # cliente apuntando al stub, con token fijo
        client = FinnegansClient.__new__(FinnegansClient)
        client.settings = type("S", (), {"base_url": f"http://127.0.0.1:{self.port}"})()
        client.timeout = 5
        client._token = "T"
        client._token_ts = 9e18
        client.token_ttl_seconds = 3600
        server._client = client

    def tearDown(self):
        self.httpd.shutdown()
        server._client = None

    def test_list_subpath_trae_datos(self):
        out = server.consultar_finnegans("cliente/list")
        self.assertIn("P01093", out)

    def test_id_missing_da_mensaje_accionable(self):
        out = server.consultar_finnegans("cliente")
        self.assertIn("/list", out)  # sugiere usar la operacion de listado
        self.assertNotIn("id missing", out.lower())
