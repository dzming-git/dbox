"""
Service Manager Utility for AI Assistant

Allows AI to restart Windows services without direct admin privileges
by using scheduled tasks.
"""
import subprocess
import time
from typing import Optional


def restart_service(service_name: str) -> dict:
    """
    Restart a Windows service using scheduled task

    Args:
        service_name: 'admin', 'main', 'thumbnail', or 'all'

    Returns:
        dict with 'success' and 'message' keys
    """
    task_map = {
        'admin': 'DPlayer_Restart_Admin',
        'main': 'DPlayer_Restart_Main',
        'thumbnail': 'DPlayer_Restart_Thumbnail',
        'all': 'DPlayer_Restart_All'
    }

    if service_name not in task_map:
        return {
            'success': False,
            'message': f"Invalid service name: {service_name}. Use: admin, main, thumbnail, all"
        }

    task_name = task_map[service_name]

    try:
        # Run the scheduled task
        result = subprocess.run(
            ['schtasks', '/run', '/tn', task_name],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            # Wait for service to restart
            time.sleep(3)
            return {
                'success': True,
                'message': f"Successfully initiated restart for {service_name} service"
            }
        else:
            return {
                'success': False,
                'message': f"Failed to restart {service_name}: {result.stderr}"
            }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'message': f"Timeout restarting {service_name} service"
        }
    except Exception as e:
        return {
            'success': False,
            'message': f"Error restarting {service_name}: {str(e)}"
        }


def get_service_status(service_name: str) -> dict:
    """Get the current status of a service"""
    service_map = {
        'admin': 'DPlayer-Admin',
        'main': 'DPlayer-Main',
        'thumbnail': 'DPlayer-Thumbnail'
    }

    if service_name not in service_map:
        return {'success': False, 'message': f'Invalid service: {service_name}'}

    try:
        result = subprocess.run(
            ['sc', 'query', service_map[service_name]],
            capture_output=True,
            text=True
        )

        if 'RUNNING' in result.stdout:
            return {'success': True, 'status': 'RUNNING', 'details': result.stdout}
        elif 'STOPPED' in result.stdout:
            return {'success': True, 'status': 'STOPPED', 'details': result.stdout}
        else:
            return {'success': True, 'status': 'UNKNOWN', 'details': result.stdout}
    except Exception as e:
        return {'success': False, 'message': f'Error: {str(e)}'}


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python service_manager.py [restart|status] [admin|main|thumbnail|all]")
        sys.exit(1)

    action = sys.argv[1]
    service = sys.argv[2] if len(sys.argv) > 2 else None

    if action == 'restart' and service:
        result = restart_service(service)
        print(f"{'SUCCESS' if result['success'] else 'FAILED'}: {result['message']}")

    elif action == 'status' and service:
        result = get_service_status(service)
        print(f"Service: {service}")
        print(f"Status: {result.get('status', 'UNKNOWN')}")
        print(f"Success: {result['success']}")

    else:
        print("Invalid command")
        sys.exit(1)
