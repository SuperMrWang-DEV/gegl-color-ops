#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""===========================================================================
 tools/mock_comfy.py · 假装是 ComfyUI 的假服务
 ---------------------------------------------------------------------------
 用途   插件和 ai_client 要测「上传 → 排队 → 轮询 → 取图」整条链路，但 CI 上
       既没有显卡也没有 ComfyUI。这个 mock 把这条链路按真服务的接口复刻一遍，
       重绘结果用一个确定性的颜色填进蒙版区域，好让断言能算准。
       A stand-in for ComfyUI: same endpoints, deterministic pixels.

 用法   python tools/mock_comfy.py --port 8188        # 手动起一个，插件直接用
        from mock_comfy import start_mock            # 测试里起在随机端口

 接口   GET  /system_stats
        GET  /object_info/CheckpointLoaderSimple
        POST /upload/image
        POST /prompt            （prompt 里带 "__FAIL__" 会返回 400 + node_errors）
        GET  /history/<id>
        GET  /view?filename=...
        GET  /queue / POST /interrupt

 注意   重绘结果 = 原图，蒙版区域（mask PNG 的 alpha < 128 处）填成 FILL_RGB。
        所以「白=要重绘」这条约定一旦写反，测试立刻红——这正是要守的东西。
        只有一个 LoadImage 的工作流（整图 img2img）原样返回。
 ==========================================================================="""

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "plugin", "_shared"))

import ai_client  # noqa: E402

# 重绘区域固定填这个颜色：断言时不用猜，也不会和测试图的颜色撞
FILL_RGB = (30, 144, 255)

CHECKPOINT = "mock-sd15.safetensors"


class MockState(object):
    """mock 服务的内存状态：上传的文件、已完成的单子、收到的请求。"""

    def __init__(self, delay=0.0, fail_status=None):
        self.delay = delay
        self.fail_status = fail_status        # 让 /prompt 直接报错（测错误路径）
        self.workdir = tempfile.mkdtemp(prefix="mock-comfy-")
        self.inputs = {}                      # name -> bytes
        self.outputs = {}                     # filename -> bytes
        self.history = {}                     # prompt_id -> entry
        self.prompts = {}                     # prompt_id -> workflow
        self.requests = []                    # (method, path)
        self.lock = threading.Lock()

    # ---- 生成 ----
    def generate(self, workflow):
        """按工作流里的 LoadImage + SaveImage 造一张结果图。"""
        loads = {}
        prefix = "mock"
        for node in workflow.values():
            kind = node.get("class_type")
            if kind == "LoadImage":
                loads[node["inputs"].get("image", "")] = node["inputs"].get("image")
            elif kind == "SaveImage":
                prefix = node["inputs"].get("filename_prefix") or "mock"

        names = [n for n in loads if n in self.inputs]
        if len(names) == 1:
            # img2img 工作流只有一张 LoadImage：原样返回。
            # 「denoise=0 等于不动像素」是真的，磨皮预修那三支插件据此断言
            # 「AI 参考与原图一致时不该凭空刷出蒙版」。
            sw, sh, sch, spix = ai_client.decode_png(self.inputs[names[0]])
            out = bytearray(sw * sh * 4)
            for i in range(sw * sh):
                j3, j4 = i * sch, i * 4
                out[j4:j4 + 3] = spix[j3:j3 + 3]
                out[j4 + 3] = spix[j3 + 3] if sch == 4 else 255
            filename = "%s_%05d_.png" % (prefix, len(self.outputs) + 1)
            self.outputs[filename] = ai_client.rgba_png(sw, sh, bytes(out))
            return {"filename": filename, "subfolder": "", "type": "output"}
        if len(names) < 2:
            raise ValueError("工作流里要有两张 LoadImage（原图 + 蒙版），"
                             "实际上传了 %s" % list(self.inputs))
        # 哪张是蒙版？按上传顺序取（插件先传 src 再传 mask），文件名兜底
        src_name = next((n for n in names if "src" in n), names[0])
        mask_name = next((n for n in names if n != src_name), names[-1])

        sw, sh, sch, spix = ai_client.decode_png(self.inputs[src_name])
        mw, mh, mch, mpix = ai_client.decode_png(self.inputs[mask_name])
        if (mw, mh) != (sw, sh):
            raise ValueError("蒙版与原图尺寸不一致: %dx%d vs %dx%d"
                             % (mw, mh, sw, sh))

        out = bytearray(sw * sh * 4)
        for i in range(sw * sh):
            r, g, b = spix[i * sch:i * sch + 3]
            a = spix[i * sch + 3] if sch == 4 else 255
            if mch == 4:
                keep = mpix[i * 4 + 3]                 # mask = 1 - alpha
            elif mch == 1:
                keep = mpix[i]
            else:
                keep = 255
            if keep < 128:                             # 透明 = 要重绘
                r, g, b = FILL_RGB
                a = 255
            out[i * 4:i * 4 + 4] = bytes((r, g, b, a))

        filename = "%s_%05d_.png" % (prefix, len(self.outputs) + 1)
        self.outputs[filename] = ai_client.rgba_png(sw, sh, bytes(out))
        return {"filename": filename, "subfolder": "", "type": "output"}


def _make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):          # 静音，测试输出别被刷屏
            pass

        # ---- 工具 ----
        def _send(self, code, payload, ctype="application/json"):
            body = payload if isinstance(payload, bytes) else \
                json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read(self):
            length = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(length) if length else b""

        # ---- 路由 ----
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            state.requests.append(("GET", path))

            if path == "/system_stats":
                return self._send(200, {
                    "system": {"comfyui_version": "0.0.0-mock",
                               "python_version": "mock",
                               "os": "mock"},
                    "devices": [{"name": "mock", "type": "cpu"}]})

            if path == "/object_info/CheckpointLoaderSimple":
                return self._send(200, {"CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": [[CHECKPOINT]]},
                              "optional": {}},
                    "output": ["MODEL", "CLIP", "VAE"]}})

            if path.startswith("/history/"):
                pid = path.rsplit("/", 1)[-1]
                entry = state.history.get(pid)
                return self._send(200, {} if entry is None else {pid: entry})

            if path == "/view":
                query = urllib.parse.parse_qs(parsed.query)
                name = (query.get("filename") or [""])[0]
                blob = state.outputs.get(name)
                if blob is None:
                    return self._send(404, {"error": "no such file: %s" % name})
                return self._send(200, blob, "image/png")

            if path == "/queue":
                return self._send(200, {"queue_running": [], "queue_pending": []})

            return self._send(404, {"error": "mock: unknown GET " + path})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            body = self._read()
            state.requests.append(("POST", path))

            if path == "/upload/image":
                return self._upload(body)

            if path == "/interrupt":
                return self._send(200, {})

            if path == "/prompt":
                return self._prompt(body)

            return self._send(404, {"error": "mock: unknown POST " + path})

        # ---- 具体处理 ----
        def _upload(self, body):
            ctype = self.headers.get("Content-Type") or ""
            match = re.search(r"boundary=(.+)$", ctype)
            if not match:
                return self._send(400, {"error": "缺少 multipart boundary"})
            boundary = match.group(1).strip().strip('"').encode()
            name = None
            for part in body.split(b"--" + boundary):
                head, _, payload = part.partition(b"\r\n\r\n")
                if not head:
                    continue
                fn = re.search(br'filename="([^"]*)"', head)
                if fn:
                    name = fn.group(1).decode("utf-8", "replace")
                    blob = payload.rstrip(b"\r\n")
                    with state.lock:
                        state.inputs[name] = blob
            if not name:
                return self._send(400, {"error": "multipart 里没有 filename"})
            return self._send(200, {"name": name, "subfolder": "",
                                    "type": "input"})

        def _prompt(self, body):
            if state.fail_status:
                return self._send(400, {
                    "error": {"type": "prompt_outputs_failed_validation",
                              "message": state.fail_status, "details": ""},
                    "node_errors": {}})
            try:
                payload = json.loads(body.decode("utf-8"))
            except ValueError:
                return self._send(400, {"error": {"message": "不是 JSON"}})
            workflow = payload.get("prompt") or {}
            text = json.dumps(workflow, ensure_ascii=False)
            if "__FAIL__" in text:
                return self._send(400, {
                    "error": {"type": "prompt_outputs_failed_validation",
                              "message": "模拟的校验失败", "details": ""},
                    "node_errors": {"6": {"errors": [
                        {"message": "Value not in list: ckpt_name",
                         "type": "value_not_in_list"}]}}})

            pid = uuid.uuid4().hex
            if state.delay:
                time.sleep(state.delay)
            try:
                image = state.generate(workflow)
            except ValueError as exc:
                return self._send(400, {"error": {"message": str(exc)},
                                        "node_errors": {}})

            with state.lock:
                state.prompts[pid] = workflow
                # 模拟「排完队、跑完了」：mock 一气呵成，history 直接就是终态
                state.history[pid] = {
                    "prompt": [0, pid, workflow, {}, []],
                    "outputs": {"9": {"images": [image]}},
                    "status": {"status_str": "success", "completed": True,
                               "messages": [["execution_start",
                                             {"prompt_id": pid}]]},
                }
            return self._send(200, {"prompt_id": pid, "number": 0,
                                    "node_errors": {}})

    return Handler


class MockServer(object):
    """起在随机（或指定）端口的假 ComfyUI，测试里当上下文管理器用。"""

    def __init__(self, port=0, delay=0.0, fail_status=None):
        self.state = MockState(delay=delay, fail_status=fail_status)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(self.state))
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       name="mock-comfy", daemon=True)
        self._started = False

    def start(self):
        # start_mock() 里已经起过一次，再进 with 不能重复 start（线程只能 start 一次）
        if not self._started:
            self.thread.start()
            self._started = True
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def start_mock(port=0, delay=0.0, fail_status=None):
    return MockServer(port=port, delay=delay, fail_status=fail_status).start()


def main(argv=None):
    ap = argparse.ArgumentParser(description="假装是 ComfyUI 的假服务")
    ap.add_argument("--port", type=int, default=8188)
    ap.add_argument("--delay", type=float, default=0.0,
                    help="每单假装耗时多少秒（0 = 立刻返回）")
    ap.add_argument("--fail", default=None,
                    help="让 /prompt 直接报这个错（测错误提示用）")
    args = ap.parse_args(argv)
    srv = MockServer(port=args.port, delay=args.delay,
                     fail_status=args.fail).start()
    print("mock ComfyUI on %s  (Ctrl-C 退出)" % srv.url)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        srv.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
