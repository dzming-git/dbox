#!/usr/bin/env python3
"""测试标签API权限过滤"""

import requests
import json

BASE_URL = "http://localhost:8080"

def test_tags_api():
    """测试标签API"""
    
    print("=" * 60)
    print("测试标签API权限过滤")
    print("=" * 60)
    
    # 1. 测试未登录用户
    print("\n1. 测试未登录用户:")
    response = requests.get(f"{BASE_URL}/api/tags")
    print(f"   状态码: {response.status_code}")
    data = response.json()
    print(f"   标签数量: {len(data.get('tags', []))}")
    
    # 2. 登录获取token
    print("\n2. 登录获取token:")
    
    # 尝试登录 root 用户
    login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "root",
        "password": "root"  # 默认密码
    })
    print(f"   root 登录状态码: {login_response.status_code}")
    
    if login_response.status_code == 200:
        login_data = login_response.json()
        root_token = login_data.get('token') or login_data.get('access_token') or login_data.get('data', {}).get('token')
        print(f"   root token: {root_token[:20] if root_token else 'None'}...")
        
        # 测试 root 用户
        print("\n3. 测试 root 用户 (ROOT角色):")
        headers = {"Authorization": f"Bearer {root_token}"}
        response = requests.get(f"{BASE_URL}/api/tags", headers=headers)
        print(f"   状态码: {response.status_code}")
        data = response.json()
        print(f"   标签数量: {len(data.get('tags', []))}")
        if data.get('tags'):
            print(f"   前3个标签:")
            for tag in data['tags'][:3]:
                print(f"     - {tag.get('name')}: {tag.get('video_count', 0)} 个视频")
    
    # 尝试登录 lyx 用户
    print("\n4. 登录 lyx 用户:")
    login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "lyx",
        "password": "lyx"  # 默认密码
    })
    print(f"   lyx 登录状态码: {login_response.status_code}")
    
    if login_response.status_code == 200:
        login_data = login_response.json()
        lyx_token = login_data.get('token') or login_data.get('access_token') or login_data.get('data', {}).get('token')
        print(f"   lyx token: {lyx_token[:20] if lyx_token else 'None'}...")
        
        # 测试 lyx 用户
        print("\n5. 测试 lyx 用户 (普通用户):")
        headers = {"Authorization": f"Bearer {lyx_token}"}
        response = requests.get(f"{BASE_URL}/api/tags", headers=headers)
        print(f"   状态码: {response.status_code}")
        data = response.json()
        print(f"   标签数量: {len(data.get('tags', []))}")
        if data.get('tags'):
            print(f"   标签详情:")
            total_videos = sum(tag.get('video_count', 0) for tag in data['tags'])
            print(f"   总视频数: {total_videos}")
            for tag in data['tags'][:5]:
                print(f"     - {tag.get('name')}: {tag.get('video_count', 0)} 个视频")

if __name__ == '__main__':
    test_tags_api()
