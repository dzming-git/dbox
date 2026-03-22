#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer WebUI 服务重启脚本
"""
import os
import sys
import subprocess
import time

def run_cmd(cmd, description):
    """执行命令并打印结果"""
    print(f"[+] {description}...")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"    成功")
        else:
            print(f"    警告: {result.stderr[:100] if result.stderr else '无错误信息'}")
        return result.returncode == 0
    except Exception as e:
        print(f"    错误: {e}")
        return False

def main():
    print("=" * 50)
    print("DPlayer WebUI 服务重启脚本")
    print("=" * 50)
    print()
    
    # 1. 停止现有的 node 进程
    run_cmd("taskkill /F /IM node.exe 2>nul", "停止现有的前端进程")
    run_cmd("taskkill /F /IM npm.exe 2>nul", "停止 npm 进程")
    time.sleep(2)
    
    # 2. 停止 NSSM 服务
    run_cmd("nssm stop dplayer-webui 2>nul", "停止 dplayer-webui 服务")
    time.sleep(2)
    
    # 3. 启动 NSSM 服务
    print("[+] 启动 dplayer-webui 服务...")
    result = subprocess.run("nssm start dplayer-webui", shell=True, capture_output=True, text=True)
    if "SERVICE_RUNNING" in result.stdout or result.returncode == 0:
        print("    成功")
    else:
        print(f"    警告: {result.stdout[:100] if result.stdout else result.stderr[:100]}")
    time.sleep(3)
    
    # 4. 检查服务状态
    print("[+] 检查服务状态...")
    result = subprocess.run("nssm status dplayer-webui", shell=True, capture_output=True, text=True)
    print(f"    状态: {result.stdout.strip()}")
    
    # 5. 检查端口
    print("[+] 检查端口 5173...")
    result = subprocess.run("netstat -ano | findstr :5173", shell=True, capture_output=True, text=True)
    if result.stdout:
        print(f"    {result.stdout.strip()}")
    else:
        print("    端口未监听")
    
    print()
    print("=" * 50)
    print("WebUI 服务重启完成")
    print("访问地址: http://localhost:5173")
    print("=" * 50)

if __name__ == '__main__':
    main()
