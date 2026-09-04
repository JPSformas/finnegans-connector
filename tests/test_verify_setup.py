"""El verificador de instalacion no puede decir 'todo OK' con el .env incompleto.

Si falta FINNEGANS_SWAGGER_KEY, buscar_api / ver_api / preparar_cambio fallan,
asi que el verificador tiene que marcarlo como error y no como detalle.
"""
import unittest

import verify_setup


ENV_COMPLETO = """\
FINNEGANS_CLIENT_ID=abc123
FINNEGANS_CLIENT_SECRET=secreto
FINNEGANS_DOCS_CLIENT_ID=doc123
FINNEGANS_DOCS_SECRET_KEY=docsecreto
FINNEGANS_SWAGGER_KEY=435f45445548
"""


def _sin(env: str, variable: str) -> str:
    return "".join(l for l in env.splitlines(keepends=True)
                   if not l.startswith(f"{variable}="))


class TestValidarEnv(unittest.TestCase):
    def test_env_completo_no_da_errores(self):
        self.assertEqual(verify_setup.validar_env(ENV_COMPLETO), [])

    def test_falta_la_swagger_key(self):
        errores = verify_setup.validar_env(_sin(ENV_COMPLETO, "FINNEGANS_SWAGGER_KEY"))
        self.assertEqual(len(errores), 1)
        self.assertIn("FINNEGANS_SWAGGER_KEY", errores[0])

    def test_swagger_key_vacia_tambien_es_error(self):
        env = ENV_COMPLETO.replace("FINNEGANS_SWAGGER_KEY=435f45445548",
                                   "FINNEGANS_SWAGGER_KEY=")
        errores = verify_setup.validar_env(env)
        self.assertEqual(len(errores), 1)
        self.assertIn("FINNEGANS_SWAGGER_KEY", errores[0])

    def test_swagger_key_con_el_valor_de_ejemplo_es_error(self):
        env = ENV_COMPLETO.replace("FINNEGANS_SWAGGER_KEY=435f45445548",
                                   "FINNEGANS_SWAGGER_KEY=tu_swagger_key")
        errores = verify_setup.validar_env(env)
        self.assertEqual(len(errores), 1)
        self.assertIn("ejemplo", errores[0].lower())

    def test_sigue_detectando_las_credenciales_de_api(self):
        errores = verify_setup.validar_env(_sin(ENV_COMPLETO, "FINNEGANS_CLIENT_SECRET"))
        self.assertEqual(len(errores), 1)
        self.assertIn("FINNEGANS_CLIENT_SECRET", errores[0])

    def test_acumula_varios_faltantes(self):
        env = _sin(_sin(ENV_COMPLETO, "FINNEGANS_CLIENT_ID"), "FINNEGANS_SWAGGER_KEY")
        self.assertEqual(len(verify_setup.validar_env(env)), 2)

    def test_env_vacio_reporta_todas_las_requeridas(self):
        errores = verify_setup.validar_env("")
        self.assertEqual(len(errores), len(verify_setup.VARIABLES_REQUERIDAS))


class TestVariablesRequeridas(unittest.TestCase):
    def test_incluye_la_swagger_key(self):
        self.assertIn("FINNEGANS_SWAGGER_KEY", verify_setup.VARIABLES_REQUERIDAS)


if __name__ == "__main__":
    unittest.main()
