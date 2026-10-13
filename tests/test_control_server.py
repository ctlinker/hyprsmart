import time
import unittest
from hyprsmart.daemon.control_server import ControlServer, send_control_command


class TestControlServer(unittest.TestCase):
    def test_control_ipc(self):
        def mock_handler(req):
            if req.get("cmd") == "hello":
                return {"status": "ok", "echo": req.get("val")}
            return {"status": "error"}

        server = ControlServer(mock_handler)
        server.start()
        time.sleep(0.1)

        try:
            res = send_control_command({"cmd": "hello", "val": "world"}, timeout=2.0)
            self.assertEqual(res.get("status"), "ok")
            self.assertEqual(res.get("echo"), "world")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
