import unittest
from finnegans.validator import (
    ChangeStore, ValidationError, construir_preview, generar_codigo,
)


class TestPreviewYStore(unittest.TestCase):
    def test_generar_codigo_4_digitos(self):
        c = generar_codigo()
        self.assertTrue(c.isdigit())
        self.assertEqual(len(c), 4)

    def test_preview_marca_problemas_y_codigo(self):
        txt = construir_preview(
            "cliente", "POST", None, {}, {"Nombre": "X"},
            campos_body=["Codigo", "Nombre"],
            problemas=["Falta el campo requerido 'Codigo'."],
            alto_riesgo=False, motivo="operacion estandar", codigo="4271",
        )
        self.assertIn("cliente", txt)
        self.assertIn("POST", txt)
        self.assertIn("Codigo", txt)
        self.assertIn("4271", txt)
        self.assertIn("Falta el campo requerido", txt)

    def test_consume_requiere_codigo_correcto(self):
        store = ChangeStore()
        p = store.prepare(
            api_id="cliente", metodo="POST", resource_id=None, parametros={},
            body={"Codigo": "A"}, resumen="crear", codigo="1234",
            preview="...", alto_riesgo=False,
        )
        with self.assertRaises(ValidationError):
            store.consume(p.confirmacion_id, "0000")  # codigo incorrecto
        # el correcto consume una sola vez
        again = store.consume(p.confirmacion_id, "1234")
        self.assertEqual(again.api_id, "cliente")
        with self.assertRaises(ValidationError):
            store.consume(p.confirmacion_id, "1234")  # ya consumido


if __name__ == "__main__":
    unittest.main()
