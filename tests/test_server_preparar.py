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
        # SPEC (fixture compartida) documenta ClienteBody con Codigo/Nombre/Limite.
        # Si preparar_cambio NO resolviera el schema desde swaggerGlobal
        # (body_schema=None), validar_body devolveria el aviso "(sin schema: ...)"
        # y construir_preview no marcaria ningun campo como "no documentado"
        # (la condicion es `not campos_body or k in campos_body`, y con
        # campos_body=[] esa condicion es siempre verdadera) -> las dos
        # aserciones de abajo fallarian. Eso es lo que hace que este test
        # dependa realmente de la ruta swaggerGlobal, no del eco generico de
        # `datos` en el preview.
        from tests.test_swagger_catalog import SPEC
        sc._SPEC_CACHE.clear()
        sc._fetch_spec = lambda url, key, timeout=60: SPEC  # type: ignore
        out = server.preparar_cambio(
            api_id="cliente", metodo="POST",
            datos={"Codigo": "X", "NoExiste": "Z"}, descripcion="alta test",
        )
        # Prueba que body_schema SE RESOLVIO desde swaggerGlobal: no aparece
        # el aviso de "sin schema" que emite validar_body cuando body_schema
        # es None.
        self.assertNotIn(
            "(sin schema: no se pudo verificar contra la documentacion)", out
        )
        # 'Codigo' esta documentado en ClienteBody -> su linea en el preview
        # NO debe llevar la marca de "campo no documentado".
        linea_codigo = next(l for l in out.splitlines() if "Codigo" in l and l.strip().startswith("-"))
        self.assertNotIn("(campo no documentado)", linea_codigo)
        # 'NoExiste' NO esta documentado en ClienteBody -> su linea en el
        # preview SI debe llevar la marca real que usa construir_preview.
        linea_noexiste = next(l for l in out.splitlines() if "NoExiste" in l and l.strip().startswith("-"))
        self.assertIn("(campo no documentado)", linea_noexiste)


if __name__ == "__main__":
    unittest.main()
