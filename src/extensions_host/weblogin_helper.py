# -*- coding: utf-8 -*-
"""网页登录的「用户会话助手」——由服务投递到用户桌面会话，勿在服务进程内直接运行。

职责：拉起真实浏览器 → 轮询 cookie → 把结果写成 JSON 交给服务。

为什么必须跑在用户会话里（而不是服务里）：
  1. 浏览器要**出现在用户桌面上**——服务在 Session 0，直接起的窗口用户看不见；
  2. playwright 只在这里用。实测在服务进程内启动 playwright 会让整个扩展宿主卡住
     （所有插件接口开始 503）。登录这种边缘功能绝不能具备拖垮宿主的能力，
     放进独立进程后，它崩了最多是本次登录失败。

为什么不用 playwright.launch() 拉起浏览器：那会带自动化特征（navigator.webdriver
等），目标站点的人机风控很可能拦截。这里手动拉起真实 Edge/Chrome，只用
connect_over_cdp 挂上去读 cookie——它就是用户平时用的那个普通浏览器。
"""

import os
import sys
import time
import json
import shutil
import argparse
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from weblogin import browser_path, cdp_ready, cookies_matched, norm_cookies   # noqa: E402

_POLL = 1.5


def _write(out_dir, sid, state, cookies=None, error=''):
    """原子写结果文件：先写 .tmp 再 replace，避免服务读到写了一半的 JSON。"""
    path = os.path.join(out_dir, sid + '.json')
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'sid': sid, 'state': state,
                       'cookies': cookies or [], 'error': error},
                      f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sid', required=True)
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--profile', required=True)
    ap.add_argument('--url', required=True)
    ap.add_argument('--domain', default='')
    ap.add_argument('--match', default='')
    ap.add_argument('--timeout', type=int, default=900)
    ap.add_argument('--out', required=True)
    ap.add_argument('--browser', default='')
    a = ap.parse_args()

    match = [x for x in (a.match or '').split(',') if x]
    cancel_path = os.path.join(a.out, a.sid + '.cancel')
    proc = None
    try:
        _write(a.out, a.sid, 'waiting')
        exe = a.browser or browser_path()
        if not exe:
            _write(a.out, a.sid, 'error', error='未找到 Edge/Chrome')
            return 2
        # 只加必要参数：不加任何自动化开关（无 navigator.webdriver 等痕迹），
        # 也不碰代理相关参数——用户若靠系统代理上网，浏览器照常走代理。
        cmd = [exe,
               '--user-data-dir=' + a.profile,
               '--remote-debugging-port=%d' % a.port,
               '--no-first-run',
               '--no-default-browser-check',
               '--disable-blink-features=AutomationControlled',
               a.url]
        proc = subprocess.Popen(cmd)
        if not cdp_ready(a.port):
            _write(a.out, a.sid, 'error', error='浏览器未就绪（调试端口没起来）')
            return 3
        # 系统代理会把 playwright 对本机 CDP 端口的请求也代理掉（实测返回 400
        # "This does not look like a DevTools server"）：注册表里 ProxyEnable=1 且
        # ProxyOverride 含 127.*，但那个绕过列表只对 urllib 生效——playwright 自己的
        # 传输层不读 IE 设置，于是把 /json/version 发给了代理。
        # 这里 playwright 只连 127.0.0.1，直接整体绕代理。
        os.environ['NO_PROXY'] = '*'
        os.environ['no_proxy'] = '*'
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            _write(a.out, a.sid, 'error', error='缺少 playwright：%s' % e)
            return 4
        with sync_playwright() as p:
            try:
                b = p.chromium.connect_over_cdp('http://127.0.0.1:%d' % a.port)
            except Exception as e:
                _write(a.out, a.sid, 'error', error='连接浏览器失败：%s' % e)
                return 5
            deadline = time.time() + a.timeout
            while time.time() < deadline:
                if os.path.isfile(cancel_path):
                    _write(a.out, a.sid, 'cancelled')
                    return 0
                try:
                    ctxs = b.contexts
                    ctx = ctxs[0] if ctxs else None
                    if ctx is not None:
                        cks = ctx.cookies()
                        if cookies_matched(cks, match, a.domain):
                            _write(a.out, a.sid, 'done', norm_cookies(cks, a.domain))
                            return 0
                except Exception:
                    pass                # 浏览器可能正在导航，下一拍再试
                time.sleep(_POLL)
            _write(a.out, a.sid, 'timeout', error='等待登录超时')
            return 6
    except Exception as e:
        _write(a.out, a.sid, 'error', error=str(e))
        return 7
    finally:
        # 收尾：关掉浏览器 + 清掉临时 profile（登录成功后同样要做，不留残留）
        if proc is not None:
            try:
                subprocess.run(['taskkill', '/f', '/t', '/pid', str(proc.pid)],
                               capture_output=True, timeout=10)
            except Exception:
                pass
        for _ in range(3):
            try:
                if os.path.isdir(a.profile):
                    shutil.rmtree(a.profile, ignore_errors=True)
                if not os.path.isdir(a.profile):
                    break
            except Exception:
                pass
            time.sleep(0.8)


if __name__ == '__main__':
    sys.exit(main() or 0)
