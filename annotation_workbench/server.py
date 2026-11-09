"""仅绑定回环地址的单人标注服务。"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit, unquote

from .store import Store, Conflict, identifier

STATIC = Path(__file__).parent / "static"


def handler(store):
    class Handler(BaseHTTPRequestHandler):
        def video(self, task):
            data = store.load(task)
            path = store.resolve(data["dataset"]["video"]["path"])
            size = path.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get("Range")
            if requested:
                import re
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                if not match or not any(match.groups()):
                    return self.respond(416, {"error": "无效的字节范围"})
                left, right = match.groups()
                if left:
                    start = int(left)
                    end = min(int(right), end) if right else end
                else:
                    start = max(0, size - int(right))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with path.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        block = stream.read(min(remaining, 256 * 1024))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def respond(self, status, value, content_type="application/json; charset=utf-8"):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if content_type.startswith("application/json") else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self, post=False):
            try:
                # 拒绝跨站写请求和 DNS rebinding；无 CORS、无任意文件服务。
                host = self.headers.get("Host", "")
                allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
                if host not in allowed:
                    return self.respond(403, {"error": "仅允许本地访问"})
                origin = self.headers.get("Origin")
                if post and (self.headers.get("Content-Type", "").split(";")[0] != "application/json" or
                             (origin and origin not in {"http://" + h for h in allowed})):
                    return self.respond(403, {"error": "拒绝跨站请求"})
                path = unquote(urlsplit(self.path).path)
                args = path.strip("/").split("/")
                body = {}
                if post:
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 20_000_000:
                        raise ValueError("请求大小无效")
                    body = json.loads(self.rfile.read(size))
                if path == "/api/tasks":
                    return self.respond(200, store.create(body) if post else store.tasks())
                if len(args) >= 3 and args[:2] == ["api", "tasks"]:
                    task = identifier(args[2])
                    action = args[3] if len(args) > 3 else ""
                    if not post and not action:
                        return self.respond(200, store.load(task))
                    if not post and action == "export":
                        data = store.load(task)
                        return self.respond(200, {"dataset": data["dataset"], "annotation": data["annotation"]})
                    if not post and action == "video":
                        return self.video(task)
                    if not post and action == "image" and len(args) == 5:
                        fid = identifier(args[4])
                        data = store.load(task)
                        if fid not in data["annotation"]["frames"]:
                            raise ValueError("帧不存在")
                        return self.respond(200, (store.paths(task)[2] / f"{fid}.jpg").read_bytes(), "image/jpeg")
                    if post:
                        if action == "save":
                            return self.respond(200, store.save(task, body))
                        if action == "import-run":
                            return self.respond(200, store.import_run(task, body["run"]))
                        if action == "ocr":
                            return self.respond(200, store.ocr(task, body["frame_id"]))
                        if action == "regenerate":
                            return self.respond(200, store.regenerate(task))
                if not post and path in ("/", "/app.js", "/style.css"):
                    name = "index.html" if path == "/" else path[1:]
                    mime = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css"}[name]
                    return self.respond(200, (STATIC / name).read_bytes(), mime + "; charset=utf-8")
                return self.respond(404, {"error": "入口不存在"})
            except Conflict as exc:
                self.respond(409, {"error": str(exc)})
            except FileNotFoundError:
                self.respond(404, {"error": "文件不存在；图片缓存缺失时可点击重建图片"})
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                self.respond(400, {"error": str(exc)})
            except Exception as exc:
                self.log_error("%s", exc)
                self.respond(500, {"error": f"操作失败：{exc}"})

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(True)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="本地板书标注工作台：任务准备、区域修订、跨帧条目与 JSON 导出")
    parser.add_argument("--port", type=int, default=8765, help="回环服务端口，默认 8765")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="项目目录")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(Store(args.root)))
    print(f"标注工作台：http://127.0.0.1:{server.server_port} （Ctrl+C 停止）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
