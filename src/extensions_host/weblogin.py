# -*- coding: utf-8 -*-
"""通用「网页登录」：在用户桌面打开真实浏览器，人工完成登录，自动取回 cookie。

## 为什么需要它

很多站点没有可用的 OAuth，登录态只能靠 cookie。让用户自己开 devtools 抄 cookie
再粘进凭证库，体验极差且极易粘错。

## 为什么不能 iframe 内嵌官方登录页

这些站点都下发 `X-Frame-Options` / CSP `frame-ancestors`，浏览器会**直接拒绝嵌套**，
绕不过去。所以只能是「打开一个真实浏览器窗口」。

## 为什么不能直接在服务进程里跑 playwright

实测：在 extensions_host（Session 0 服务）里 import 并启动 playwright，会让**整个宿主
卡住**，所有插件接口开始返回 503。登录这种边缘功能绝不能具备拖垮宿主的能力。

所以真正干活的是**投递到用户会话的助手进程**（`weblogin_helper.py`）：
  · 浏览器必须出现在用户桌面 —— 服务在 Session 0，直接起的窗口用户看不见；
  · playwright 只在助手里用 —— 它崩了最多是本次登录失败，宿主毫发无损。
服务这边只负责：投递助手、轮询结果文件。

## 为什么不用 playwright.launch() 拉起浏览器

那样会带自动化特征（`navigator.webdriver=true` 等），目标站点的人机风控很可能拦截。
这里改为**手动拉起**真实的 Edge/Chrome（只额外加 `--user-data-dir` 与
`--remote-debugging-port`），再用 `connect_over_cdp` 挂上去读 cookie——浏览器本身就是
用户平时用的那个，没有任何自动化痕迹。

验证码 / 滑块 / 邮箱验证码 / 2FA 一律由用户在真实浏览器里完成：既 100% 可靠（邮箱码
根本无法自动化），也不触碰对方的风控（自动破解人机校验是对抗风控，违反对方 ToS，
且对方一改就失效，是维护陷阱）。

## 用法

    sid = host.weblogin.start(url='https://example.com/login',
                              match=['sessionid'], domain='example.com')
    st  = host.weblogin.status(sid)      # state: waiting|done|timeout|error|cancelled
    host.weblogin.cancel(sid)
"""

import os
import sys
import time
import socket
import threading
import ctypes
from ctypes import wintypes

try:
    import winreg
except Exception:                                   # 非 Windows（理论上不会）
    winreg = None

DEFAULT_TIMEOUT = 900        # 登录窗口最长等待（秒）

# ---------------------------------------------------------------- Win32 直调
# 与远程桌面插件 sessiond 同源的踩坑经验：
#  · pywin32 的 DuplicateTokenEx 包装一律返回 1346（ERROR_BAD_IMPERSONATION_LEVEL）
#    → 必须 ctypes 直调；
#  · ctypes 必须显式声明 argtypes/restype，否则 64 位 HANDLE 被截成 32 位，
#    GetCurrentProcess() 伪句柄失效 → 后续调用全报「句柄无效」(WinError 6)；
#  · PyHANDLE 析构会自动 CloseHandle，取到用户令牌后**必须保留句柄对象**，
#    若 int() 后丢掉对象，句柄立刻被关，创建进程时报「句柄无效」。
_advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

_MAXIMUM_ALLOWED = 0x02000000
_TOKEN_ALL_ACCESS = 0x000F01FF
_SECURITY_IMPERSONATION = 2
_TOKEN_PRIMARY = 1
_TOKEN_SESSION_ID = 12
_STARTF_USESHOWWINDOW = 0x00000001
_SW_SHOWNORMAL = 1


class _STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR),
        ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
        ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
        ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD),
        ('dwXCountChars', wintypes.DWORD), ('dwYCountChars', wintypes.DWORD),
        ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
        ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
        ('lpReserved2', ctypes.c_void_p),
        ('hStdInput', wintypes.HANDLE), ('hStdOutput', wintypes.HANDLE),
        ('hStdError', wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]


_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.GetCurrentProcess.argtypes = []
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.HANDLE)]
_advapi32.DuplicateTokenEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.HANDLE)]
_advapi32.SetTokenInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.c_void_p, wintypes.DWORD]
_advapi32.CreateProcessAsUserW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR,
                                           ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                                           wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                           ctypes.POINTER(_STARTUPINFO),
                                           ctypes.POINTER(_PROCESS_INFORMATION)]
_advapi32.CreateProcessAsUserW.restype = wintypes.BOOL


def _log(msg, *a):
    try:
        import logging
        logging.getLogger('weblogin').info(msg, *a)
    except Exception:
        pass


def _winerr(where):
    try:
        return '%s: %s' % (where, ctypes.WinError(ctypes.get_last_error()))
    except Exception:
        return where


# ---------------------------------------------------------------- 会话 / 令牌
def _console_session():
    try:
        import win32ts
        s = int(win32ts.WTSGetActiveConsoleSessionId())
    except Exception:
        return None
    if s < 0 or s == 0xFFFFFFFF:
        return None
    return s


def _user_token(sess):
    """已登录用户的令牌（首选：浏览器以用户身份运行，行为最自然）。

    **必须返回句柄对象本身，不能 int() 后丢掉对象**：PyHANDLE 析构时会自动
    CloseHandle，一旦把它转成 int 再丢弃，句柄立刻被关掉，后续
    CreateProcessAsUserW 一律报「句柄无效」(WinError 6)。
    """
    try:
        import win32ts
        return win32ts.WTSQueryUserToken(sess)
    except Exception:
        return None


def _dup_system_token_for_session(sess):
    """兜底：复制本进程 SYSTEM 令牌并把会话号改到目标会话。

    **必须先复制**再改 TokenSessionId——直接改本进程令牌会把整个服务进程挪到别的会话。
    """
    cur = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(),
                                      _TOKEN_ALL_ACCESS, ctypes.byref(cur)):
        raise RuntimeError(_winerr('OpenProcessToken'))
    try:
        new = wintypes.HANDLE()
        if not _advapi32.DuplicateTokenEx(cur, _MAXIMUM_ALLOWED, None,
                                          _SECURITY_IMPERSONATION, _TOKEN_PRIMARY,
                                          ctypes.byref(new)):
            raise RuntimeError(_winerr('DuplicateTokenEx'))
        sid = wintypes.DWORD(int(sess))
        if not _advapi32.SetTokenInformation(new, _TOKEN_SESSION_ID,
                                             ctypes.byref(sid), ctypes.sizeof(sid)):
            _kernel32.CloseHandle(new)
            raise RuntimeError(_winerr('SetTokenInformation(TokenSessionId)'))
        return new.value
    finally:
        _kernel32.CloseHandle(cur)


def _hval(tok):
    """句柄对象 → 句柄值（HANDLE 取 .value，PyHANDLE 可直接 int）。"""
    v = getattr(tok, 'value', None)
    if isinstance(v, int):
        return v
    try:
        return int(tok)
    except Exception:
        return 0


def _spawn(tok, cmd, desktop):
    """以给定令牌在指定桌面创建进程，返回 pid。调用方负责保持 tok 存活。"""
    h = _hval(tok)
    if not h:
        raise RuntimeError('无效令牌')
    si = _STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = desktop
    si.dwFlags = _STARTF_USESHOWWINDOW
    si.wShowWindow = _SW_SHOWNORMAL              # 必须看得见：用户要在里面操作
    pi = _PROCESS_INFORMATION()
    buf = ctypes.create_unicode_buffer(cmd)
    if not _advapi32.CreateProcessAsUserW(h, None, buf, None, None, False, 0,
                                          None, None, ctypes.byref(si),
                                          ctypes.byref(pi)):
        raise RuntimeError(_winerr('CreateProcessAsUserW'))
    try:
        _kernel32.CloseHandle(pi.hThread)
        _kernel32.CloseHandle(pi.hProcess)
    except Exception:
        pass
    return int(pi.dwProcessId)


def _launch_in_session(cmd, desktop='WinSta0\\Default'):
    """把进程投递到用户会话的指定桌面，返回 pid。"""
    sess = _console_session()
    if sess is None:
        raise RuntimeError('没有活动的控制台会话（请先登录到 Windows 桌面）')
    errs = []
    # 1) 用户令牌：进程以用户身份运行，最自然（首选）
    utok = _user_token(sess)
    if utok is not None:
        try:
            return _spawn(utok, cmd, desktop)
        except Exception as e:
            errs.append('user-token: %s' % e)
    # 2) 兜底：SYSTEM 令牌复制后改会话号
    try:
        stok = _dup_system_token_for_session(sess)
        try:
            return _spawn(stok, cmd, desktop)
        finally:
            try:
                _kernel32.CloseHandle(stok)
            except Exception:
                pass
    except Exception as e:
        errs.append('system-token: %s' % e)
    raise RuntimeError('；'.join(errs) or '取不到可用于交互桌面的令牌')


# ---------------------------------------------------------------- 浏览器
def browser_path(prefer=None):
    """找本机 Edge / Chrome。优先 Edge（Windows 自带，必有）。"""
    if prefer and os.path.isfile(prefer):
        return prefer
    cands = []
    if winreg:
        for root, sub in (
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe'),
            (winreg.HKEY_LOCAL_MACHINE,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe'),
            (winreg.HKEY_CURRENT_USER,
             r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe'),
        ):
            try:
                with winreg.OpenKey(root, sub) as k:
                    v, _t = winreg.QueryValueEx(k, '')
                    if v and os.path.isfile(v):
                        cands.append(v)
            except Exception:
                continue
    pf86 = os.environ.get('ProgramFiles(x86)') or r'C:\Program Files (x86)'
    pf = os.environ.get('ProgramFiles') or r'C:\Program Files'
    cands += [
        os.path.join(pf86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        os.path.join(pf86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        os.path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _free_port():
    s = socket.socket()
    try:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
    finally:
        s.close()


def cdp_ready(port, timeout=45):
    """等浏览器的调试端口可用。"""
    from shared.http_client import get_bytes, HttpClientError
    end = time.time() + timeout
    while time.time() < end:
        try:
            get_bytes('http://127.0.0.1:%d/json/version' % port, timeout=1.5)
            return True
        except HttpClientError:
            time.sleep(0.6)
    return False


def cookies_matched(cookies, names, domain):
    """是否凑齐了标志登录成功的 cookie。"""
    if not names:
        return False
    pool = [c for c in cookies
            if not domain or domain.lower() in (c.get('domain') or '').lower()]
    have = {str(c.get('name') or '') for c in pool}
    return all(n in have for n in names)


def norm_cookies(cookies, domain):
    """归一化成凭证库能直接存的结构。"""
    out = []
    for c in cookies:
        if domain and domain.lower() not in (c.get('domain') or '').lower():
            continue
        name = c.get('name')
        if not name:
            continue
        try:
            exp = int(float(c.get('expires') or -1))
        except Exception:
            exp = -1
        out.append({
            'name': name,
            'value': c.get('value') or '',
            'domain': c.get('domain') or (domain or ''),
            'path': c.get('path') or '/',
            # 存成 'TRUE'/'FALSE'：凭证库按 Netscape 行拼装，布尔 True 会拼出非法的 "True"
            'secure': 'TRUE' if c.get('secure') else 'FALSE',
            'httpOnly': 'TRUE' if c.get('httpOnly') else 'FALSE',
            'expires': exp,
        })
    return out


# ---------------------------------------------------------------- 助手进程
def _pythonw():
    """助手的解释器：优先 pythonw（无控制台窗口，不在用户桌面闪黑框）。"""
    d = os.path.dirname(sys.executable or '')
    for n in ('pythonw.exe', 'python.exe'):
        p = os.path.join(d, n)
        if p and os.path.isfile(p):
            return p
    return sys.executable or 'python'


def _helper_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'weblogin_helper.py')


# ---------------------------------------------------------------- 会话管理
class _Session(object):
    def __init__(self, sid, url, match, domain, timeout, profile, port, pid, exe):
        self.sid = sid
        self.url = url
        self.match = list(match or [])
        self.domain = domain
        self.profile = profile
        self.port = port
        self.pid = pid                  # 助手进程 pid（不是浏览器 pid）
        self.exe = exe
        self.state = 'waiting'          # waiting|done|timeout|error|cancelled
        self.cookies = []
        self.error = ''
        self.started_at = time.time()


class WebLoginManager(object):
    """通用网页登录：投递助手 → 助手开真实浏览器 → 人工登录 → 回传 cookie。"""

    def __init__(self, base_dir):
        self.base_dir = base_dir
        try:
            os.makedirs(base_dir, exist_ok=True)
        except Exception:
            pass
        self._sessions = {}
        self._lock = threading.Lock()

    # ---------- 对外 API ----------
    def start(self, url, match=None, domain=None, timeout=DEFAULT_TIMEOUT,
              browser=None):
        """打开登录页。返回 {'ok':bool, 'sid':str, 'error':str}。"""
        if not url:
            return {'ok': False, 'error': '缺少登录页地址'}
        if not browser_path(browser):
            return {'ok': False, 'error': '未找到 Edge/Chrome，无法打开登录页'}
        sid = 'wl%s' % str(int(time.time() * 1000))
        profile = os.path.join(self.base_dir, sid)
        port = _free_port()
        for stale in (self._res_path(sid), self._cancel_path(sid)):
            try:
                if os.path.isfile(stale):
                    os.remove(stale)
            except Exception:
                pass
        cmd = ('"%s" "%s" --sid %s --port %d --profile "%s" --url "%s" '
               '--domain "%s" --match "%s" --timeout %d --out "%s"'
               % (_pythonw(), _helper_path(), sid, port, profile, url,
                  domain or '', ','.join(match or []), int(timeout), self.base_dir))
        try:
            pid = _launch_in_session(cmd)
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        s = _Session(sid, url, match, domain, timeout, profile, port, pid, browser or '')
        with self._lock:
            self._sessions[sid] = s
        _log('登录助手已投递 sid=%s pid=%s port=%s url=%s', sid, pid, port, url)
        return {'ok': True, 'sid': sid, 'pid': pid, 'port': port}

    def status(self, sid):
        s = self._sessions.get(sid)
        if not s:
            return {'ok': False, 'error': '登录会话不存在（可能已过期）'}
        res = self._read_result(sid)
        if res:
            s.state = res.get('state') or s.state
            s.cookies = res.get('cookies') or []
            s.error = res.get('error') or ''
        elif not self._alive(s) and s.state == 'waiting':
            # 助手没了却没留下结果 = 异常退出，不能让前端一直转圈
            s.state = 'error'
            s.error = '登录助手已退出，未拿到结果'
        return {'ok': True, 'sid': sid, 'state': s.state,
                'cookies': s.cookies if s.state == 'done' else [],
                'error': s.error, 'url': s.url}

    def cancel(self, sid):
        s = self._sessions.get(sid)
        if not s:
            return {'ok': False, 'error': '登录会话不存在'}
        # 写「取消标记」让助手自己收尾（关浏览器 + 清临时 profile），
        # 而不是由服务强杀——强杀会留下一个孤儿浏览器窗口。
        try:
            with open(self._cancel_path(sid), 'w', encoding='utf-8') as f:
                f.write('1')
        except Exception:
            pass
        s.state = 'cancelled'
        return {'ok': True, 'state': 'cancelled'}

    # ---------- 内部 ----------
    def _res_path(self, sid):
        return os.path.join(self.base_dir, sid + '.json')

    def _cancel_path(self, sid):
        return os.path.join(self.base_dir, sid + '.cancel')

    def _read_result(self, sid):
        p = self._res_path(sid)
        try:
            if not os.path.isfile(p):
                return None
            import json
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _alive(s):
        try:
            import psutil
            return bool(s.pid) and psutil.pid_exists(s.pid)
        except Exception:
            return True                 # 查不到就当活着，避免误判成失败


_MANAGER = None
_MGR_LOCK = threading.Lock()


def get_manager():
    """进程内单例（所有插件共用一个管理器）。"""
    global _MANAGER
    with _MGR_LOCK:
        if _MANAGER is None:
            try:
                from shared.credential_vault import data_dir_for
                base = os.path.join(data_dir_for(), 'weblogin')
            except Exception:
                base = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'data', 'weblogin')
            _MANAGER = WebLoginManager(base)
        return _MANAGER
