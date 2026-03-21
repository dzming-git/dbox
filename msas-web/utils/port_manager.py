"""
端口管理工具模块
提供端口占用检查和强制释放功能
"""
import psutil
import socket
import logging

logger = logging.getLogger(__name__)


def is_port_in_use(port):
    """
    检查指定端口是否被占用
    
    Args:
        port (int): 要检查的端口号
    
    Returns:
        bool: True表示端口被占用，False表示端口空闲
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('localhost', port))
            return result == 0
    except Exception as e:
        logger.error(f"检查端口 {port} 占用状态失败: {e}")
        return False


def find_process_using_port(port):
    """
    查找占用指定端口的进程
    
    Args:
        port (int): 端口号
    
    Returns:
        list: 占用该端口的进程对象列表，如果没有则返回空列表
    """
    processes = []
    try:
        for conn in psutil.net_connections():
            if conn.laddr.port == port and conn.status == 'LISTEN':
                try:
                    proc = psutil.Process(conn.pid)
                    processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    logger.warning(f"无法访问进程 {conn.pid}")
    except Exception as e:
        logger.error(f"查找端口 {port} 的进程失败: {e}")
    
    return processes


def kill_process(process):
    """
    强制终止指定进程
    
    Args:
        process (psutil.Process): 要终止的进程对象
    
    Returns:
        bool: True表示成功终止，False表示失败
    """
    try:
        pid = process.pid
        name = process.name()
        process.terminate()  # 先尝试正常终止
        
        # 等待进程结束
        try:
            process.wait(timeout=5)
            logger.info(f"成功终止进程 {name} (PID: {pid})")
            return True
        except psutil.TimeoutExpired:
            # 正常终止超时，强制杀死
            process.kill()
            process.wait(timeout=2)
            logger.info(f"强制杀死进程 {name} (PID: {pid})")
            return True
            
    except psutil.NoSuchProcess:
        logger.warning(f"进程已不存在")
        return True
    except psutil.AccessDenied:
        logger.error(f"没有权限终止进程 (PID: {process.pid})")
        return False
    except Exception as e:
        logger.error(f"终止进程失败: {e}")
        return False


def kill_all_processes_using_port(port):
    """
    强制终止占用指定端口的所有进程
    
    Args:
        port (int): 端口号
    
    Returns:
        dict: 返回操作结果，包括:
            - success: 是否成功
            - killed_count: 被终止的进程数
            - processes: 被终止的进程信息列表
    """
    result = {
        'success': True,
        'killed_count': 0,
        'processes': []
    }
    
    processes = find_process_using_port(port)
    
    if not processes:
        logger.info(f"端口 {port} 没有被占用")
        return result
    
    logger.warning(f"端口 {port} 被 {len(processes)} 个进程占用")
    
    for proc in processes:
        proc_info = {
            'pid': proc.pid,
            'name': proc.name(),
            'status': 'failed'
        }
        
        if kill_process(proc):
            result['killed_count'] += 1
            proc_info['status'] = 'killed'
        
        result['processes'].append(proc_info)
    
    # 验证端口是否已释放
    if is_port_in_use(port):
        result['success'] = False
        logger.error(f"端口 {port} 仍然被占用，可能有新进程启动")
    else:
        logger.info(f"端口 {port} 已成功释放")
    
    return result


def ensure_port_available(port):
    """
    确保端口可用，如果被占用则强制释放
    
    Args:
        port (int): 端口号
    
    Returns:
        dict: 返回操作结果
    """
    if not is_port_in_use(port):
        logger.info(f"端口 {port} 可用")
        return {
            'success': True,
            'action': 'none',
            'message': f'端口 {port} 可用'
        }
    
    logger.warning(f"端口 {port} 被占用，正在强制释放...")
    result = kill_all_processes_using_port(port)
    result['action'] = 'killed'
    result['message'] = f'已终止 {result["killed_count"]} 个进程以释放端口 {port}'
    
    return result


if __name__ == '__main__':
    # 测试代码
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python port_manager.py <port> [check|kill]")
        sys.exit(1)
    
    port = int(sys.argv[1])
    action = sys.argv[2] if len(sys.argv) > 2 else 'check'
    
    if action == 'check':
        if is_port_in_use(port):
            print(f"端口 {port} 被占用")
            processes = find_process_using_port(port)
            for proc in processes:
                print(f"  - PID: {proc.pid}, Name: {proc.name()}")
        else:
            print(f"端口 {port} 空闲")
    
    elif action == 'kill':
        result = kill_all_processes_using_port(port)
        print(f"终止了 {result['killed_count']} 个进程")
        if not result['success']:
            print("警告: 端口可能仍然被占用")
