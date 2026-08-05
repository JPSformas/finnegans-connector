import tempfile
import unittest
from pathlib import Path
import server
from finnegans.audit import AuditLog


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.store = {}

    def request(self, method, endpoint, id=None, params=None, body=None):
        self.calls.append((method, endpoint, id))
        if method == "POST":
            self.store["10"] = body
            return {"Codigo": "10", **(body or {})}
        if method == "GET":
            return self.store.get(id, {"_leido": True, "id": id})
        return {"ok": True}


class TestEjecutarCambio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        server._audit = AuditLog(str(Path(self.dir.name) / "a.jsonl"), "TEST")
        server._changes.__init__()
        self.fake = _FakeClient()
        server._client = self.fake  # inyectar cliente falso

    def tearDown(self):
        server._client = None
        self.dir.cleanup()

    def _preparar(self):
        p = server._changes.prepare(
            api_id="cliente", metodo="POST", resource_id=None, parametros=None,
            body={"Nombre": "X"}, resumen="crear", codigo="4321",
            preview="...", alto_riesgo=False,
        )
        return p.confirmacion_id

    def test_codigo_incorrecto_no_ejecuta(self):
        cid = self._preparar()
        out = server.ejecutar_cambio(cid, "0000")
        self.assertIn("incorrecto", out.lower())
        self.assertEqual(self.fake.calls, [])

    def test_codigo_correcto_ejecuta_y_relee(self):
        cid = self._preparar()
        out = server.ejecutar_cambio(cid, "4321")
        self.assertIn("EJECUTADO", out)
        metodos = [c[0] for c in self.fake.calls]
        self.assertIn("POST", metodos)
        self.assertIn("GET", metodos)  # read-back
        self.assertIn("Verificacion", out)


if __name__ == "__main__":
    unittest.main()
