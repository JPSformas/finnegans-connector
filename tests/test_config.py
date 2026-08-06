import unittest
from finnegans.config import Settings


class TestSettingsNuevo(unittest.TestCase):
    def _settings(self, env):
        import os
        for k in ("FINNEGANS_OPERATOR", "FINNEGANS_AUDIT_LOG",
                  "FINNEGANS_ALLOW_DELETE", "FINNEGANS_HIGH_RISK_PATTERNS",
                  "FINNEGANS_CLIENT_ID", "FINNEGANS_CLIENT_SECRET",
                  "FINNEGANS_SWAGGER_URL", "FINNEGANS_SWAGGER_KEY"):
            os.environ.pop(k, None)
        os.environ.update(env)
        return Settings(load_env=False)

    def test_operator_y_defaults(self):
        s = self._settings({"FINNEGANS_OPERATOR": "Juan <j@x.com>"})
        self.assertEqual(s.operator, "Juan <j@x.com>")
        self.assertFalse(s.allow_delete)
        self.assertEqual(s.high_risk_patterns, [])
        self.assertTrue(s.audit_log_path)  # tiene default

    def test_allow_delete_truthy(self):
        s = self._settings({"FINNEGANS_ALLOW_DELETE": "true"})
        self.assertTrue(s.allow_delete)

    def test_high_risk_patterns_split(self):
        s = self._settings({"FINNEGANS_HIGH_RISK_PATTERNS": "asiento, factura ,cierre"})
        self.assertEqual(s.high_risk_patterns, ["asiento", "factura", "cierre"])

    def test_swagger_defaults_y_key(self):
        import os
        os.environ.pop("FINNEGANS_SWAGGER_URL", None)
        os.environ.pop("FINNEGANS_SWAGGER_KEY", None)
        s = self._settings({"FINNEGANS_SWAGGER_KEY": "abc123"})
        self.assertEqual(s.swagger_url, "https://oneteam.finneg.com/BSA/api/swaggerGlobal")
        self.assertEqual(s.swagger_key, "abc123")
        s.require_swagger_config()  # no lanza

    def test_require_swagger_config_sin_key_lanza(self):
        import os
        os.environ.pop("FINNEGANS_SWAGGER_KEY", None)
        s = self._settings({})
        with self.assertRaises(RuntimeError):
            s.require_swagger_config()


if __name__ == "__main__":
    unittest.main()
