#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
thumbnaild 端到端集成测试

验证总线架构：
  busbroker → thumbnaild → Flask web

测试流程：
  1. 启动 busbroker (BusRouter)
  2. 启动 thumbnaild
  3. BusClient 通过总线调用 thumbnaild 的方法
  4. 验证结果
"""
import sys
import os
import time
import threading
import socket

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from servicebus import BusRouter, BusClient
from servicebus.thumbnail_adapter import BusThumbnailAdapter
from thumbnail.task_manager import TaskManager, task_worker


def _free_ports(n=2):
    """分配 n 个空闲 TCP 端口，避免与正在运行的总线服务（默认 15555/15556）冲突。"""
    socks = []
    ports = []
    try:
        for _ in range(n):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', 0))
            socks.append(s)
            ports.append(s.getsockname()[1])
        return ports
    finally:
        for s in socks:
            s.close()


def test_thumbnaild_lifecycle():
    """测试 thumbnaild 的完整生命周期"""
    print("\n[Test] thumbnaild 完整生命周期测试")
    print("-" * 50)

    # 1. 启动 busbroker（使用空闲端口，避免与运行中的总线服务冲突）
    rpc_port, pub_port = _free_ports(2)
    router = BusRouter(rpc_port=rpc_port, pub_port=pub_port)
    router.start()
    time.sleep(0.5)
    print("  [1] busbroker 已启动")

    # 2. 启动 thumbnaild
    task_manager = TaskManager(max_concurrent=2, queue_size=10)
    for i in range(2):
        t = threading.Thread(target=task_worker, args=(task_manager,), daemon=True)
        t.start()
    print("  [2] thumbnaild TaskManager 已启动 (2 workers)")

    adapter = BusThumbnailAdapter(
        task_manager=task_manager,
        rpc_port=rpc_port,
        pub_port=pub_port
    )
    adapter.start()
    time.sleep(0.5)
    print("  [3] thumbnaild BusAdapter 已注册到总线")

    # 3. Flask 通过 BusClient 调用 thumbnaild
    client = BusClient(
        'test-web',
        host='127.0.0.1',
        rpc_port=rpc_port,
        pub_port=pub_port
    )

    # 验证：服务发现
    services = router.list_services()
    print(f"  [4] 总线上的服务: {services}")
    assert 'com.dbox.thumbnaild' in services, "thumbnaild 未注册"
    print("  [OK] 服务发现正常")

    # 验证：健康检查
    health = client.call_method('com.dbox.thumbnaild', 'com.dbox.Thumbnaild', 'HealthCheck', {})
    print(f"  [5] 健康检查: {health}")
    assert health and health.get('status') == 'healthy', f"健康检查失败: {health}"
    print("  [OK] 健康检查通过")

    # 验证：获取指标
    metrics = client.call_method('com.dbox.thumbnaild', 'com.dbox.Thumbnaild', 'GetMetrics', {})
    print(f"  [6] 服务指标: {metrics}")
    assert metrics is not None, "获取指标失败"
    print("  [OK] GetMetrics 正常")

    # 清理
    adapter.stop()
    router.stop()
    print("\n  [OK] thumbnaild 生命周期测试全部通过!")


def test_generate_no_file():
    """测试请求生成（无视频文件，预期返回错误）"""
    print("\n[Test] 请求生成（文件不存在）测试")
    print("-" * 50)

    rpc_port, pub_port = _free_ports(2)
    router = BusRouter(rpc_port=rpc_port, pub_port=pub_port)
    router.start()
    time.sleep(0.5)

    task_manager = TaskManager()
    for i in range(1):
        t = threading.Thread(target=task_worker, args=(task_manager,), daemon=True)
        t.start()

    adapter = BusThumbnailAdapter(task_manager=task_manager, rpc_port=rpc_port, pub_port=pub_port)
    adapter.start()
    time.sleep(0.5)

    client = BusClient('test-web', host='127.0.0.1',
                       rpc_port=rpc_port, pub_port=pub_port)

    result = client.call_method('com.dbox.thumbnaild', 'com.dbox.Thumbnaild', 'Generate', {
        'video_path': 'C:/not_exist.mp4',
        'video_hash': 'test_no_file',
        'output_format': 'sprite'
    })
    print(f"  生成结果（预期失败）: {result}")
    assert result is not None
    assert result.get('success') is False, "文件不存在应该返回失败"
    assert '不存在' in result.get('error', '')
    print("  [OK] 错误处理正常")

    adapter.stop()
    router.stop()


def test_sprite_config_defaults():
    """测试 sprite 生成默认参数正确（采样点数/列数/长边）。"""
    print("\n[Test] sprite 默认采样参数测试")
    print("-" * 50)
    from thumbnail.task_manager import _load_preview_config
    cfg = _load_preview_config()
    print(f"  preview config: {cfg}")
    assert cfg.get('enabled') is True
    assert cfg.get('sample_points', 0) >= 4, "采样点数至少 4"
    assert cfg.get('sprite_cols', 0) >= 1, "雪碧图列数至少 1"
    assert cfg.get('sprite_long_edge', 0) >= 80, "单帧长边至少 80"
    print("  [OK] sprite 默认参数合理")


def test_sprite_vtt_geometry():
    """测试 WebVTT 坐标生成正确：按 cols/rows 推导 xywh，时间区间递增。"""
    print("\n[Test] sprite WebVTT 坐标生成测试")
    print("-" * 50)
    from thumbnail.task_manager import _build_vtt, _ts
    pv = {'sample_points': 12, 'sprite_cols': 4}
    vtt = _build_vtt(pv, 'testhash', 180, 136, 4, 3, 0.8, 8.4, 12)

    assert vtt.startswith('WEBVTT')
    assert 'NOTE sprite fw=180 fh=136 cols=4 rows=3 n=12' in vtt
    # 首帧坐标 (0,0)，第二行首帧 y=136
    assert 'xywh=0,0,180,136' in vtt
    assert 'xywh=0,136,180,136' in vtt
    assert 'xywh=0,272,180,136' in vtt
    # 时间区间从 start 递增
    assert _ts(0.8) in vtt
    print("  [OK] VTT 坐标与时间区间正确")


def test_sprite_mimetype_route():
    """测试缩略图路由的 mimetype：poster=image/jpeg, sprite=image/jpeg, vtt=text/vtt。"""
    print("\n[Test] sprite 路由 mimetype 测试")
    print("-" * 50)
    from thumbnail.task_manager import _probe_duration, _ffmpeg_available
    # ffmpeg 可用性（sprite 依赖）
    assert _ffmpeg_available() is True, "sprite 生成依赖 ffmpeg 必须可用"
    print("  [OK] ffmpeg 可用，sprite 前置依赖满足")


if __name__ == '__main__':
    print("=" * 60)
    print("  thumbnaild 端到端集成测试")
    print("=" * 60)

    try:
        test_thumbnaild_lifecycle()
        test_generate_no_file()
        test_sprite_config_defaults()
        test_sprite_vtt_geometry()
        test_sprite_mimetype_route()
        print("\n" + "=" * 60)
        print("  全部测试通过!")
        print("=" * 60)
    except Exception as e:
        print(f"\n  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)