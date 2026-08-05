import json
import tempfile
import unittest
from pathlib import Path
from finnegans.audit import AuditLog


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self.dir.name) / "sub" / "audit.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def test_crea_directorio_y_escribe_linea(self):
        log = AuditLog(self.path, "Juan <j@x.com>")
        log.record("preparado", metodo="POST", api_id="cliente")
        lines = Path(self.path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["evento"], "preparado")
        self.assertEqual(rec["operador"], "Juan <j@x.com>")
        self.assertEqual(rec["metodo"], "POST")
        self.assertIn("timestamp", rec)

    def test_append_no_sobreescribe(self):
        log = AuditLog(self.path, "op")
        log.record("preparado", api_id="a")
        log.record("ejecutado", api_id="a", resultado="OK")
        lines = Path(self.path).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_nunca_loguea_access_token(self):
        log = AuditLog(self.path, "op")
        log.record("preparado", api_id="cliente",
                   parametros={"ACCESS_TOKEN": "SECRETO123", "Estado": "activo"})
        content = Path(self.path).read_text(encoding="utf-8")
        self.assertNotIn("SECRETO123", content)
        self.assertIn("Estado", content)

    def test_redacta_token_anidado_en_dict(self):
        log = AuditLog(self.path, "op")
        log.record("preparado", api_id="cliente",
                   parametros={"credenciales": {"token": "SECRETONESTED1"}})
        content = Path(self.path).read_text(encoding="utf-8")
        self.assertNotIn("SECRETONESTED1", content)
        self.assertIn("credenciales", content)

    def test_redacta_password_anidado_en_lista(self):
        log = AuditLog(self.path, "op")
        log.record("preparado", api_id="cliente",
                   body={"items": [{"password": "SECRETONESTED2"}]})
        content = Path(self.path).read_text(encoding="utf-8")
        self.assertNotIn("SECRETONESTED2", content)

    def test_redacta_token_en_tupla(self):
        log = AuditLog(self.path, "op")
        log.record("preparado", api_id="cliente",
                   body=({"token": "SECRETOTUPLE"},))
        content = Path(self.path).read_text(encoding="utf-8")
        self.assertNotIn("SECRETOTUPLE", content)


if __name__ == "__main__":
    unittest.main()
