# tests/test_server_preparar.py
import tempfile
import unittest
from pathlib import Path
import server
from finnegans import swagger_catalog as sc
from finnegans.audit import AuditLog


class TestPrepararCambio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        # Redirigir auditoria a temp y forzar settings de prueba
        server._audit = AuditLog(str(Path(self.dir.name) / "a.jsonl"), "TEST")
        server._changes.__init__()  # limpiar pendientes

        sc._SPEC_CACHE.clear()
        fake_spec = {"paths": {"/cliente": {"post": {
            "parameters": [{"name": "body", "in": "body", "required": True,
                            "schema": {"required": ["Codigo"],
                                       "properties": {"Codigo": {"type": "string"}}}}]}}}}
        self._orig_fetch_spec = sc._fetch_spec
        sc._fetch_spec = lambda url, key, timeout=60: fake_spec

        class _S:
            allow_delete = False
            high_risk_patterns = []
            swagger_url = "http://x/swaggerGlobal"
            swagger_key = "k"

            def require_swagger_config(self):
                pass
        self._orig_get_settings = server.get_settings
        server.get_settings = lambda: _S()

    def tearDown(self):
        sc._fetch_spec = self._orig_fetch_spec
        sc._SPEC_CACHE.clear()
        server.get_settings = self._orig_get_settings
        self.dir.cleanup()

    def test_delete_bloqueado_no_crea_pendiente(self):
        out = server.preparar_cambio("cliente", "DELETE", id="9")
        self.assertIn("bloquead", out.lower())
        self.assertEqual(len(server._changes._pending), 0)

    def test_post_crea_pendiente_con_codigo_y_advertencia(self):
        out = server.preparar_cambio("cliente", "POST", datos={"Nombre": "X"})
        self.assertIn("CONFIRMACION", out)
        self.assertIn("codigo", out.lower())
        # 'Nombre' no esta en schema, 'Codigo' falta -> advertencias
        self.assertIn("⚠️", out)
        self.assertEqual(len(server._changes._pending), 1)

    def test_preview_usa_campos_de_swaggerglobal(self):
        from tests.test_swagger_catalog import SPEC
        sc._SPEC_CACHE.clear()
        sc._fetch_spec = lambda url, key, timeout=60: SPEC  # type: ignore
        server.get_settings().swagger_key = "k"
        out = server.preparar_cambio(
            api_id="cliente", metodo="POST",
            datos={"Codigo": "X", "Nombre": "Y"}, descripcion="alta test",
        )
        # el preview referencia los campos documentados del body
        self.assertIn("Codigo", out)
        self.assertIn("Nombre", out)


if __name__ == "__main__":
    unittest.main()
