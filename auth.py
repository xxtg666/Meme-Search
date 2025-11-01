"""认证中间件模块"""
from fastapi import HTTPException, Security, Header
from typing import Optional
import config


def verify_admin_key(x_admin_key: Optional[str] = Header(None)):
    """验证管理员密钥"""
    if not x_admin_key:
        raise HTTPException(status_code=401, detail="缺少管理员密钥")
    if x_admin_key != config.ADMIN_SECRET_KEY:
        raise HTTPException(status_code=403, detail="管理员密钥无效")
    return x_admin_key
