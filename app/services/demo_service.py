"""
演示模式服务
管理真实/演示模式切换，通过 cookie 持久化
"""
import os
from fastapi import Request

DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "")
COOKIE_NAME = "ls_mode"


def is_demo_mode(request: Request) -> bool:
    """
    判断当前是否为演示模式
    默认（无 cookie）= 真实模式
    cookie = "demo" = 演示模式
    """
    return request.cookies.get(COOKIE_NAME) == "demo"


def verify_password(password: str) -> bool:
    """验证密码是否正确"""
    if not DEMO_PASSWORD:
        return False
    return password == DEMO_PASSWORD
