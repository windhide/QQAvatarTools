# 模拟 NapCat OneBot HTTP 服务，用于本地端到端测试
import json
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RECEIVED = Path(__file__).parent / "received"
RECEIVED.mkdir(exist_ok=True)


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        auth = self.headers.get("Authorization", "")
        path = self.path.split("?")[0]
        if auth != "Bearer test-token":
            return self._json({"status": "failed", "retcode": 401, "msg": "token mismatch"}, 401)
        if path == "/get_login_info":
            return self._json({"status": "ok", "retcode": 0,
                               "data": {"user_id": 10001, "nickname": "测试账号"}})
        if path == "/set_qq_avatar":
            param = json.loads(raw)
            f = Path(param["file"])
            saved = RECEIVED / f.name
            shutil.copyfile(f, saved)          # 头像文件用后即删，先抢救一份
            sys.stderr.write(f"RECEIVED {f} size={f.stat().st_size}\n")
            sys.stderr.flush()
            return self._json({"status": "ok", "retcode": 0, "data": None})
        self._json({"status": "failed", "retcode": 404}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 17861
    print(f"mock napcat on {port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Mock).serve_forever()
