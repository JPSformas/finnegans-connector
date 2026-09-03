# tests/test_install.py
import unittest
from install import render_env, upsert_mcp_entry


class TestInstall(unittest.TestCase):
    def test_render_env_inserta_operador(self):
        tpl = "FINNEGANS_CLIENT_ID=abc\nFINNEGANS_OPERATOR=\n"
        out = render_env(tpl, "Juan <j@x.com>")
        self.assertIn("FINNEGANS_OPERATOR=Juan <j@x.com>", out)
        self.assertIn("FINNEGANS_CLIENT_ID=abc", out)

    def test_upsert_crea_y_actualiza(self):
        cfg = {}
        cfg = upsert_mcp_entry(cfg, "python.exe", "C:\\x\\server.py", "C:\\x")
        self.assertIn("finnegans-agent", cfg["mcpServers"])
        # idempotente: no duplica
        cfg2 = upsert_mcp_entry(cfg, "python.exe", "C:\\x\\server.py", "C:\\x")
        self.assertEqual(len(cfg2["mcpServers"]), 1)
        self.assertEqual(cfg2["mcpServers"]["finnegans-agent"]["command"], "python.exe")


if __name__ == "__main__":
    unittest.main()
