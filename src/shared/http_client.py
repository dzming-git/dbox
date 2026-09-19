"""统一 HTTP 客户端。

整合此前散落在 extensions_host / servicebus / web 各处的 urllib.request 与
requests 调用，统一超时、异常归一、JSON 编解码与 HTTP 健康检查，消除各调用点
自行拼装 Request / 处理 HTTPError 的重复代码。

统一契约：
- 网络层故障（连接失败 / 超时 / DNS）→ 抛 HttpClientError(status=None)
- HTTP 4xx/5xx → 抛 HttpClientError(status=code, body=text)（由 raise_on_error 控制）
- 成功 → 解析后的 JSON（空响应返回 {}）

提供的语义化入口：
- request / get_json / post_json：成功返回解析后的 JSON，4xx/5xx 抛异常
- request_raw / get_bytes：返回原始响应体字节（4xx/5xx 抛异常），用于 CDP 探活等
- proxy_request：反向代理，返回 (status_code, body_bytes)，仅网络故障抛异常
- http_health_timed：探活，返回 (状态串, 延迟毫秒)，不抛异常

流式透传（SSE 等）不走本模块，仍由调用方用底层 http.client 处理（见 web/main.py），
因为 requests 会缓冲整条响应流，导致 EventSource 实时增量中断。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger('dbox.http')

DEFAULT_TIMEOUT = 10  # 秒


class HttpClientError(Exception):
    """HTTP 客户端统一异常：网络故障或 HTTP 错误。"""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 body: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _do(method: str, url: str, *, json_body: Any = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        raise_on_error: bool = True) -> requests.Response:
    try:
        resp = requests.request(method, url, json=json_body, params=params,
                                data=data, headers=headers, cookies=cookies,
                                timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise HttpClientError(f'{method} {url} 请求失败: {e}') from e
    if raise_on_error and resp.status_code >= 400:
        raise HttpClientError(f'{method} {url} 返回 {resp.status_code}',
                              status=resp.status_code, body=resp.text)
    return resp


def request(method: str, url: str, *, json_body: Any = None,
            params: Optional[Dict[str, Any]] = None,
            data: Optional[bytes] = None,
            headers: Optional[Dict[str, str]] = None,
            cookies: Optional[Dict[str, str]] = None,
            timeout: int = DEFAULT_TIMEOUT) -> Any:
    """发送请求并返回解析后的 JSON（空响应返回 {}）；4xx/5xx 抛 HttpClientError。"""
    resp = _do(method, url, json_body=json_body, params=params, data=data,
               headers=headers, cookies=cookies, timeout=timeout,
               raise_on_error=True)
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return resp.text


def get_json(url: str, **kw) -> Any:
    return request('GET', url, **kw)


def post_json(url: str, json_body: Any = None, **kw) -> Any:
    return request('POST', url, json_body=json_body, **kw)


def request_raw(method: str, url: str, *, json_body: Any = None,
                data: Optional[bytes] = None,
                headers: Optional[Dict[str, str]] = None,
                timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """返回原始响应体字节；4xx/5xx 抛 HttpClientError（与 urllib 行为一致）。"""
    resp = _do(method, url, json_body=json_body, data=data, headers=headers,
               timeout=timeout, raise_on_error=True)
    return resp.content


def get_bytes(url: str, *, headers: Optional[Dict[str, str]] = None,
             timeout: int = DEFAULT_TIMEOUT) -> bytes:
    return request_raw('GET', url, headers=headers, timeout=timeout)


def proxy_request(method: str, url: str, *, json_body: Any = None,
                  data: Optional[bytes] = None,
                  headers: Optional[Dict[str, str]] = None,
                  cookies: Optional[Dict[str, str]] = None,
                  timeout: int = DEFAULT_TIMEOUT) -> Tuple[int, bytes]:
    """反向代理：透传方法/头/体，返回 (status_code, body_bytes)。仅网络故障抛 HttpClientError。"""
    resp = _do(method, url, json_body=json_body, data=data, headers=headers,
               cookies=cookies, timeout=timeout, raise_on_error=False)
    return resp.status_code, resp.content


def http_health_timed(url: str, *, timeout: float = 1.5,
                      reachable: Tuple[int, ...] = (200, 401, 403, 404)
                      ) -> Tuple[str, Optional[float]]:
    """探活并返回 (状态串, 延迟毫秒|None)。状态串: healthy/unhealthy/timeout/offline。

    reachable 内的状态码视为“进程活着、可达”（默认含认证拦截 401/403 与
    路由缺失 404，与 watchdog_adapter 语义一致）。
    """
    start = time.time()
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.exceptions.Timeout:
        return ('timeout', None)
    except requests.exceptions.RequestException:
        return ('offline', None)
    latency = (time.time() - start) * 1000
    status = 'healthy' if resp.status_code in reachable else 'unhealthy'
    return (status, latency)
