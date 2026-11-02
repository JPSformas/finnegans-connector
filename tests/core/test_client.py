import json

import httpx2
import pytest

from finnegans_core.client import FinnegansAuthError, FinnegansClient, FinnegansError
from finnegans_core.config import Settings

SECRETO = "c35c93e38ea18d611e5676b448e02ff3"
CID = "94bb5156bbb4a20106433f3112df6cd7"


def _settings(**extra):
    env = {"FINNEGANS_CLIENT_ID": CID, "FINNEGANS_CLIENT_SECRET": SECRETO}
    env.update(extra)
    return Settings.from_env(env)


def _cliente(handler, **extra):
    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return FinnegansClient(_settings(**extra), http=http)


def test_token_texto_plano_y_json():
    c = _cliente(lambda req: httpx2.Response(200, text="abc"))
    assert c.token() == "abc"
    c = _cliente(lambda req: httpx2.Response(200, json={"access_token": "xyz"}))
    assert c.token() == "xyz"


def test_token_pide_credenciales_y_se_cachea():
    vistos = []

    def h(req):
        vistos.append(req)
        return httpx2.Response(200, text="abc")

    c = _cliente(h)
    c.token()
    c.token()
    assert len(vistos) == 1
    q = vistos[0].url.params
    assert vistos[0].url.path == "/api/oauth/token"
    assert q["grant_type"] == "client_credentials"
    assert q["client_id"] == CID and q["client_secret"] == SECRETO
    c.token(forzar=True)
    assert len(vistos) == 2


def test_access_token_va_en_cada_request():
    vistos = []

    def h(req):
        if req.url.path == "/api/oauth/token":
            return httpx2.Response(200, text="abc")
        vistos.append(req)
        return httpx2.Response(200, json={"ok": 1})

    c = _cliente(h)
    assert c.request("GET", "cliente", id="P01093", params={"a": "b"}) == {"ok": 1}
    assert vistos[0].url.path == "/api/cliente/P01093"
    assert vistos[0].url.params["ACCESS_TOKEN"] == "abc"
    assert vistos[0].url.params["a"] == "b"


def test_respuesta_no_json_devuelve_texto():
    def h(req):
        if req.url.path == "/api/oauth/token":
            return httpx2.Response(200, text="abc")
        return httpx2.Response(200, text="hola")

    assert _cliente(h).request("GET", "x") == "hola"


def test_reintenta_una_vez_ante_401():
    tokens = []
    estado = {"n": 0}

    def h(req):
        if req.url.path == "/api/oauth/token":
            tokens.append(1)
            return httpx2.Response(200, text=f"t{len(tokens)}")
        estado["n"] += 1
        if estado["n"] == 1:
            return httpx2.Response(401, text="vencido")
        return httpx2.Response(200, json={"ok": True})

    c = _cliente(h)
    assert c.request("GET", "cliente") == {"ok": True}
    assert len(tokens) == 2


def test_dos_401_levantan_error():
    def h(req):
        if req.url.path == "/api/oauth/token":
            return httpx2.Response(200, text="abc")
        return httpx2.Response(401, text="no")

    with pytest.raises(FinnegansError):
        _cliente(h).request("GET", "cliente")


def test_body_json_en_put():
    vistos = []

    def h(req):
        if req.url.path == "/api/oauth/token":
            return httpx2.Response(200, text="abc")
        vistos.append(req)
        return httpx2.Response(200, json={})

    _cliente(h).request("PUT", "cliente", id="X", body={"Codigo": "X"})
    assert vistos[0].method == "PUT"
    assert vistos[0].headers["content-type"].startswith("application/json")
    assert json.loads(vistos[0].content) == {"Codigo": "X"}


def test_errores_no_filtran_secretos():
    c = _cliente(lambda req: httpx2.Response(401, text=f"denegado {SECRETO}"))
    with pytest.raises(FinnegansAuthError) as e:
        c.token()
    assert SECRETO not in str(e.value) and CID not in str(e.value)
    assert "***" in str(e.value)

    def h(req):
        if req.url.path == "/api/oauth/token":
            return httpx2.Response(200, text="TOKEN-SECRETO-123")
        return httpx2.Response(500, text="fallo ACCESS_TOKEN=TOKEN-SECRETO-123")

    with pytest.raises(FinnegansError) as e:
        _cliente(h).request("GET", "cliente")
    assert "TOKEN-SECRETO-123" not in str(e.value)
    assert "***" in str(e.value)


def test_falla_de_red_no_filtra_secretos():
    def h(req):
        raise httpx2.ConnectError(f"no conecta {req.url}")

    with pytest.raises(FinnegansAuthError) as e:
        _cliente(h).token()
    assert SECRETO not in str(e.value) and CID not in str(e.value)


def test_base_url_invalida_da_error_claro():
    c = _cliente(lambda req: httpx2.Response(200, text="abc"), FINNEGANS_BASE_URL="api.finneg.com")
    with pytest.raises(FinnegansAuthError) as e:
        c.token()
    assert "https://" in str(e.value)
    assert "api.finneg.com" in str(e.value)
    assert SECRETO not in str(e.value) and CID not in str(e.value)


def test_base_url_invalida_en_request():
    c = _cliente(lambda req: httpx2.Response(200, text="abc"), FINNEGANS_BASE_URL="httpsapi.finneg.com")
    with pytest.raises(FinnegansError) as e:
        c.request("GET", "cliente")
    assert "https://" in str(e.value)
