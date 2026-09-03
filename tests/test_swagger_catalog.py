import io
import json
import unittest
from unittest import mock

from finnegans import swagger_catalog as sc


SPEC = {
    "swagger": "2.0",
    "basePath": "/api",
    "definitions": {
        "ClienteBody": {
            "type": "object",
            "required": ["Codigo", "Nombre"],
            "properties": {
                "Codigo": {"type": "string"},
                "Nombre": {"type": "string"},
                "Limite": {"type": "number"},
            },
        }
    },
    "paths": {
        "/cliente/list": {"get": {"tags": ["cliente"], "summary": "Listar cliente",
            "operationId": "cliente_list",
            "parameters": [{"name": "ACCESS_TOKEN", "in": "query", "required": True}]}},
        "/cliente/{codigo}": {"get": {"tags": ["cliente"], "summary": "Obtener cliente por ID",
            "operationId": "cliente_get",
            "parameters": [{"name": "codigo", "in": "path", "required": True},
                           {"name": "ACCESS_TOKEN", "in": "query", "required": True}]}},
        "/cliente": {"post": {"tags": ["cliente"], "summary": "Crear cliente",
            "operationId": "cliente_post",
            "parameters": [{"name": "ACCESS_TOKEN", "in": "query", "required": True},
                           {"name": "body", "in": "body", "required": True,
                            "schema": {"$ref": "#/definitions/ClienteBody"}}]}},
        "/reports/analisisFacturaVenta": {"get": {"tags": ["reports", "VENTAS"],
            "summary": "Analisis de facturas de venta",
            "operationId": "reports_analisisFacturaVenta",
            "parameters": [{"name": "ACCESS_TOKEN", "in": "query", "required": True},
                           {"name": "FechaDesde", "in": "query", "required": False,
                            "description": "Filtrar por fecha desde"}]}},
    },
}


class TestFetchSpec(unittest.TestCase):
    def test_arma_url_con_key_y_parsea_json(self):
        """Verifica que _fetch_spec construye la URL con key URL-encoded y parsea JSON."""

        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        spec_json = json.dumps({"swagger": "2.0", "paths": {}})
        fake_response = FakeResponse(spec_json.encode("utf-8"))

        with mock.patch("finnegans.swagger_catalog.urllib.request.urlopen") as mock_urlopen:
            # Configure the mock to be a context manager
            mock_urlopen.return_value = fake_response

            spec = sc._fetch_spec("http://x/swaggerGlobal", "k e/y")

            # Captura el Request objeto que fue pasado
            self.assertTrue(mock_urlopen.called, "urlopen was not called")
            called_req = mock_urlopen.call_args[0][0]
            called_url = called_req.get_full_url()

        # Verifica URL con key URL-encoded
        self.assertIn("key=k%20e%2Fy", called_url)
        # Verifica JSON parseado
        self.assertEqual(spec, {"swagger": "2.0", "paths": {}})


class TestCargarSpec(unittest.TestCase):
    def setUp(self):
        sc._SPEC_CACHE.clear()
        self._calls = []
        self._orig_fetch_spec = sc._fetch_spec

    def tearDown(self):
        sc._fetch_spec = self._orig_fetch_spec

    def _fake_fetch(self, url, key, timeout=60):
        self._calls.append((url, key))
        return {"swagger": "2.0", "paths": {}}

    def test_cachea_tras_primera_carga(self):
        sc._fetch_spec = self._fake_fetch  # type: ignore
        a = sc.cargar_spec("http://x/swaggerGlobal", "k")
        b = sc.cargar_spec("http://x/swaggerGlobal", "k")
        self.assertIs(a, b)
        self.assertEqual(len(self._calls), 1)  # una sola llamada de red

    def test_force_recarga(self):
        sc._fetch_spec = self._fake_fetch  # type: ignore
        sc.cargar_spec("http://x/swaggerGlobal", "k")
        sc.cargar_spec("http://x/swaggerGlobal", "k", force=True)
        self.assertEqual(len(self._calls), 2)

    def test_error_de_red_es_swaggererror(self):
        def boom(url, key, timeout=60):
            raise OSError("sin red")
        sc._fetch_spec = boom  # type: ignore
        with self.assertRaises(sc.SwaggerError):
            sc.cargar_spec("http://x/swaggerGlobal", "k", force=True)


class TestBuscarEndpoints(unittest.TestCase):
    def test_encuentra_cliente_y_rankea(self):
        r = sc.buscar_endpoints(SPEC, "cliente")
        paths = [x["path"] for x in r]
        self.assertIn("/cliente/list", paths)
        self.assertIn("/cliente/{codigo}", paths)
        self.assertTrue(all(x["score"] > 0 for x in r))

    def test_encuentra_reporte_por_venta(self):
        r = sc.buscar_endpoints(SPEC, "factura de venta")
        self.assertIn("/reports/analisisFacturaVenta", [x["path"] for x in r])

    def test_sin_coincidencias_devuelve_vacio(self):
        self.assertEqual(sc.buscar_endpoints(SPEC, "zzz-inexistente"), [])


class TestVerEndpoint(unittest.TestCase):
    def test_operaciones_de_cliente(self):
        ops = sc.ver_endpoint(SPEC, "cliente")
        pares = {(o["metodo"], o["path"]) for o in ops}
        self.assertIn(("GET", "/cliente/list"), pares)
        self.assertIn(("GET", "/cliente/{codigo}"), pares)
        self.assertIn(("POST", "/cliente"), pares)

    def test_params_excluyen_access_token_y_body(self):
        ops = sc.ver_endpoint(SPEC, "cliente")
        get_id = next(o for o in ops if o["path"] == "/cliente/{codigo}")
        nombres = [p["nombre"] for p in get_id["parametros"]]
        self.assertIn("codigo", nombres)
        self.assertNotIn("ACCESS_TOKEN", nombres)

    def test_body_schema_resuelto_por_ref(self):
        ops = sc.ver_endpoint(SPEC, "cliente")
        post = next(o for o in ops if o["metodo"] == "POST")
        self.assertTrue(post["tiene_body"])
        self.assertEqual(sorted(post["body_campos"]), ["Codigo", "Limite", "Nombre"])
        self.assertEqual(sorted(post["body_requeridos"]), ["Codigo", "Nombre"])

    def test_recurso_por_path_exacto_de_reporte(self):
        ops = sc.ver_endpoint(SPEC, "reports/analisisFacturaVenta")
        self.assertEqual(len(ops), 1)
        params = [p["nombre"] for p in ops[0]["parametros"]]
        self.assertIn("FechaDesde", params)


if __name__ == "__main__":
    unittest.main()


# --- Refs externas de body (Finnegans no usa "#/definitions/..." para los VO) ---

VO_CLIENTE = {
    "required": ["Codigo", "Nombre", "Percepciones"],
    "properties": {
        "Codigo": {"type": "string"},
        "Nombre": {"type": "string"},
        "Descripcion": {"type": "string"},
        "Percepciones": {"type": "array"},
    },
}

REF_EXTERNA = "/BSA/api/swaggerApi?key=abc123&api=cliente&nombreVO=ClienteVO"

SPEC_REF_EXTERNA = {
    "swagger": "2.0",
    sc._SOURCE_URL_KEY: "https://oneteam.finneg.com/BSA/api/swaggerGlobal",
    "paths": {
        "/cliente/{codigo}": {
            "put": {
                "tags": ["cliente"], "summary": "cliente",
                "parameters": [
                    {"name": "ACCESS_TOKEN", "in": "query", "required": True},
                    {"name": "ClienteVO", "in": "body", "required": True,
                     "schema": {"$ref": REF_EXTERNA}},
                ],
            }
        }
    },
}


def _fake_urlopen(payload):
    """Devuelve un urlopen falso que responde payload como JSON."""
    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    return mock.Mock(return_value=FakeResponse(json.dumps(payload).encode("utf-8")))


class TestRefExterna(unittest.TestCase):
    def setUp(self):
        sc._VO_CACHE.clear()

    def test_resolver_ref_baja_el_schema_del_host_del_spec(self):
        with mock.patch("finnegans.swagger_catalog.urllib.request.urlopen",
                        _fake_urlopen(VO_CLIENTE)) as fake:
            schema = sc.resolver_ref(SPEC_REF_EXTERNA, {"$ref": REF_EXTERNA})
        self.assertEqual(sorted(schema["properties"]), sorted(VO_CLIENTE["properties"]))
        url = fake.call_args[0][0].full_url
        self.assertEqual(url, "https://oneteam.finneg.com" + REF_EXTERNA)

    def test_ver_endpoint_expone_campos_y_requeridos_del_vo(self):
        with mock.patch("finnegans.swagger_catalog.urllib.request.urlopen",
                        _fake_urlopen(VO_CLIENTE)):
            ops = sc.ver_endpoint(SPEC_REF_EXTERNA, "cliente")
        put = next(o for o in ops if o["metodo"] == "PUT")
        self.assertTrue(put["tiene_body"])
        self.assertTrue(put["body_schema_ok"])
        self.assertIn("Descripcion", put["body_campos"])
        self.assertIn("Codigo", put["body_requeridos"])

    def test_cachea_el_vo_y_no_lo_baja_dos_veces(self):
        fake = _fake_urlopen(VO_CLIENTE)
        with mock.patch("finnegans.swagger_catalog.urllib.request.urlopen", fake):
            sc.resolver_ref(SPEC_REF_EXTERNA, {"$ref": REF_EXTERNA})
            sc.resolver_ref(SPEC_REF_EXTERNA, {"$ref": REF_EXTERNA})
        self.assertEqual(fake.call_count, 1)

    def test_si_falla_la_bajada_degrada_con_body_schema_ok_false(self):
        with mock.patch("finnegans.swagger_catalog.urllib.request.urlopen",
                        side_effect=OSError("sin red")):
            ops = sc.ver_endpoint(SPEC_REF_EXTERNA, "cliente")
        put = next(o for o in ops if o["metodo"] == "PUT")
        self.assertTrue(put["tiene_body"])
        self.assertFalse(put["body_schema_ok"])
        self.assertEqual(put["body_campos"], [])

    def test_ref_interna_sigue_funcionando(self):
        ops = sc.ver_endpoint(SPEC, "cliente")
        post = next(o for o in ops if o["metodo"] == "POST")
        self.assertTrue(post["body_schema_ok"])
        self.assertIn("Codigo", post["body_campos"])
        self.assertIn("Nombre", post["body_requeridos"])

    def test_cargar_spec_guarda_la_url_de_origen(self):
        sc._SPEC_CACHE.clear()
        with mock.patch("finnegans.swagger_catalog._fetch_spec", return_value={"paths": {}}):
            spec = sc.cargar_spec("https://oneteam.finneg.com/BSA/api/swaggerGlobal", "k")
        self.assertEqual(spec[sc._SOURCE_URL_KEY],
                         "https://oneteam.finneg.com/BSA/api/swaggerGlobal")
