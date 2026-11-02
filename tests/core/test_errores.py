"""Traduccion de errores crudos de Finnegans a mensajes accionables.

El lider no tiene que ver un HTTP 405 con un JSON adentro: tiene que leer
que hacer a continuacion.
"""
import unittest

from finnegans_core.errores import traducir_error


# Mensajes crudos reales, tal como los arma FinnegansClient.request().
CRUDO_TRANSACCION = (
    'Error en GET movimientoFondos/list (HTTP 405): '
    '{"error":"Method Not Allowed: No se puede hacer list sobre una transaccion","status":405}'
)
CRUDO_ID_MISSING = (
    'Error en GET cliente (HTTP 400): {"error":"Bad Request: id missing","status":400}'
)
CRUDO_404 = 'Error en GET cliente (HTTP 404): {"error":"Not Found","status":404}'
CRUDO_401 = 'Error en GET cliente (HTTP 401): {"error":"Unauthorized","status":401}'
CRUDO_500 = 'Error en GET reports/MOVINT (HTTP 500): {"error":"Internal Server Error"}'
CRUDO_SIN_RED = 'No se pudo conectar a Finnegans (cliente): <urlopen error timed out>'


class TestTransaccionNoSeLista(unittest.TestCase):
    """El caso mas comun: pedir /list sobre un documento."""

    def setUp(self):
        self.msg = traducir_error("movimientoFondos/list", CRUDO_TRANSACCION)

    def test_explica_que_es_una_transaccion(self):
        self.assertIn("transaccion", self.msg.lower())

    def test_nombra_el_recurso_sin_el_sufijo_list(self):
        self.assertIn("movimientoFondos", self.msg)
        self.assertNotIn("movimientoFondos/list", self.msg)

    def test_indica_el_reporte_alternativo_y_su_parametro(self):
        self.assertIn("reports/DETALLETRANSACCIONES", self.msg)
        self.assertIn("PARAM_Categoria", self.msg)

    def test_indica_donde_sacar_la_categoria(self):
        self.assertIn("reports/CATEGORIASDOCUMENTOSAPI", self.msg)

    def test_no_filtra_el_error_crudo(self):
        self.assertNotIn("405", self.msg)
        self.assertNotIn("Method Not Allowed", self.msg)


class TestOtrosErrores(unittest.TestCase):
    def test_id_missing_pide_el_codigo_y_ofrece_el_listado(self):
        msg = traducir_error("cliente", CRUDO_ID_MISSING)
        self.assertIn("cliente/list", msg)
        self.assertNotIn("id missing", msg.lower())

    def test_404_dice_que_no_existe_e_incluye_el_codigo_buscado(self):
        msg = traducir_error("cliente", CRUDO_404, id="P99999")
        self.assertIn("P99999", msg)
        self.assertIn("no existe", msg.lower())
        self.assertNotIn("404", msg)

    def test_credenciales_rechazadas_manda_a_it(self):
        msg = traducir_error("cliente", CRUDO_401)
        self.assertIn("credenciales", msg.lower())
        self.assertIn("IT", msg)
        self.assertNotIn("401", msg)

    def test_500_sugiere_revisar_parametros_con_ver_endpoint(self):
        msg = traducir_error("reports/MOVINT", CRUDO_500)
        self.assertIn("ver_endpoint", msg)
        self.assertIn("parametro", msg.lower())
        self.assertNotIn("500", msg)

    def test_sin_conexion_habla_de_conexion_y_no_de_urlopen(self):
        msg = traducir_error("cliente", CRUDO_SIN_RED)
        self.assertIn("conect", msg.lower())
        self.assertNotIn("urlopen", msg)


class TestErrorDesconocido(unittest.TestCase):
    """Nunca devolver el crudo pelado, pero no perder el detalle para IT."""

    CRUDO = 'Error en GET raro (HTTP 418): {"error":"I am a teapot","status":418}'

    def test_da_un_mensaje_en_castellano_antes_del_detalle(self):
        msg = traducir_error("raro", self.CRUDO)
        self.assertTrue(msg.lower().startswith("no pude"), msg)

    def test_conserva_el_detalle_tecnico_etiquetado(self):
        msg = traducir_error("raro", self.CRUDO)
        self.assertIn("Detalle tecnico", msg)
        self.assertIn("418", msg)

    def test_recorta_un_detalle_larguisimo(self):
        crudo = "Error en GET raro (HTTP 418): " + ("x" * 5000)
        msg = traducir_error("raro", crudo)
        self.assertLess(len(msg), 1000)


class TestSiempreDevuelveAlgoUtil(unittest.TestCase):
    def test_mensaje_vacio_no_rompe(self):
        self.assertTrue(traducir_error("cliente", ""))

    def test_ningun_caso_devuelve_el_crudo_tal_cual(self):
        for crudo in (CRUDO_TRANSACCION, CRUDO_ID_MISSING, CRUDO_404,
                      CRUDO_401, CRUDO_500, CRUDO_SIN_RED):
            self.assertNotEqual(traducir_error("x", crudo), crudo)


if __name__ == "__main__":
    unittest.main()


# Variantes reales del mismo problema, verificadas contra la API:
#   facturaVenta/list, pedidoVenta/list -> "Esta api no soporta list"
#   remito/list                         -> "No se pudo encontrar la api"
CRUDO_NO_SOPORTA_LIST = (
    'Error en GET facturaVenta/list (HTTP 405): '
    '{"error":"Method Not Allowed: Esta api no soporta list","status":405}'
)
CRUDO_API_INEXISTENTE = (
    'Error en GET remito/list (HTTP 501): '
    '{"error":"Not Implemented: No se pudo encontrar la api","status":501}'
)


class TestApiSinListado(unittest.TestCase):
    """Mismo problema del lider que la transaccion, pero otro texto de la API."""

    def setUp(self):
        self.msg = traducir_error("facturaVenta/list", CRUDO_NO_SOPORTA_LIST)

    def test_deriva_al_mismo_reporte(self):
        self.assertIn("reports/DETALLETRANSACCIONES", self.msg)
        self.assertIn("PARAM_Categoria", self.msg)

    def test_no_afirma_que_sea_una_transaccion(self):
        # La API no lo dice, asi que el mensaje no lo puede inventar.
        self.assertNotIn("es una transaccion", self.msg)

    def test_no_filtra_el_error_crudo(self):
        self.assertNotIn("405", self.msg)
        self.assertNotIn("no soporta list", self.msg)


class TestApiInexistente(unittest.TestCase):
    def setUp(self):
        self.msg = traducir_error("remito/list", CRUDO_API_INEXISTENTE)

    def test_manda_a_buscar_el_nombre_correcto(self):
        self.assertIn("buscar_endpoint", self.msg)

    def test_nombra_lo_que_se_pidio(self):
        self.assertIn("remito", self.msg)

    def test_no_filtra_el_error_crudo(self):
        self.assertNotIn("501", self.msg)
        self.assertNotIn("Not Implemented", self.msg)


class TestCredencialesYPermisos(unittest.TestCase):
    def test_401_nombra_los_campos_del_formulario_y_no_variables(self):
        msg = traducir_error("cliente", CRUDO_401)
        self.assertIn("Client ID de Finnegans", msg)
        self.assertIn("Client secret de Finnegans", msg)
        self.assertIn("configuracion de la extension", msg)
        self.assertNotIn("FINNEGANS_", msg)

    def test_403_en_lectura_tambien_son_credenciales(self):
        crudo = 'Error en GET cliente (HTTP 403): {"error":"Forbidden"}'
        msg = traducir_error("cliente", crudo)
        self.assertIn("credenciales", msg.lower())
        self.assertNotIn("FINNEGANS_", msg)

    def test_403_en_escritura_es_falta_de_permiso_no_credenciales(self):
        for metodo in ("POST", "PUT", "PATCH", "DELETE"):
            crudo = f'Error en {metodo} cliente (HTTP 403): {{"error":"Forbidden"}}'
            msg = traducir_error("cliente", crudo, id="C1")
            self.assertIn("permiso", msg.lower(), metodo)
            self.assertIn(metodo, msg)
            self.assertIn("'cliente'", msg)
            self.assertNotIn("rechazo las credenciales", msg)
            self.assertNotIn("FINNEGANS_", msg)


class TestDetalleDel500EnEscrituras(unittest.TestCase):
    RECHAZO = "No se puede mezclar Convenio Multilateral con Local en ControlImpositivo1"

    def test_500_en_escritura_muestra_lo_que_dijo_la_api(self):
        crudo = f'Error en PUT cliente (HTTP 500): {{"error":"{self.RECHAZO}"}}'
        msg = traducir_error("cliente", crudo, id="C1")
        self.assertIn("Finnegans no pudo procesar la operacion sobre 'cliente'", msg)
        self.assertIn(self.RECHAZO, msg)
        self.assertIn("La API respondio", msg)

    def test_500_en_escritura_corta_el_detalle_a_300(self):
        crudo = "Error en POST cliente (HTTP 500): " + ("q" * 5000)
        msg = traducir_error("cliente", crudo)
        detalle = msg.split("La API respondio: ", 1)[1]
        self.assertLessEqual(len(detalle.rstrip("…")), 300)
        self.assertLess(len(msg), 800)

    def test_500_en_lectura_no_agrega_el_detalle(self):
        msg = traducir_error("reports/MOVINT", CRUDO_500)
        self.assertNotIn("La API respondio", msg)
        self.assertNotIn("Internal Server Error", msg)

    def test_500_en_escritura_sin_cuerpo_no_agrega_nada(self):
        msg = traducir_error("cliente", "Error en DELETE cliente (HTTP 500): ")
        self.assertNotIn("La API respondio", msg)
