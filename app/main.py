import os
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import scheduler as sch
from app.auth import auth_user, change_sys_password, ensure_sys_account, login_system, logout_system
from app.mteam import client
from app.store import (
    actions_last_hour,
    add_wish,
    append_access_log,
    append_ink_log,
    append_log,
    count_logs,
    delete_wish,
    ensure_dirs,
    ensure_wish_token,
    load_config,
    load_profile_history,
    load_profile_snapshot,
    load_ratio_tips,
    load_tasks,
    load_wishes,
    read_logs,
    remove_task,
    save_config,
    update_wish,
)

ROOT = Path(__file__).resolve().parent.parent


def app_version() -> str:
    v = (os.environ.get("APP_VERSION") or "").strip()
    if v and v != "0.0.0":
        return v
    for p in (ROOT / "VERSION", Path("/app/VERSION")):
        try:
            if p.exists():
                t = p.read_text(encoding="utf-8").strip()
                if t:
                    return t
        except Exception:
            pass
    return "dev"


ensure_dirs()
ensure_sys_account()
app = FastAPI(title="种控台", version=app_version())
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def access_logger(request, call_next):
    path = request.url.path
    resp = await call_next(request)
    skip = (
        "/api/logs",
        "/api/dashboard",
        "/api/scheduler/status",
        "/api/auth/me",
        "/api/personal",
    )
    if path.startswith("/api/") and path not in skip:
        try:
            append_access_log(
                f"{request.method} {path} -> {resp.status_code}",
                action="http",
                method=request.method,
                path=path,
                status=resp.status_code,
                ip=request.client.host if request.client else "-",
            )
        except Exception:
            pass
    return resp


class SysLoginIn(BaseModel):
    username: str
    password: str


class PassIn(BaseModel):
    old_password: str
    new_password: str


class ConfigIn(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    web_base: Optional[str] = None
    proxy: Optional[str] = None
    keywords: Optional[List[str]] = None
    exclude_keywords: Optional[List[str]] = None
    keyword_match: Optional[str] = None
    mode: Optional[str] = None
    interval_min: Optional[int] = None
    interval_max: Optional[int] = None
    page_size: Optional[int] = None
    auto_download: Optional[bool] = None
    hobby_max_versions: Optional[int] = None
    human_mode: Optional[bool] = None
    action_delay_min: Optional[float] = None
    action_delay_max: Optional[float] = None
    page_delay_min: Optional[float] = None
    page_delay_max: Optional[float] = None
    max_actions_per_hour: Optional[int] = None
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None
    ua_rotate: Optional[bool] = None
    client_version: Optional[str] = None
    web_version: Optional[str] = None
    ratio_assist: Optional[bool] = None
    ratio_max_size_gb: Optional[float] = None
    ratio_min_size_gb: Optional[float] = None
    ratio_min_seeders: Optional[int] = None
    ratio_max_seeders: Optional[int] = None
    ratio_min_leechers: Optional[int] = None
    ratio_pages: Optional[int] = None
    ratio_prefer_free: Optional[bool] = None
    ratio_top_n: Optional[int] = None
    ratio_auto_download: Optional[bool] = None
    ratio_schedule_enabled: Optional[bool] = None
    ratio_schedule_start: Optional[str] = None
    ratio_schedule_end: Optional[str] = None
    ratio_schedule_weekdays: Optional[list] = None
    tr_servers: Optional[list] = None
    tr_default_id: Optional[str] = None
    tr_auto_server_id: Optional[str] = None
    tr_ratio_server_id: Optional[str] = None
    tr_auto_hobby: Optional[bool] = None
    tr_auto_ratio: Optional[bool] = None
    tr_auto_manual: Optional[bool] = None
    tr_manage_enabled: Optional[bool] = None
    tr_manage_interval_min: Optional[int] = None
    tr_manage_delete_data: Optional[bool] = None
    tr_manage_only_finished: Optional[bool] = None
    tr_manage_rule_ratio: Optional[bool] = None
    tr_manage_min_ratio: Optional[float] = None
    tr_manage_rule_seed_days: Optional[bool] = None
    tr_manage_seed_days: Optional[float] = None
    tr_manage_rule_idle_days: Optional[bool] = None
    tr_manage_idle_days: Optional[float] = None
    tr_manage_rule_error: Optional[bool] = None
    tr_manage_rule_max_seed: Optional[bool] = None
    tr_manage_max_seed: Optional[int] = None
    checkin_enabled: Optional[bool] = None
    checkin_start: Optional[str] = None
    checkin_end: Optional[str] = None
    checkin_min_actions: Optional[int] = None
    checkin_max_actions: Optional[int] = None
    wish_enabled: Optional[bool] = None
    wish_title: Optional[str] = None
    wish_intro: Optional[str] = None
    ink_city: Optional[str] = None
    ink_wt: Optional[str] = None


class WishSubmitIn(BaseModel):
    nickname: str = ""
    keywords: str
    note: str = ""


class WishStatusIn(BaseModel):
    status: str


class SiteLoginIn(BaseModel):
    username: str
    password: str
    captcha: str
    captcha_id: str = ""


class DownloadIn(BaseModel):
    torrent_id: str
    name: str = ""
    server_id: str = ""


class TrTestIn(BaseModel):
    server_id: Optional[str] = None
    name: Optional[str] = None
    url: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    download_dir: Optional[str] = None
    paused: Optional[bool] = None


def _mask_cfg(cfg: dict) -> dict:
    from app.transmission import mask_servers

    safe = dict(cfg)
    safe.pop("sys_password", None)
    if safe.get("password"):
        safe["password"] = "******"
    safe["tr_servers"] = mask_servers(safe.get("tr_servers") or [])
    safe.pop("tr_pass", None)
    key = (safe.get("api_key") or "").strip()
    if key:
        safe["api_key_set"] = True
        safe["api_key_fp"] = f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "****"
    else:
        safe["api_key_set"] = False
        safe["api_key_fp"] = ""
    safe["api_key"] = ""
    return safe


class TestKeyIn(BaseModel):
    api_key: Optional[str] = None
    api_base: Optional[str] = None


@app.post("/api/site/test")
def site_test(body: Optional[TestKeyIn] = None, user: str = Depends(auth_user)):
    try:
        body = body or TestKeyIn()
        if body.api_base:
            cfg = load_config()
            cfg["api_base"] = body.api_base.strip()
            save_config(cfg)
        return client.test_connection(api_key=body.api_key)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/site/clear_key")
def clear_key(user: str = Depends(auth_user)):
    cfg = load_config()
    cfg["api_key"] = ""
    save_config(cfg)
    append_log("已清除 API Key")
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/wish/{token}")
def wish_page(token: str):
    return FileResponse(Path(__file__).resolve().parent.parent / "static" / "wish.html")


_wish_rate: dict = {}


def _wish_cfg_ok(token: str) -> dict:
    cfg = load_config()
    if not cfg.get("wish_enabled"):
        raise HTTPException(404, "收集页未开启")
    if (cfg.get("wish_token") or "").strip() != (token or "").strip():
        raise HTTPException(404, "链接无效或已失效")
    return cfg


@app.get("/api/public/wish/{token}")
def public_wish_meta(token: str):
    cfg = _wish_cfg_ok(token)
    return {
        "title": cfg.get("wish_title") or "想看清单",
        "intro": cfg.get("wish_intro") or "留下片名或关键词，我们会参考收录到监控列表。",
    }


@app.post("/api/public/wish/{token}")
def public_wish_submit(token: str, body: WishSubmitIn, request: Request):
    import time

    _wish_cfg_ok(token)
    kw = (body.keywords or "").strip()
    if not kw:
        raise HTTPException(400, "请填写感兴趣的内容")
    ip = request.client.host if request.client else "-"
    now = time.time()
    last = _wish_rate.get(ip) or 0
    if now - last < 30:
        raise HTTPException(429, "提交太频繁，请稍后再试")
    _wish_rate[ip] = now
    item = add_wish({
        "nickname": body.nickname,
        "keywords": kw,
        "note": body.note,
        "ip": ip,
        "ua": (request.headers.get("user-agent") or "")[:200],
    })
    append_access_log(
        f"兴趣收集 昵称={item['nickname']} 关键词={item['keywords']}",
        action="wish_collect",
        nickname=item["nickname"],
        keywords=item["keywords"],
        note=item.get("note") or "",
        wish_id=item["id"],
        ip=ip,
    )
    return {"ok": True, "id": item["id"]}


@app.get("/api/wish/info")
def wish_info(user: str = Depends(auth_user)):
    cfg = load_config()
    token = (cfg.get("wish_token") or "").strip()
    items = load_wishes()
    return {
        "enabled": bool(cfg.get("wish_enabled")),
        "token": token,
        "title": cfg.get("wish_title") or "想看清单",
        "intro": cfg.get("wish_intro") or "",
        "path": f"/wish/{token}" if token else "",
        "total": len(items),
        "new_count": len([x for x in items if x.get("status") == "new"]),
    }


@app.post("/api/wish/token")
def wish_regen_token(user: str = Depends(auth_user)):
    token = ensure_wish_token(force=True)
    cfg = load_config()
    cfg["wish_enabled"] = True
    cfg["wish_token"] = token
    save_config(cfg)
    append_access_log("已生成兴趣收集链接", action="wish_collect", event="regen", token_fp=token[:6])
    return {"ok": True, "token": token, "path": f"/wish/{token}", "enabled": True}


@app.get("/api/wish/submissions")
def wish_list(user: str = Depends(auth_user)):
    return {"items": load_wishes()}


@app.post("/api/wish/{wish_id}/status")
def wish_set_status(wish_id: str, body: WishStatusIn, user: str = Depends(auth_user)):
    st = (body.status or "").strip()
    if st not in ("new", "adopted", "ignored"):
        raise HTTPException(400, "无效状态")
    from app.timeutil import now_str

    fields = {"status": st}
    if st == "adopted":
        fields["adopted_at"] = now_str()
    row = update_wish(wish_id, **fields)
    if not row:
        raise HTTPException(404, "记录不存在")
    return {"ok": True, "item": row}


@app.post("/api/wish/{wish_id}/adopt")
def wish_adopt(wish_id: str, user: str = Depends(auth_user)):
    from app.timeutil import now_str

    items = load_wishes()
    row = next((x for x in items if str(x.get("id")) == str(wish_id)), None)
    if not row:
        raise HTTPException(404, "记录不存在")
    parts = [x.strip() for x in (row.get("keywords") or "").replace("，", ",").split(",") if x.strip()]
    if not parts:
        raise HTTPException(400, "无关键词可采纳")
    cfg = load_config()
    kws = list(cfg.get("keywords") or [])
    added = []
    for p in parts:
        if p not in kws:
            kws.append(p)
            added.append(p)
    cfg["keywords"] = kws
    save_config(cfg)
    updated = update_wish(
        wish_id,
        status="adopted",
        adopted_at=now_str(),
    )
    append_access_log(
        f"采纳兴趣关键词 +{added or parts}",
        action="wish_collect",
        event="adopt",
        wish_id=wish_id,
        added=added or parts,
    )
    return {"ok": True, "added": added, "keywords": kws, "item": updated}


@app.delete("/api/wish/{wish_id}")
def wish_delete(wish_id: str, user: str = Depends(auth_user)):
    if not delete_wish(wish_id):
        raise HTTPException(404, "记录不存在")
    return {"ok": True}


@app.post("/api/auth/login")
def sys_login(body: SysLoginIn):
    try:
        return login_system(body.username.strip(), body.password)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/logout")
def sys_logout(authorization: Optional[str] = Header(None), user: str = Depends(auth_user)):
    if authorization and authorization.startswith("Bearer "):
        logout_system(authorization[7:].strip())
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: str = Depends(auth_user)):
    return {"username": user}


@app.post("/api/auth/password")
def pwd(body: PassIn, user: str = Depends(auth_user)):
    try:
        change_sys_password(body.old_password, body.new_password)
        append_log(f"系统密码已修改 by {user}")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/config")
def get_config(user: str = Depends(auth_user)):
    return _mask_cfg(load_config())


@app.post("/api/config")
def update_config(body: ConfigIn, user: str = Depends(auth_user)):
    import uuid

    cfg = load_config()
    data = body.model_dump(exclude_none=True)
    if data.get("password") == "******":
        data.pop("password")
    if "tr_servers" in data:
        old_map = {str(s.get("id")): s for s in (cfg.get("tr_servers") or [])}
        cleaned = []
        for s in data["tr_servers"] or []:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or "").strip() or str(uuid.uuid4())[:8]
            old = old_map.get(sid) or {}
            pwd = s.get("pass")
            if pwd in (None, "", "******"):
                pwd = old.get("pass") or ""
            cleaned.append({
                "id": sid,
                "name": (s.get("name") or "未命名").strip() or "未命名",
                "enabled": bool(s.get("enabled", True)),
                "url": (s.get("url") or "").strip(),
                "user": (s.get("user") or "").strip(),
                "pass": pwd,
                "download_dir": (s.get("download_dir") or "").strip(),
                "paused": bool(s.get("paused", False)),
            })
        data["tr_servers"] = cleaned
        if cleaned and not data.get("tr_default_id") and not cfg.get("tr_default_id"):
            data["tr_default_id"] = cleaned[0]["id"]
        if cleaned and not data.get("tr_auto_server_id") and not cfg.get("tr_auto_server_id"):
            data["tr_auto_server_id"] = cleaned[0]["id"]
        if cleaned and not data.get("tr_ratio_server_id") and not cfg.get("tr_ratio_server_id"):
            data["tr_ratio_server_id"] = cleaned[0]["id"]
        ids = {s["id"] for s in cleaned}
        for key in ("tr_default_id", "tr_auto_server_id", "tr_ratio_server_id"):
            cur = (data.get(key) if key in data else cfg.get(key)) or ""
            if cur and cur not in ids and cleaned:
                data[key] = cleaned[0]["id"]
    ak = (data.get("api_key") or "").strip().strip('"').strip("'")
    ak = "".join(ak.split())
    if not ak or "****" in ak:
        data.pop("api_key", None)
    else:
        data["api_key"] = ak
    if "ratio_schedule_weekdays" in data:
        days = []
        for x in data["ratio_schedule_weekdays"] or []:
            try:
                d = int(x)
            except Exception:
                continue
            if 0 <= d <= 6 and d not in days:
                days.append(d)
        data["ratio_schedule_weekdays"] = days or [0, 1, 2, 3, 4, 5, 6]
    cfg.update(data)
    save_config(cfg)
    if any(k.startswith("checkin_") for k in data.keys()):
        try:
            if cfg.get("checkin_enabled"):
                sch.schedule_checkin()
            else:
                sch.stop_checkin()
        except Exception:
            pass
    if any(k.startswith("ratio_schedule_") for k in data.keys()):
        try:
            if cfg.get("ratio_schedule_enabled"):
                sch.schedule_ratio()
            else:
                sch.stop_ratio()
        except Exception:
            pass
    if any(k.startswith("tr_manage_") for k in data.keys()):
        try:
            if cfg.get("tr_manage_enabled"):
                sch.schedule_tr_manage(delay_sec=15)
            else:
                sch.stop_tr_manage()
        except Exception:
            pass
    append_log(f"配置已更新 by {user}")
    return {"ok": True, "api_key_set": bool(cfg.get("api_key"))}


@app.get("/api/transmission/servers")
def tr_servers(user: str = Depends(auth_user)):
    from app.transmission import mask_servers

    cfg = load_config()
    return {
        "items": mask_servers(cfg.get("tr_servers") or []),
        "default_id": cfg.get("tr_default_id") or "",
        "auto_server_id": cfg.get("tr_auto_server_id") or "",
        "ratio_server_id": cfg.get("tr_ratio_server_id") or "",
    }


@app.post("/api/transmission/test")
def transmission_test(body: Optional[TrTestIn] = None, user: str = Depends(auth_user)):
    from app.transmission import TransmissionClient, get_server

    try:
        body = body or TrTestIn()
        if body.server_id:
            server = get_server(body.server_id)
        elif body.url:
            server = {
                "id": "tmp",
                "name": body.name or "测试",
                "enabled": True,
                "url": body.url,
                "user": body.user or "",
                "pass": body.password or "",
                "download_dir": body.download_dir or "",
                "paused": bool(body.paused),
            }
            if not server["pass"] and body.server_id:
                server["pass"] = get_server(body.server_id).get("pass") or ""
        else:
            server = get_server()
        return TransmissionClient(server).test()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/transmission/torrents")
def transmission_torrents(server_id: str = "", user: str = Depends(auth_user)):
    from app.transmission import collect_tr_overview

    try:
        return collect_tr_overview(server_id or None)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/transmission/stats")
def transmission_stats(server_id: str = "", user: str = Depends(auth_user)):
    from app.transmission import collect_tr_overview

    try:
        data = collect_tr_overview(server_id or None)
        return {
            "ok": True,
            "stats": data.get("stats") or {},
            "servers": data.get("servers") or [],
            "errors": data.get("errors") or [],
            "torrent_count": len(data.get("items") or []),
        }
    except Exception as e:
        raise HTTPException(400, str(e))


class TrActionIn(BaseModel):
    server_id: str
    torrent_ids: List[int]
    action: str


class TrManageRunIn(BaseModel):
    dry_run: Optional[bool] = False


@app.post("/api/transmission/action")
def transmission_action(body: TrActionIn, user: str = Depends(auth_user)):
    from app.transmission import torrent_action

    try:
        return torrent_action(body.server_id, body.torrent_ids or [], body.action)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/transmission/manage/run")
def transmission_manage_run(body: Optional[TrManageRunIn] = None, user: str = Depends(auth_user)):
    from app.transmission import run_tr_manage

    dry = bool(body.dry_run) if body else False
    try:
        result = run_tr_manage(dry_run=dry)
        if load_config().get("tr_manage_enabled"):
            sch.schedule_tr_manage()
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/captcha")
def captcha(user: str = Depends(auth_user)):
    try:
        return client.fetch_captcha()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/site/login")
def site_login(body: SiteLoginIn, user: str = Depends(auth_user)):
    try:
        cfg = load_config()
        pwd = body.password
        if not pwd or pwd == "******":
            pwd = cfg.get("password") or ""
        if not pwd:
            raise RuntimeError("请填写站点密码")
        cfg["username"] = body.username
        cfg["password"] = pwd
        save_config(cfg)
        return client.login(body.username, pwd, body.captcha, body.captcha_id)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/profile")
def profile(user: str = Depends(auth_user)):
    try:
        return client.profile()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/personal")
def personal_cached(user: str = Depends(auth_user)):
    snap = load_profile_snapshot()
    history = load_profile_history(120)
    tasks = load_tasks()
    hobby = [x for x in tasks if (x.get("source") or "hobby") == "hobby"]
    sys = {
        "task_total": len(hobby),
        "task_downloaded": len([x for x in hobby if x.get("status") == "downloaded"]),
        "task_pending": len([x for x in hobby if x.get("status") in ("pending", "matched")]),
        "task_failed": len([x for x in hobby if x.get("status") == "failed"]),
        "actions_last_hour": actions_last_hour(),
        "download_logs": count_logs("download"),
        "access_logs": count_logs("access"),
        "pt_logs": count_logs("pt"),
        "ink_logs": count_logs("ink"),
    }
    return {"stats": snap, "history": history, "system": sys, "fresh": False}


@app.post("/api/personal/refresh")
def personal_refresh(user: str = Depends(auth_user)):
    try:
        stats = client.personal_stats(save=True)
        history = load_profile_history(120)
        tasks = load_tasks()
        hobby = [x for x in tasks if (x.get("source") or "hobby") == "hobby"]
        sys = {
            "task_total": len(hobby),
            "task_downloaded": len([x for x in hobby if x.get("status") == "downloaded"]),
            "task_pending": len([x for x in hobby if x.get("status") in ("pending", "matched")]),
            "task_failed": len([x for x in hobby if x.get("status") == "failed"]),
            "actions_last_hour": actions_last_hour(),
            "download_logs": count_logs("download"),
            "access_logs": count_logs("access"),
            "pt_logs": count_logs("pt"),
            "ink_logs": count_logs("ink"),
        }
        return {"stats": stats, "history": history, "system": sys, "fresh": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/scan")
def scan_once(user: str = Depends(auth_user)):
    try:
        return client.match_and_download()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/ratio/tips")
def ratio_tips(user: str = Depends(auth_user)):
    try:
        return {"items": client.ratio_tips()}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/ratio/tips")
def ratio_tips_cached(user: str = Depends(auth_user)):
    return {"items": load_ratio_tips()}


@app.post("/api/download")
def download(body: DownloadIn, user: str = Depends(auth_user)):
    try:
        path = client.download_torrent(
            body.torrent_id,
            body.name,
            source="manual",
            human=False,
        )
        p = Path(path)
        data = p.read_bytes()
        fname = p.name
        return Response(
            content=data,
            media_type="application/x-bittorrent",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}",
                "X-Saved-Path": str(p.name),
            },
        )
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/download/tr")
def download_tr(body: DownloadIn, user: str = Depends(auth_user)):
    try:
        return client.download_to_tr(body.torrent_id, body.name, server_id=body.server_id or None)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/downloads/file/{torrent_id}")
def download_saved_file(torrent_id: str, user: str = Depends(auth_user)):
    from app.store import DOWNLOAD_DIR, load_tasks

    tid = str(torrent_id)
    for t in load_tasks():
        if str(t.get("id")) == tid and t.get("file"):
            path = DOWNLOAD_DIR / t["file"]
            if path.exists():
                return FileResponse(
                    path,
                    media_type="application/x-bittorrent",
                    filename=path.name,
                )
    matches = list(DOWNLOAD_DIR.glob(f"{tid}_*.torrent"))
    if not matches:
        raise HTTPException(404, "本地种子不存在，请先重新下载")
    path = matches[0]
    return FileResponse(path, media_type="application/x-bittorrent", filename=path.name)

@app.get("/api/tasks")
def list_tasks(source: str = "hobby", aligned: int = 1, user: str = Depends(auth_user)):
    items = load_tasks()
    if source and source != "all":
        items = [x for x in items if (x.get("source") or "hobby") == source]
    if aligned and source == "hobby":
        cfg = load_config()
        keywords = [k.strip() for k in cfg.get("keywords") or [] if k.strip()]
        exclude = [k.strip() for k in cfg.get("exclude_keywords") or [] if k.strip()]
        match = cfg.get("keyword_match") or "any"
        if not keywords:
            items = []
        else:
            items = [
                x for x in items
                if client._match_kw(
                    x.get("name") or "",
                    keywords,
                    exclude,
                    match,
                    extra=client._task_text(x),
                )
            ]
    return {"items": items, "total": len(items)}


@app.post("/api/tasks/prune")
def prune_tasks(user: str = Depends(auth_user)):
    try:
        return client.prune_hobby_tasks()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/tasks/enrich")
def enrich_tasks(user: str = Depends(auth_user)):
    try:
        return client.enrich_tasks()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/tasks/{torrent_id}")
def delete_task(torrent_id: str, user: str = Depends(auth_user)):
    ok = remove_task(torrent_id)
    if not ok:
        raise HTTPException(404, "任务不存在")
    return {"ok": True}

@app.post("/api/scheduler/start")
def start(user: str = Depends(auth_user)):
    sch.start_scheduler()
    return sch.status()


@app.post("/api/scheduler/stop")
def stop(user: str = Depends(auth_user)):
    sch.stop_scheduler()
    return sch.status()


@app.get("/api/scheduler/status")
def sched_status(user: str = Depends(auth_user)):
    return sch.status()


@app.post("/api/checkin/run")
def checkin_run(user: str = Depends(auth_user)):
    try:
        result = client.auto_checkin()
        if load_config().get("checkin_enabled"):
            sch.schedule_checkin()
        return result
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/checkin/status")
def checkin_status(user: str = Depends(auth_user)):
    st = sch.status()
    cfg = load_config()
    return {
        "enabled": bool(cfg.get("checkin_enabled")),
        "start": cfg.get("checkin_start") or "09:00",
        "end": cfg.get("checkin_end") or "12:00",
        "min_actions": cfg.get("checkin_min_actions") or 2,
        "max_actions": cfg.get("checkin_max_actions") or 5,
        "last_at": cfg.get("checkin_last_at") or "",
        "next_at": st.get("checkin_next_at") or cfg.get("checkin_next_at") or "",
    }


@app.get("/api/logs")
def logs(page: int = 1, page_size: int = 50, kind: str = "access", user: str = Depends(auth_user)):
    k = kind if kind in ("access", "pt", "download", "ink") else "access"
    data = read_logs(limit=page_size, kind=k, page=page)
    return {"kind": k, "actions_last_hour": actions_last_hour(), **data}


@app.get("/api/version")
def get_version():
    return {"version": app_version()}


def _lan_ips() -> list:
    import socket

    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            found.append(ip)
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except Exception:
        pass
    return found


@app.get("/api/lan")
def get_lan(request: Request, user: str = Depends(auth_user)):
    port = request.url.port or int(os.environ.get("PORT") or "8080")
    ips = _lan_ips()
    return {
        "ips": ips,
        "port": port,
        "urls": [f"http://{ip}:{port}/generate-image" for ip in ips],
    }


@app.get("/api/dashboard")
def dashboard(user: str = Depends(auth_user)):
    cfg = load_config()
    st = sch.status()
    return {
        "running": st["running"],
        "next_run": st.get("next_run"),
        "keywords": len(cfg.get("keywords") or []),
        "actions_last_hour": actions_last_hour(),
        "max_actions": cfg.get("max_actions_per_hour"),
        "human_mode": cfg.get("human_mode"),
        "ratio_assist": cfg.get("ratio_assist"),
        "api_key_set": bool(cfg.get("api_key")),
        "quiet": st.get("quiet"),
        "ratio_tips": load_ratio_tips()[:5],
        "task_count": len([x for x in load_tasks() if (x.get("source") or "hobby") == "hobby"]),
        "recent_downloads": [x.get("message") for x in read_logs(5, "download")["items"]],
        "recent_pt": [x.get("message") for x in read_logs(5, "pt")["items"]],
        "version": app_version(),
    }


def _ink_meta(request: Request) -> dict:
    q = request.query_params
    hmap = {}
    for k, v in request.headers.items():
        if v is None or str(v) == "":
            continue
        hmap[k.lower()] = str(v).strip()
    # ASGI 原始头（防中间层改写后遗漏）
    try:
        for kb, vb in request.scope.get("headers") or []:
            k = kb.decode("latin-1").lower()
            v = vb.decode("latin-1").strip()
            if v and k not in hmap:
                hmap[k] = v
    except Exception:
        pass

    def pick(*keys):
        for k in keys:
            v = q.get(k)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        for k in keys:
            v = hmap.get(k.lower())
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        return ""

    # 文档参数：battery / fwv / devid / model；兼容 Demo：x-* 头与 bv/logs
    battery = pick("battery", "x-battery", "x_battery", "bat", "soc")
    bv = pick("bv", "x-bv", "x_bv", "batteryvalue", "battery_value", "voltage", "volt")
    fwv = pick("fwv", "x-fwv", "x_fwv")
    devid = pick("devid", "x-devid", "x_devid", "dev_id", "deviceid", "device-id", "devId")
    model = pick("model", "x-model", "x_model")
    logs = pick("logs", "x-logs", "x_logs")
    headers = {
        "battery": battery,
        "fwv": fwv,
        "devid": devid,
        "model": model,
    }
    if bv:
        headers["bv"] = bv
    if logs:
        headers["logs"] = logs[:200]
    return {
        "battery": battery,
        "bv": bv,
        "fwv": fwv,
        "devid": devid,
        "model": model,
        "logs": logs,
        "headers": headers,
    }


@app.get("/generate-image")
def generate_image(request: Request, istest: str = ""):
    import io

    from PIL import Image

    from app.ink import _apply_device_battery_cache, _parse_battery, build_panel, fetch_ota

    meta = _apply_device_battery_cache(_ink_meta(request))
    buf = build_panel(meta)
    wt = str(load_config().get("ink_wt") or "0").strip()
    # 文档：'0' 1小时 / '1' 2小时 / '1010' 10分钟 / Demo '1005' 5分钟
    if not wt.isdigit():
        wt = "0"
    src = "preview" if istest else "device"
    bat = (meta.get("battery") or "").strip()
    bv = (meta.get("bv") or "").strip()
    devid = (meta.get("devid") or "").strip()
    model = (meta.get("model") or "").strip()
    fwv = (meta.get("fwv") or "").strip()
    dlogs = (meta.get("logs") or "").strip()
    bat_n = _parse_battery(meta)
    ip = request.client.host if request.client else ""

    ota = {"ok": False, "fver": "1.0.0", "fmd5": "", "error": "", "miss": True}
    if not istest:
        ota = fetch_ota(model, devid)
        ota_model = (ota.get("model") or model or "").strip()
        ota_devid = (ota.get("devid") or devid or "").strip()
        try:
            if ota.get("ok"):
                append_ink_log(
                    f"OTA升级信息 model={ota_model or '-'} devid={ota_devid or '-'} "
                    f"fwv={fwv or '-'} → fver={ota.get('fver') or '-'} fmd5={ota.get('fmd5') or '-'}",
                    action="ota_upgrade",
                    model=ota_model,
                    devid=ota_devid,
                    fwv=fwv,
                    fver=ota.get("fver") or "",
                    fmd5=ota.get("fmd5") or "",
                    ip=ip,
                )
            else:
                append_ink_log(
                    f"OTA升级信息未更新 model={ota_model or '-'} devid={ota_devid or '-'} "
                    f"{ota.get('error') or ota.get('hint') or '无可用固件'} → fver={ota.get('fver') or '1.0.0'}",
                    action="ota_upgrade",
                    level="warn" if (ota.get("error") or ota.get("hint")) else "info",
                    model=ota_model,
                    devid=ota_devid,
                    fwv=fwv,
                    fver=ota.get("fver") or "1.0.0",
                    fmd5=ota.get("fmd5") or "",
                    error=ota.get("error") or "",
                    hint=ota.get("hint") or "",
                    ip=ip,
                )
        except Exception:
            pass
        if dlogs:
            try:
                append_ink_log(
                    f"设备上报 model={model or '-'} devid={devid or '-'} {dlogs[:500]}",
                    action="device_logs",
                    model=model,
                    devid=devid,
                    fwv=fwv,
                    logs=dlogs[:2000],
                    ip=ip,
                )
            except Exception:
                pass

    ota_ok = bool(ota.get("ok"))
    fver = (ota.get("fver") or "").strip() if ota_ok else ""
    fmd5 = (ota.get("fmd5") or "").strip() if ota_ok else ""

    headers = meta.get("headers") if isinstance(meta.get("headers"), dict) else {}
    hdr_txt = "; ".join(f"{k}={v if v != '' else '-'}" for k, v in headers.items())
    bits = [
        f"墨水屏刷新[{src}]",
        f"{len(buf)}B",
        f"model={model or '-'}",
        f"devId={devid or '-'}",
    ]
    if bat_n is not None:
        bits.append(f"电量{bat_n}%")
    elif bv:
        bits.append(f"bv={bv}")
    if fwv:
        bits.append(f"固件{fwv}")
    if fver:
        bits.append(f"OTA{fver}")
    if not istest:
        bits.append(f"wt={wt}")
    bits.append(f"headers[{hdr_txt}]")
    try:
        append_ink_log(
            " ".join(bits),
            action="ink_refresh",
            source=src,
            battery=bat,
            bv=bv,
            battery_pct=bat_n if bat_n is not None else "",
            model=model,
            devid=devid,
            fwv=fwv,
            bytes=len(buf),
            fver=fver,
            fmd5=fmd5,
            wt="" if istest else wt,
            headers=hdr_txt,
            ip=ip,
        )
    except Exception:
        pass
    if istest:
        im = Image.open(io.BytesIO(buf)).convert("RGB")
        im = im.resize((im.width * 2, im.height * 2), Image.Resampling.NEAREST)
        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        data = out.getvalue()
        return Response(
            content=data,
            media_type="image/png",
            headers={"Content-Length": str(len(data)), "Cache-Control": "no-store"},
        )
    headers = {
        "Content-Disposition": 'attachment; filename="time-info.bmp"',
        "Content-Type": "image/bmp",
        "Content-Length": str(len(buf)),
        "Connection": "close",
        "wt": wt,
        "fver": ota.get("fver") or "1.0.0",
        "fmd5": ota.get("fmd5") or "",
    }
    return Response(content=buf, media_type="image/bmp", headers=headers)


@app.on_event("startup")
def on_startup():
    ensure_sys_account()
    cfg = load_config()
    if cfg.get("running"):
        sch.start_scheduler()
        append_log("服务启动，恢复调度")
    if cfg.get("checkin_enabled"):
        sch.schedule_checkin()
        append_log("服务启动，恢复自动签到")
    if cfg.get("ratio_schedule_enabled"):
        sch.schedule_ratio()
        append_log("服务启动，恢复定时分享监控")
    if cfg.get("tr_manage_enabled"):
        sch.schedule_tr_manage(delay_sec=30)
        append_log("服务启动，恢复TR自动清理")
