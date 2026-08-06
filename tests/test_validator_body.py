import unittest
from finnegans.validator import validar_body

SCHEMA = {
    "required": ["Codigo", "Nombre"],
    "properties": {
        "Codigo": {"type": "string"},
        "Nombre": {"type": "string"},
        "Limite": {"type": "number"},
    },
}


class TestValidarBody(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(validar_body({"Codigo": "A", "Nombre": "X"}, SCHEMA), [])

    def test_falta_requerido(self):
        problemas = validar_body({"Codigo": "A"}, SCHEMA)
        self.assertTrue(any("Nombre" in p and "falta" in p.lower() for p in problemas))

    def test_campo_desconocido(self):
        problemas = validar_body({"Codigo": "A", "Nombre": "X", "Inventado": 1}, SCHEMA)
        self.assertTrue(any("Inventado" in p for p in problemas))

    def test_tipo_incorrecto(self):
        problemas = validar_body({"Codigo": "A", "Nombre": "X", "Limite": "cero"}, SCHEMA)
        self.assertTrue(any("Limite" in p for p in problemas))

    def test_sin_schema(self):
        problemas = validar_body({"x": 1}, None)
        self.assertEqual(len(problemas), 1)
        self.assertIn("sin schema", problemas[0].lower())

    def test_bool_para_number_es_error(self):
        problemas = validar_body({"Codigo": "A", "Nombre": "X", "Limite": True}, SCHEMA)
        self.assertTrue(any("Limite" in p for p in problemas))

    def test_number_valido_ok(self):
        self.assertEqual(validar_body({"Codigo": "A", "Nombre": "X", "Limite": 100}, SCHEMA), [])
        self.assertEqual(validar_body({"Codigo": "A", "Nombre": "X", "Limite": 100.5}, SCHEMA), [])

    def test_schema_malformado_no_crashea(self):
        malformado = {"required": [], "properties": {"X": "not-a-dict"}}
        # No debe lanzar excepcion aunque la propiedad no sea un dict.
        try:
            problemas = validar_body({"X": 1}, malformado)
        except Exception as e:  # pragma: no cover
            self.fail(f"validar_body lanzo excepcion con schema malformado: {e}")
        self.assertIsInstance(problemas, list)


if __name__ == "__main__":
    unittest.main()
