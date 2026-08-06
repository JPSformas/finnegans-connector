import unittest
from finnegans.validator import evaluar_riesgo


class TestEvaluarRiesgo(unittest.TestCase):
    def test_delete_bloqueado_por_defecto(self):
        bloq, alto, motivo = evaluar_riesgo("DELETE", "123", "cliente", False, [])
        self.assertTrue(bloq)
        self.assertIn("DELETE", motivo)

    def test_delete_permitido_si_allow(self):
        bloq, alto, _ = evaluar_riesgo("DELETE", "123", "cliente", True, [])
        self.assertFalse(bloq)
        self.assertTrue(alto)  # borrar sigue siendo alto riesgo

    def test_put_sin_id_es_alto_riesgo(self):
        bloq, alto, motivo = evaluar_riesgo("PUT", None, "cliente", False, [])
        self.assertFalse(bloq)
        self.assertTrue(alto)
        self.assertIn("sin id", motivo.lower())

    def test_patch_sin_id_es_alto_riesgo(self):
        bloq, alto, motivo = evaluar_riesgo("PATCH", None, "cliente", False, [])
        self.assertFalse(bloq)
        self.assertTrue(alto)
        self.assertIn("sin id", motivo.lower())

    def test_patron_alto_riesgo(self):
        bloq, alto, motivo = evaluar_riesgo("POST", None, "asientoContable", False, ["asiento"])
        self.assertTrue(alto)
        self.assertIn("asiento", motivo.lower())

    def test_post_normal_bajo_riesgo(self):
        bloq, alto, _ = evaluar_riesgo("POST", None, "cliente", False, [])
        self.assertFalse(bloq)
        self.assertFalse(alto)


if __name__ == "__main__":
    unittest.main()
