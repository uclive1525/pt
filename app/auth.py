import os
import secrets
import time
from typing import Dict, Optional

from fastapi import Header, HTTPException

from app.store import load_config, save_config

_sessions: Dict[str, dict] = {}


def _sys_user() -> str:
    return os.getenv("SYS_USER") or load_config().get("sys_username") or "admin"


def _sys_pass() -> str:
    return os.getenv("SYS_PASS") or load_config().get("sys_password") or "admin123"


def ensure_sys_account():
    cfg = load_config()
    changed = False
    if not cfg.get("sys_username"):
        cfg["sys_username"] = "admin"
        changed = True
    if not cfg.get("sys_password"):
        cfg["sys_password"] = "admin123"
        changed = True
    if changed:
        save_config(cfg)


def login_system(username: str, password: str) -> dict:
    ensure_sys_account()
    if username != _sys_user() or password != _sys_pass():
        raise RuntimeError("账号或密码错误")
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"user": username, "exp": time.time() + 7 * 86400}
    return {"token": token, "username": username}


def logout_system(token: str):
    _sessions.pop(token, None)


def auth_user(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登录")
    token = authorization[7:].strip()
    sess = _sessions.get(token)
    if not sess or sess["exp"] < time.time():
        _sessions.pop(token, None)
        raise HTTPException(401, "登录已过期")
    return sess["user"]


def change_sys_password(old: str, new: str):
    if old != _sys_pass():
        raise RuntimeError("原密码错误")
    if len(new) < 4:
        raise RuntimeError("新密码至少4位")
    cfg = load_config()
    cfg["sys_password"] = new
    save_config(cfg)
