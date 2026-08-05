# tests/test_server_preparar.py
import asyncio
import tempfile
import unittest
from pathlib import Path
import server
from finnegans.audit import AuditLog


class TestPrepararCambio(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        # Redirigir auditoria a temp y forzar settings de prueba
        server._audit = AuditLog(str(Path(self.dir.name) / "a.jsonl"), "TEST")
        server._changes.__init__()  # limpiar pendientes

        async def fake_get_api(api_id):
            return {"request_structure": {"paths": {"/api/cliente": {"post": {
                "requestBodySchema": {"required": ["Codigo"],
                                       "properties": {"Codigo": {"type": "string"}}}}}}}}
        self._orig = server.get_api
        server.get_api = fake_get_api

        class _S:
            allow_delete = False
            high_risk_patterns = []
        server.get_settings = lambda: _S()

    def tearDown(self):
        server.get_api = self._orig
        self.dir.cleanup()

    def test_delete_bloqueado_no_crea_pendiente(self):
        out = asyncio.run(server.preparar_cambio("cliente", "DELETE", id="9"))
        self.assertIn("bloquead", out.lower())
        self.assertEqual(len(server._changes._pending), 0)

    def test_post_crea_pendiente_con_codigo_y_advertencia(self):
        out = asyncio.run(server.preparar_cambio("cliente", "POST", datos={"Nombre": "X"}))
        self.assertIn("CONFIRMACION", out)
        self.assertIn("codigo", out.lower())
        # 'Nombre' no esta en schema, 'Codigo' falta -> advertencias
        self.assertIn("⚠️", out)
        self.assertEqual(len(server._changes._pending), 1)


if __name__ == "__main__":
    unittest.main()
