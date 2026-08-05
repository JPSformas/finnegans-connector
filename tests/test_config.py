import unittest
from finnegans.config import Settings


class TestSettingsNuevo(unittest.TestCase):
    def _settings(self, env):
        import os
        for k in ("FINNEGANS_OPERATOR", "FINNEGANS_AUDIT_LOG",
                  "FINNEGANS_ALLOW_DELETE", "FINNEGANS_HIGH_RISK_PATTERNS",
                  "FINNEGANS_CLIENT_ID", "FINNEGANS_CLIENT_SECRET"):
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


if __name__ == "__main__":
    unittest.main()
