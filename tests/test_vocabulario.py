"""Vocabulario de negocio: el lider no escribe como se llaman los endpoints.

Tres problemas distintos, verificados contra la API real:
  - acentos:  "tesoreria" se escribe "tesoreria" -> hoy tokeniza como ['tesorer','a']
  - plurales: "cheques" encuentra 2 endpoints, "cheque" ninguno
  - sinonimos: "tesoreria" y "caja" no aparecen en ningun nombre de endpoint
"""
import unittest

from finnegans import vocabulario as v


class TestNormalizar(unittest.TestCase):
    def test_saca_acentos(self):
        self.assertEqual(v.normalizar("tesorería"), "tesoreria")
        self.assertEqual(v.normalizar("Análisis"), "analisis")

    def test_pasa_a_minusculas(self):
        self.assertEqual(v.normalizar("MovimientoFondos"), "movimientofondos")

    def test_deja_la_enie(self):
        # 'n' y 'ñ' son letras distintas: normalizarla cambiaria la palabra.
        self.assertEqual(v.normalizar("año"), "año")

    def test_tolera_vacio(self):
        self.assertEqual(v.normalizar(""), "")
        self.assertEqual(v.normalizar(None), "")


class TestVariantes(unittest.TestCase):
    """Se generan las formas para que consulta y endpoint se encuentren."""

    def test_plural_en_vocal_incluye_el_singular(self):
        self.assertIn("cheque", v.variantes("cheques"))
        self.assertIn("factura", v.variantes("facturas"))

    def test_plural_en_consonante_incluye_el_singular(self):
        self.assertIn("proveedor", v.variantes("proveedores"))

    def test_el_singular_siempre_esta_incluido(self):
        self.assertIn("cheque", v.variantes("cheque"))

    def test_no_mutila_palabras_cortas(self):
        # 'mas', 'dos', 'pos' no deben perder la s y colisionar con todo.
        self.assertEqual(v.variantes("mas"), {"mas"})

    def test_singular_y_plural_se_cruzan(self):
        self.assertTrue(v.variantes("cheque") & v.variantes("cheques"))


class TestSinonimos(unittest.TestCase):
    def test_tesoreria_lleva_al_vocabulario_de_la_api(self):
        self.assertIn("fondos", v.sinonimos_de("tesoreria"))

    def test_funciona_con_acento_en_la_consulta(self):
        self.assertIn("fondos", v.sinonimos_de("tesorería"))

    def test_caja_lleva_a_fondos(self):
        self.assertIn("fondos", v.sinonimos_de("caja"))

    def test_remito_lleva_a_los_nombres_que_finnegans_si_tiene(self):
        # /remito no existe en la API (501): los documentos son despacho y recepcion.
        self.assertTrue({"despacho", "recepcion"} & set(v.sinonimos_de("remito")))

    def test_palabra_sin_sinonimo_devuelve_vacio(self):
        self.assertEqual(v.sinonimos_de("cliente"), ())


class TestDiccionarioBienFormado(unittest.TestCase):
    """Un sinonimo mal escrito no matchea nunca y no se nota."""

    def test_claves_y_valores_normalizados(self):
        for clave, destinos in v.SINONIMOS.items():
            self.assertEqual(clave, v.normalizar(clave), f"clave: {clave}")
            for d in destinos:
                self.assertEqual(d, v.normalizar(d), f"destino de {clave}: {d}")

    def test_ningun_destino_es_una_frase(self):
        for clave, destinos in v.SINONIMOS.items():
            for d in destinos:
                self.assertNotIn(" ", d, f"destino de {clave}: {d}")

    def test_ninguna_clave_se_apunta_a_si_misma(self):
        for clave, destinos in v.SINONIMOS.items():
            self.assertNotIn(clave, destinos, f"clave: {clave}")


if __name__ == "__main__":
    unittest.main()
