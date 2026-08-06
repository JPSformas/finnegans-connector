import io
import json
import unittest
from unittest import mock

from finnegans import swagger_catalog as sc


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


if __name__ == "__main__":
    unittest.main()
