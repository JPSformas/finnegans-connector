# tests/test_no_asyncio_run_in_tools.py
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestNoAsyncioRunInTools(unittest.TestCase):
    def test_server_and_discovery_no_asyncio_run(self):
        for rel in ("server.py", "finnegans/discovery.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn(
                "asyncio.run", src,
                f"{rel} no debe llamar asyncio.run (rompe dentro del event loop del MCP)",
            )


if __name__ == "__main__":
    unittest.main()
