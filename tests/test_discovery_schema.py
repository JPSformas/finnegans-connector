# tests/test_discovery_schema.py
import unittest
from finnegans.discovery import extraer_schema_escritura

SPEC = {
    "request_structure": {
        "paths": {
            "/api/cliente": {
                "post": {
                    "summary": "Crear cliente",
                    "parameters": [{"name": "ACCESS_TOKEN"}, {"name": "sucursal", "required": True}],
                    "requestBodySchema": {
                        "required": ["Codigo", "Nombre"],
                        "properties": {
                            "Codigo": {"type": "string"},
                            "Nombre": {"type": "string"},
                            "Limite": {"type": "number"},
                        },
                    },
                }
            }
        }
    }
}


class TestExtraerSchema(unittest.TestCase):
    def test_post_devuelve_campos_y_requeridos(self):
        r = extraer_schema_escritura(SPEC, "POST")
        self.assertEqual(sorted(r["campos_body"]), ["Codigo", "Limite", "Nombre"])
        self.assertEqual(sorted(r["requeridos"]), ["Codigo", "Nombre"])
        nombres_param = [p["nombre"] for p in r["parametros"]]
        self.assertIn("sucursal", nombres_param)
        self.assertNotIn("ACCESS_TOKEN", nombres_param)

    def test_metodo_inexistente_devuelve_vacio(self):
        r = extraer_schema_escritura(SPEC, "DELETE")
        self.assertIsNone(r["body_schema"])
        self.assertEqual(r["campos_body"], [])


if __name__ == "__main__":
    unittest.main()
