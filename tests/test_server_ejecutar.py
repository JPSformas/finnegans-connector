import tempfile
import unittest
from pathlib import Path
import server
from finnegans import FinnegansError
from finnegans.audit import AuditLog


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.store = {}
        self.raise_get_ids = set()  # ids cuyo GET debe lanzar FinnegansError

    def request(self, method, endpoint, id=None, params=None, body=None):
        self.calls.append((method, endpoint, id))
        if method == "POST":
            self.store["10"] = body
            return {"Codigo": "10", **(body or {})}
        if method == "GET":
            if id in self.raise_get_ids:
                raise FinnegansError(f"404 no existe {id}")
            return self.store.get(id, {"_leido": True, "id": id})
        if method == "PUT":
            self.store[id] = body
            return {"ok": True, "id": id}
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

    def test_put_relee_via_get(self):
        p = server._changes.prepare(
            api_id="cliente", metodo="PUT", resource_id="55", parametros=None,
            body={"Nombre": "Editado"}, resumen="editar", codigo="7777",
            preview="...", alto_riesgo=False,
        )
        out = server.ejecutar_cambio(p.confirmacion_id, "7777")
        self.assertIn("EJECUTADO", out)
        # read-back: hubo un GET sobre el id 55
        self.assertIn(("GET", "cliente", "55"), self.fake.calls)
        self.assertIn("Verificacion posterior", out)

    def test_delete_confirma_no_existe(self):
        self.fake.raise_get_ids.add("X")  # el GET de read-back fallara (registro borrado)
        p = server._changes.prepare(
            api_id="cliente", metodo="DELETE", resource_id="X", parametros=None,
            body=None, resumen="borrar", codigo="9999",
            preview="...", alto_riesgo=True,
        )
        out = server.ejecutar_cambio(p.confirmacion_id, "9999")
        self.assertIn("EJECUTADO", out)
        self.assertIn(("GET", "cliente", "X"), self.fake.calls)  # read-back intento el GET
        readback = out.split("Verificacion posterior:", 1)[1]
        self.assertTrue(
            "ya no existe" in readback or "DELETE OK" in readback,
            msg=f"read-back no confirmo el borrado: {readback!r}",
        )


if __name__ == "__main__":
    unittest.main()


class _ClienteQueFalla:
    """Cliente cuyo POST rompe con el error crudo real de la API."""

    CRUDO = 'Error en POST cliente (HTTP 500): {"error":"Internal Server Error"}'

    def __init__(self):
        self.calls = []

    def request(self, method, endpoint, id=None, params=None, body=None):
        self.calls.append((method, endpoint, id))
        raise FinnegansError(self.CRUDO)


class TestEjecutarCambioConError(unittest.TestCase):
    """Un lider tampoco tiene que ver el error crudo cuando falla una escritura."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.log = Path(self.dir.name) / "a.jsonl"
        server._audit = AuditLog(str(self.log), "TEST")
        server._changes.__init__()
        self.fake = _ClienteQueFalla()
        server._client = self.fake

    def tearDown(self):
        server._client = None
        self.dir.cleanup()

    def _ejecutar(self):
        p = server._changes.prepare(
            api_id="cliente", metodo="POST", resource_id=None, parametros=None,
            body={"Nombre": "X"}, resumen="crear", codigo="4321",
            preview="...", alto_riesgo=False,
        )
        return server.ejecutar_cambio(p.confirmacion_id, "4321")

    def test_devuelve_mensaje_traducido_y_no_el_crudo(self):
        out = self._ejecutar()
        self.assertIn("ver_api", out)
        self.assertNotIn("500", out)
        self.assertNotIn("Internal Server Error", out)

    def test_aclara_que_el_cambio_no_se_aplico(self):
        out = self._ejecutar()
        self.assertIn("no se aplico", out.lower())

    def test_la_auditoria_conserva_el_detalle_crudo_para_it(self):
        self._ejecutar()
        self.assertIn("Internal Server Error", self.log.read_text(encoding="utf-8"))
