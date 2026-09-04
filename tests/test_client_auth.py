"""La autenticacion no puede filtrar el client_secret en los errores.

El token se pide con las credenciales en el query string, asi que cualquier
excepcion que incluya la URL las deja en la pantalla, en el log de la
instalacion y en cualquier traceback que el usuario reenvie.
"""
import unittest
import urllib.error
from unittest import mock

from finnegans.client import FinnegansAuthError, FinnegansClient


SECRETO = "c35c93e38ea18d611e5676b448e02ff3"
ID = "94bb5156bbb4a20106433f3112df6cd7"


def _cliente(base_url: str) -> FinnegansClient:
    c = FinnegansClient.__new__(FinnegansClient)
    c.settings = type("S", (), {
        "base_url": base_url,
        "client_id": ID,
        "client_secret": SECRETO,
    })()
    c.timeout = 5
    c._token = None
    c._token_ts = 0.0
    c.token_ttl_seconds = 3600
    return c


class TestBaseUrlMalformada(unittest.TestCase):
    """Caso real: el .env llego con 'httpsapi.finneg.com' (sin '://')."""

    def test_da_un_error_claro_y_no_un_traceback_de_urllib(self):
        with self.assertRaises(FinnegansAuthError) as ctx:
            _cliente("httpsapi.finneg.com").get_token()
        self.assertIn("FINNEGANS_BASE_URL", str(ctx.exception))

    def test_el_mensaje_no_filtra_las_credenciales(self):
        with self.assertRaises(FinnegansAuthError) as ctx:
            _cliente("httpsapi.finneg.com").get_token()
        self.assertNotIn(SECRETO, str(ctx.exception))
        self.assertNotIn(ID, str(ctx.exception))

    def test_muestra_el_valor_recibido_para_poder_corregirlo(self):
        with self.assertRaises(FinnegansAuthError) as ctx:
            _cliente("httpsapi.finneg.com").get_token()
        self.assertIn("httpsapi.finneg.com", str(ctx.exception))

    def test_base_url_vacia_tambien_avisa(self):
        with self.assertRaises(FinnegansAuthError) as ctx:
            _cliente("").get_token()
        self.assertIn("FINNEGANS_BASE_URL", str(ctx.exception))

    def test_acepta_http_y_https(self):
        for base in ("https://api.finneg.com", "http://localhost:8080"):
            with mock.patch("finnegans.client.urllib.request.urlopen",
                            side_effect=OSError("sin red")):
                with self.assertRaises(FinnegansAuthError) as ctx:
                    _cliente(base).get_token()
            self.assertNotIn("FINNEGANS_BASE_URL", str(ctx.exception), base)


class TestErroresDeRedNoFiltranNada(unittest.TestCase):
    def test_falla_de_conexion(self):
        with mock.patch("finnegans.client.urllib.request.urlopen",
                        side_effect=OSError(f"algo con {SECRETO} adentro")):
            with self.assertRaises(FinnegansAuthError) as ctx:
                _cliente("https://api.finneg.com").get_token()
        self.assertNotIn(SECRETO, str(ctx.exception))

    def test_url_invalida_que_urllib_rechaza(self):
        # ValueError no estaba en ningun except y se propagaba cruda, con la
        # URL completa -- credenciales incluidas -- en el mensaje.
        with mock.patch("finnegans.client.urllib.request.urlopen",
                        side_effect=ValueError(f"unknown url type: {SECRETO}")):
            with self.assertRaises(FinnegansAuthError) as ctx:
                _cliente("https://api.finneg.com").get_token()
        self.assertNotIn(SECRETO, str(ctx.exception))

    def test_http_error_con_las_credenciales_en_el_cuerpo(self):
        err = urllib.error.HTTPError(
            f"https://api.finneg.com/api/oauth/token?client_secret={SECRETO}",
            401, "Unauthorized", {}, None)
        err.read = lambda: f"denegado para {SECRETO}".encode()
        with mock.patch("finnegans.client.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(FinnegansAuthError) as ctx:
                _cliente("https://api.finneg.com").get_token()
        self.assertNotIn(SECRETO, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


TOKEN = "455213cc-f8e5-483f-bd75-83c0cf9f4c3b"


def _cliente_con_token(base_url: str) -> FinnegansClient:
    c = _cliente(base_url)
    c._token = TOKEN
    c._token_ts = 9e18
    return c


class TestConsultasNoFiltranElToken(unittest.TestCase):
    """request() manda el ACCESS_TOKEN en el query string: mismo riesgo."""

    def test_base_url_malformada_da_un_error_claro(self):
        from finnegans.client import FinnegansError
        with self.assertRaises(FinnegansError) as ctx:
            _cliente_con_token("httpsapi.finneg.com").get("cliente", id="P01093")
        self.assertIn("FINNEGANS_BASE_URL", str(ctx.exception))

    def test_base_url_malformada_no_filtra_el_token(self):
        from finnegans.client import FinnegansError
        with self.assertRaises(FinnegansError) as ctx:
            _cliente_con_token("httpsapi.finneg.com").get("cliente", id="P01093")
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_falla_de_red_con_la_url_en_el_mensaje(self):
        from finnegans.client import FinnegansError
        detalle = f"<urlopen error para https://api.finneg.com/api/cliente?ACCESS_TOKEN={TOKEN}>"
        with mock.patch("finnegans.client.urllib.request.urlopen",
                        side_effect=OSError(detalle)):
            with self.assertRaises(FinnegansError) as ctx:
                _cliente_con_token("https://api.finneg.com").get("cliente")
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_cuerpo_de_error_con_el_token_adentro(self):
        from finnegans.client import FinnegansError
        err = urllib.error.HTTPError("https://x", 500, "err", {}, None)
        err.read = lambda: f"fallo con ACCESS_TOKEN={TOKEN}".encode()
        with mock.patch("finnegans.client.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(FinnegansError) as ctx:
                _cliente_con_token("https://api.finneg.com").get("cliente")
        self.assertNotIn(TOKEN, str(ctx.exception))
