"""插件文件变动热重载（零依赖，纯标准库轮询实现）。

背景：扩展宿主（extensions_host）仅在启动时 import 一次插件模块，之后改动插件
后端代码 / manifest 不会生效，必须手动 restart 进程。CodeBuddy这类插件甚至会在
运行时改写自己的源码，导致「代码改了但接口对不上（404/500）」。

本模块在后台线程轮询监控：
- `<extensions>/<key>/backend/**/*.py`
- `<extensions>/<key>/manifest.json`

当检测到变动（防抖 1.5s）后，触发 `reload_all_plugins` 真正重载蓝图。

任务保护（核心安全诉求）：
重载前会征询每个受影响插件的「是否忙碌」钩子。插件模块可导出可选函数
`__ext_busy__()`，返回 True 表示当前有活跃任务、不应被重载。若任一相关插件
忙碌，则延迟重载（轮询等待），直到空闲或超时（超时后放弃本次，等下次变动再试），
从而避免打断正在跑的生成任务 / SSE 流。

UI（panel.html）不监控：宿主每次打开面板都实时读磁盘，无需重载。
"""

import os
import time
import threading
import logging

logger = logging.getLogger('ext.hotreload')

# 轮询间隔（秒）
_POLL_INTERVAL = 1.0
# 防抖：连续变动后等待静默期再触发（秒）
_DEBOUNCE = 1.5
# 忙碌时最长等待重载的时间（秒），超时则放弃本次触发
_BUSY_TIMEOUT = 600.0


def _extensions_dir():
    """返回插件根目录（与 plugin_loader 一致：项目根/extensions）。"""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(pkg_dir))
    return os.path.join(project_root, 'extensions')


def _iter_watch_files(ext_dir):
    """生成所有受监控文件的 (path) 列表。"""
    files = []
    if not os.path.isdir(ext_dir):
        return files
    for key in os.listdir(ext_dir):
        key_dir = os.path.join(ext_dir, key)
        if not os.path.isdir(key_dir):
            continue
        # manifest.json
        mf = os.path.join(key_dir, 'manifest.json')
        if os.path.isfile(mf):
            files.append(mf)
        # backend/**/*.py
        backend_dir = os.path.join(key_dir, 'backend')
        if os.path.isdir(backend_dir):
            for root, _dirs, names in os.walk(backend_dir):
                for n in names:
                    if n.endswith('.py'):
                        files.append(os.path.join(root, n))
    return files


def _snapshot(files):
    """记录每个文件的 (mtime, size) 指纹。"""
    snap = {}
    for f in files:
        try:
            st = os.stat(f)
            snap[f] = (st.st_mtime, st.st_size)
        except OSError:
            snap[f] = None
    return snap


def _changed(prev, cur):
    """比较指纹是否变化（含文件新增/删除）。"""
    if set(prev.keys()) != set(cur.keys()):
        return True
    for f, v in cur.items():
        if prev.get(f) != v:
            return True
    return False


def _plugin_busy(scripts):
    """征询受影响插件是否忙碌。

    插件模块以 `ext_<key>` 形式挂在 sys.modules 中（与 plugin_loader 的命名一致）。
    若某插件模块导出 `__ext_busy__` 且返回真，则视为忙碌，本次重载应延迟。
    scripts 参数保留用于将来扩展（如按启用状态过滤），当前以 sys.modules 为准。
    """
    import sys
    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.startswith('ext_'):
            continue
        hook = getattr(mod, '__ext_busy__', None)
        if callable(hook):
            try:
                if hook():
                    key = mod_name[len('ext_'):]
                    return key
            except Exception as e:
                logger.warning('插件 %s 的 __ext_busy__ 钩子异常，按不忙碌处理: %s', mod_name, e)
    return None


def _do_reload(app, scripts):
    """执行真正重载，并尊重忙碌保护。返回触发是否成功。

    采用「nssm restart 整个 extensions 进程」的方式：整进程重启走的是经过
    验证的初始 load_all 路径，保证重载后蓝图状态干净（规避进程内手工
    unregister 在 Flask/Werkzeug 下残留路由索引的 KeyError 500）。

    为避免「进程内调用 nssm restart 杀掉自己」的竞态/死循环，restart 命令
    通过 `cmd /c start` 以独立进程组（DETACHED_PROCESS）异步分离执行，
    父进程被 nssm 停止时不影响已分离的 restart 命令完成。
    """
    busy_key = _plugin_busy(scripts)
    if busy_key:
        logger.info('插件 %s 当前有活跃任务，延迟热重载以避免中断', busy_key)
        print('[hotreload] 插件 %s 忙碌，延迟重载' % busy_key, flush=True)
        return False
    try:
        import subprocess, shutil
        svc = os.environ.get('EXTENSIONS_HOST_SERVICE', 'dbox-extensions')
        # nssm 通常不在服务进程的环境 PATH 中，优先用绝对路径，其次 which 查找
        nssm_bin = r'C:\Tools\nssm.exe'
        if not os.path.isfile(nssm_bin):
            nssm_bin = shutil.which('nssm') or 'nssm'
        # 独立进程组异步执行，避免被父进程退出牵连
        cmd = '"%s" restart %s' % (nssm_bin, svc)
        subprocess.Popen(cmd, shell=True,
                         creationflags=0x00000200,  # DETACHED_PROCESS
                         close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info('热重载：已异步请求 nssm restart %s (bin=%s)', svc, nssm_bin)
        print('[hotreload] 已请求重启 extensions 进程以加载新代码', flush=True)
        return True
    except Exception:
        logger.exception('热重载失败')
        print('[hotreload] 热重载失败', flush=True)
        return True


def start_hotreload(app, scripts_getter):
    """启动后台热重载监控线程。

    :param app: Flask app（reload_all_plugins 需要）
    :param scripts_getter: 无参 callable，返回当前 mgr.scripts 字典
                          （实时引用，reload 后框架会更新该字典）
    """
    ext_dir = _extensions_dir()
    print('[hotreload] 启动插件热重载监控: %s' % ext_dir, flush=True)
    logger.info('启动插件热重载监控: %s', ext_dir)

    state = {
        'snap': _snapshot(_iter_watch_files(ext_dir)),
        'pending': 0.0,      # 待触发的时间点（防抖）
        'busy_until': 0.0,   # 忙碌等待的超时时刻
    }
    lock = threading.Lock()

    def loop():
        while True:
            try:
                time.sleep(_POLL_INTERVAL)
                files = _iter_watch_files(ext_dir)
                cur = _snapshot(files)
                with lock:
                    if _changed(state['snap'], cur):
                        state['snap'] = cur
                        # 记录变动时刻，进入防抖等待
                        if state['pending'] == 0.0:
                            state['pending'] = time.time() + _DEBOUNCE
                        else:
                            # 连续变动：刷新防抖窗口
                            state['pending'] = max(state['pending'], time.time() + _DEBOUNCE)
                    if state['pending'] == 0.0:
                        continue
                    # 检测到文件变动，进入防抖
                    if state.get('_logged', False) is False:
                        print('[hotreload] 检测到文件变动，等待防抖窗口', flush=True)
                        state['_logged'] = True
                    # 防抖静默期已到？
                    if time.time() < state['pending']:
                        continue
                    # 尝试重载（受忙碌保护）
                    ok = _do_reload(app, scripts_getter())
                    if ok:
                        state['pending'] = 0.0
                        state['busy_until'] = 0.0
                        state['_logged'] = False
                    else:
                        # 忙碌：设置等待超时（若未设置）
                        if state['busy_until'] == 0.0:
                            state['busy_until'] = time.time() + _BUSY_TIMEOUT
                        if time.time() > state['busy_until']:
                            logger.warning('等待插件空闲超时，放弃本次热重载')
                            state['pending'] = 0.0
                            state['busy_until'] = 0.0
                        # 否则继续轮询等待，pending 保持，下个周期再试
            except Exception:
                logger.exception('热重载监控线程异常')
                time.sleep(_POLL_INTERVAL)

    t = threading.Thread(target=loop, name='ext-hotreload', daemon=True)
    t.start()
    return t


# 便于手动调试 / 测试
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # 仅打印当前快照，不做实际重载
    d = _extensions_dir()
    print('监控目录:', d)
    for f in _iter_watch_files(d):
        print('  ', f)
