"""统一 HTTP 客户端冒烟测试：本地起一个 http.server 验证各入口语义。

不触碰任何生产库 / 总线，纯网络行为校验。
"""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from shared.http_client import (  # noqa: E402
    HttpClientError,
    get_bytes,
    http_health_timed,
    proxy_request,
    request,
    request_raw,
)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静默
        pass

    def _send(self, code, body=b'', ct='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == '/json':
            self._send(200, json.dumps({'ok': True}).encode())
        elif self.path == '/empty':
            self._send(200, b'')
        elif self.path == '/500':
            self._send(500, json.dumps({'e': 'x'}).encode())
        else:
            self._send(404)

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        data = self.rfile.read(n) if n else b''
        if self.path == '/post':
            self._send(200, json.dumps({'got': data.decode()}).encode())
        else:
            self._send(404)


class HttpClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(('127.0.0.1', 0), _Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def base(self, p=''):
        return f'http://127.0.0.1:{self.port}{p}'

    def test_request_json(self):
        self.assertEqual(request('GET', self.base('/json')), {'ok': True})

    def test_request_empty_body(self):
        self.assertEqual(request('GET', self.base('/empty')), {})

    def test_get_bytes(self):
        self.assertEqual(get_bytes(self.base('/json')),
                         json.dumps({'ok': True}).encode())

    def test_request_raises_on_5xx(self):
        with self.assertRaises(HttpClientError) as ctx:
            request('GET', self.base('/500'))
        self.assertEqual(ctx.exception.status, 500)

    def test_request_raw_raises_on_4xx(self):
        with self.assertRaises(HttpClientError):
            request_raw('GET', self.base('/404'))

    def test_proxy_request_returns_status(self):
        status, raw = proxy_request('GET', self.base('/404'))
        self.assertEqual(status, 404)
        self.assertEqual(raw, b'')

    def test_proxy_post(self):
        status, raw = proxy_request('POST', self.base('/post'), json_body={'a': 1})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), {'got': json.dumps({'a': 1})})

    def test_health_timed_healthy(self):
        st, lat = http_health_timed(self.base('/empty'), timeout=2)
        self.assertEqual(st, 'healthy')
        self.assertIsNotNone(lat)

    def test_health_timed_offline(self):
        import socket
        # 绑一个临时端口后立刻关闭，再连它 -> 不可达（本机环回关端口可能表现成
        # 连接超时而非拒绝，故只断言“非 healthy 且延迟为空”，与看门狗语义一致）。
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        closed_port = s.getsockname()[1]
        s.close()
        st, lat = http_health_timed(f'http://127.0.0.1:{closed_port}/closed', timeout=0.3)
        self.assertNotEqual(st, 'healthy')
        self.assertIsNone(lat)

    def test_health_timed_reachable(self):
        # 404 在默认 reachable 集合内视为可达
        st, _ = http_health_timed(self.base('/404'), timeout=1)
        self.assertEqual(st, 'healthy')


if __name__ == '__main__':
    unittest.main()
