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

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from servicebus import BusRouter, BusClient
from servicebus.thumbnail_adapter import BusThumbnailAdapter
from thumbnail.task_manager import TaskManager, task_worker


def test_thumbnaild_lifecycle():
    """测试 thumbnaild 的完整生命周期"""
    print("\n[Test] thumbnaild 完整生命周期测试")
    print("-" * 50)

    # 1. 启动 busbroker
    router = BusRouter(rpc_port=15555, pub_port=15556)
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
        rpc_port=15555,
        pub_port=15556
    )
    adapter.start()
    time.sleep(0.5)
    print("  [3] thumbnaild BusAdapter 已注册到总线")

    # 3. Flask 通过 BusClient 调用 thumbnaild
    client = BusClient(
        'test-web',
        host='127.0.0.1',
        rpc_port=15555,
        pub_port=15556
    )

    # 验证：服务发现
    services = router.list_services()
    print(f"  [4] 总线上的服务: {services}")
    assert 'com.dplayer.thumbnaild' in services, "thumbnaild 未注册"
    print("  [OK] 服务发现正常")

    # 验证：健康检查
    health = client.call_method('com.dplayer.thumbnaild', 'com.dplayer.Thumbnaild', 'HealthCheck', {})
    print(f"  [5] 健康检查: {health}")
    assert health and health.get('status') == 'healthy', f"健康检查失败: {health}"
    print("  [OK] 健康检查通过")

    # 验证：获取指标
    metrics = client.call_method('com.dplayer.thumbnaild', 'com.dplayer.Thumbnaild', 'GetMetrics', {})
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

    router = BusRouter(rpc_port=15556, pub_port=15557)
    router.start()
    time.sleep(0.5)

    task_manager = TaskManager()
    for i in range(1):
        t = threading.Thread(target=task_worker, args=(task_manager,), daemon=True)
        t.start()

    adapter = BusThumbnailAdapter(task_manager=task_manager, rpc_port=15556, pub_port=15557)
    adapter.start()
    time.sleep(0.5)

    client = BusClient('test-web', host='127.0.0.1',
                       rpc_port=15556, pub_port=15557)

    result = client.call_method('com.dplayer.thumbnaild', 'com.dplayer.Thumbnaild', 'Generate', {
        'video_path': 'C:/not_exist.mp4',
        'video_hash': 'test_no_file',
        'output_format': 'gif'
    })
    print(f"  生成结果（预期失败）: {result}")
    assert result is not None
    assert result.get('success') is False, "文件不存在应该返回失败"
    assert '不存在' in result.get('error', '')
    print("  [OK] 错误处理正常")

    adapter.stop()
    router.stop()


if __name__ == '__main__':
    print("=" * 60)
    print("  thumbnaild 端到端集成测试")
    print("=" * 60)

    try:
        test_thumbnaild_lifecycle()
        test_generate_no_file()
        print("\n" + "=" * 60)
        print("  全部测试通过!")
        print("=" * 60)
    except Exception as e:
        print(f"\n  [FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)