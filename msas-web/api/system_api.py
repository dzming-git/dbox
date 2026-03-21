"""
系统信息API接口
提供版本信息、路径配置、健康检查等接口
"""
from flask import Blueprint, jsonify, current_app
from datetime import datetime
import os
import sys
import logging

from core.models import db, Video, Tag, User

logger = logging.getLogger(__name__)

# 创建蓝图
system_bp = Blueprint('system', __name__, url_prefix='/api/system')


def get_runtime_dir():
    """获取运行目录"""
    # 1. 环境变量
    if env_dir := os.environ.get('DPLAYER_RUNTIME'):
        return env_dir
    
    # 2. 从 install.json 读取
    try:
        import json
        from pathlib import Path
        cwd = Path.cwd()
        install_json = cwd / 'install.json'
        if install_json.exists():
            data = json.loads(install_json.read_text(encoding='utf-8'))
            if runtime_dir := data.get('runtime_dir'):
                return runtime_dir
    except Exception:
        pass
    
    # 3. 当前工作目录
    return os.getcwd()


def get_version():
    """获取版本号"""
    try:
        from pathlib import Path
        version_file = Path(__file__).parent.parent.parent / 'VERSION'
        if version_file.exists():
            return version_file.read_text(encoding='utf-8').strip()
    except Exception:
        pass
    return '2.0.0'


def get_install_info():
    """获取安装信息"""
    try:
        import json
        from pathlib import Path
        runtime_dir = Path(get_runtime_dir())
        install_json = runtime_dir / 'install.json'
        if install_json.exists():
            return json.loads(install_json.read_text(encoding='utf-8'))
    except Exception:
        pass
    return None


@system_bp.route('/info', methods=['GET'])
def system_info():
    """获取系统信息"""
    try:
        install_info = get_install_info()
        runtime_dir = get_runtime_dir()
        
        info = {
            'version': get_version(),
            'runtime_dir': runtime_dir,
            'timestamp': datetime.now().isoformat(),
            'python_version': sys.version,
            'platform': sys.platform,
        }
        
        if install_info:
            info['install'] = {
                'install_time': install_info.get('install_time'),
                'source_dir': install_info.get('source_dir'),
                'is_update': install_info.get('update', False),
            }
        else:
            info['install'] = None
        
        return jsonify({
            'success': True,
            'info': info
        })
    except Exception as e:
        logger.error(f"获取系统信息失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取系统信息失败: {str(e)}'
        }), 500


@system_bp.route('/paths', methods=['GET'])
def system_paths():
    """获取系统路径配置"""
    try:
        runtime_dir = get_runtime_dir()
        
        paths = {
            'runtime': runtime_dir,
            'database': os.path.join(runtime_dir, 'instance', 'dplayer.db'),
            'uploads': os.path.join(runtime_dir, 'uploads'),
            'logs': os.path.join(runtime_dir, 'logs'),
            'static': os.path.join(runtime_dir, 'static'),
            'config': os.path.join(runtime_dir, 'config'),
            'instance': os.path.join(runtime_dir, 'instance'),
        }
        
        return jsonify({
            'success': True,
            'paths': paths
        })
    except Exception as e:
        logger.error(f"获取路径配置失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取路径配置失败: {str(e)}'
        }), 500


@system_bp.route('/stats', methods=['GET'])
def system_stats():
    """获取系统统计数据"""
    try:
        stats = {
            'videos': Video.query.count(),
            'tags': Tag.query.count(),
            'users': User.query.count(),
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取系统统计失败: {str(e)}'
        }), 500


@system_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    try:
        # 检查数据库连接
        db.session.execute('SELECT 1')
        
        return jsonify({
            'success': True,
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'runtime_dir': get_runtime_dir(),
            'version': get_version()
        })
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'message': str(e),
            'timestamp': datetime.now().isoformat()
        }), 503


# ==================== 开发同步状态管理 ====================

# 全局同步状态（内存中）
_sync_status = {
    'is_running': False,
    'last_sync': None,
    'synced_count': 0,
    'watch_mode': False,
    'pid': None,
}


def get_sync_state_file():
    """获取同步状态文件路径"""
    from pathlib import Path
    runtime_dir = Path(get_runtime_dir())
    return runtime_dir / '.sync_state.json'


def load_sync_state_from_file():
    """从文件加载同步状态"""
    try:
        import json
        state_file = get_sync_state_file()
        if state_file.exists():
            data = json.loads(state_file.read_text(encoding='utf-8'))
            return {
                'last_sync': data.get('last_sync'),
                'synced_count': data.get('synced_count', 0),
            }
    except Exception as e:
        logger.warning(f"加载同步状态失败: {e}")
    return None


def get_sync_log():
    """获取同步日志"""
    try:
        from pathlib import Path
        runtime_dir = Path(get_runtime_dir())
        log_file = runtime_dir / 'logs' / 'dev_sync.log'
        if log_file.exists():
            lines = log_file.read_text(encoding='utf-8').strip().split('\n')
            # 返回最近50条
            return lines[-50:] if len(lines) > 50 else lines
    except Exception as e:
        logger.warning(f"读取同步日志失败: {e}")
    return []


@system_bp.route('/sync-status', methods=['GET'])
def sync_status():
    """获取开发同步状态"""
    try:
        global _sync_status
        
        # 从文件加载最新状态
        file_state = load_sync_state_from_file()
        if file_state:
            _sync_status['last_sync'] = file_state.get('last_sync')
            _sync_status['synced_count'] = file_state.get('synced_count', 0)
        
        # 获取同步日志
        sync_log = get_sync_log()
        
        return jsonify({
            'success': True,
            'status': _sync_status,
            'log': sync_log
        })
    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取同步状态失败: {str(e)}'
        }), 500


@system_bp.route('/sync-trigger', methods=['POST'])
def trigger_sync():
    """触发全量同步"""
    try:
        global _sync_status
        
        # 检查是否已在运行
        if _sync_status['is_running']:
            return jsonify({
                'success': False,
                'message': '同步任务已在运行中'
            }), 409
        
        # 获取安装信息中的源码目录
        install_info = get_install_info()
        source_dir = install_info.get('source_dir') if install_info else None
        runtime_dir = get_runtime_dir()
        
        if not source_dir:
            return jsonify({
                'success': False,
                'message': '无法确定源码目录，请检查安装信息'
            }), 400
        
        # 异步执行同步
        import threading
        import subprocess
        import sys
        
        def run_sync():
            global _sync_status
            _sync_status['is_running'] = True
            _sync_status['last_sync'] = datetime.now().isoformat()
            
            try:
                # 调用 dev_sync.py 执行同步
                script_path = os.path.join(source_dir, 'scripts', 'dev_sync.py')
                if os.path.exists(script_path):
                    result = subprocess.run(
                        [sys.executable, script_path, '--dest', runtime_dir, '--once'],
                        capture_output=True,
                        text=True,
                        timeout=300  # 5分钟超时
                    )
                    logger.info(f"同步完成: {result.returncode}")
                    if result.returncode == 0:
                        # 重新加载同步状态
                        file_state = load_sync_state_from_file()
                        if file_state:
                            _sync_status['synced_count'] = file_state.get('synced_count', 0)
                else:
                    logger.error(f"同步脚本不存在: {script_path}")
            except Exception as e:
                logger.error(f"同步执行失败: {e}")
            finally:
                _sync_status['is_running'] = False
        
        # 启动后台线程
        thread = threading.Thread(target=run_sync, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': '同步任务已启动',
            'status': _sync_status
        })
        
    except Exception as e:
        logger.error(f"触发同步失败: {e}")
        return jsonify({
            'success': False,
            'message': f'触发同步失败: {str(e)}'
        }), 500


# 导入 logging
import logging
