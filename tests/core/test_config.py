from finnegans_core.config import Settings
from finnegans_core.secretos import Redactor


def test_from_env_usa_defaults_y_no_explota_sin_claves():
    s = Settings.from_env({})
    assert s.base_url == "https://api.finneg.com"
    assert s.swagger_url == "https://oneteam.finneg.com/BSA/api/swaggerGlobal"
    assert s.docs_mcp_url.startswith("https://services.finneg.com/")
    assert s.export_dir.replace("\\", "/").endswith("Documents/Finnegans")
    assert s.faltantes() == [
        "Client ID de Finnegans",
        "Client secret de Finnegans",
        "Clave del swagger",
        "Client ID de la documentación",
        "Secret key de la documentación",
    ]
    assert s.secretos() == []


def test_from_env_lee_las_variables():
    s = Settings.from_env({
        "FINNEGANS_CLIENT_ID": "id1",
        "FINNEGANS_CLIENT_SECRET": "sec1",
        "FINNEGANS_SWAGGER_KEY": "sw1",
        "FINNEGANS_DOCS_CLIENT_ID": "did",
        "FINNEGANS_DOCS_SECRET_KEY": "dsk",
        "FINNEGANS_EXPORT_DIR": "C:/export",
        "FINNEGANS_BASE_URL": "https://otra.example",
    })
    assert s.faltantes() == []
    assert s.secretos() == ["id1", "sec1", "sw1", "did", "dsk"]
    assert s.export_dir == "C:/export"
    assert s.base_url == "https://otra.example"


def test_faltantes_ignora_espacios():
    s = Settings.from_env({"FINNEGANS_CLIENT_ID": "  ", "FINNEGANS_CLIENT_SECRET": "x"})
    assert s.faltantes()[0] == "Client ID de Finnegans"
    assert "Client secret de Finnegans" not in s.faltantes()


def test_redactor_reemplaza_mas_largo_primero():
    r = Redactor(["abc", "abcdef", ""])
    assert r.limpiar("x abcdef y abc") == "x *** y ***"
    r.agregar("tok")
    assert r.limpiar(ValueError("hay tok")) == "hay ***"
