import json
import os
from pathlib import Path
from threading import Lock

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "downloads"))
CONFIG_FILE = DATA_DIR / "config.json"
LOG_FILE = DATA_DIR / "ops.log"
ACCESS_LOG_FILE = DATA_DIR / "access.log"
PT_LOG_FILE = DATA_DIR / "pt.log"
DOWNLOAD_LOG_FILE = DATA_DIR / "download.log"
INK_LOG_FILE = DATA_DIR / "ink.log"
INK_DEVICE_FILE = DATA_DIR / "ink_device.json"
DOWNLOADED_FILE = DATA_DIR / "downloaded.json"
TASKS_FILE = DATA_DIR / "tasks.json"
RATIO_FILE = DATA_DIR / "ratio_tips.json"
PROFILE_FILE = DATA_DIR / "profile.json"
PROFILE_HISTORY_FILE = DATA_DIR / "profile_history.json"
WISH_FILE = DATA_DIR / "wish_submissions.json"

DEFAULT_CONFIG = {
    "sys_username": "admin",
    "sys_password": "admin123",
    "username": "",
    "password": "",
    "api_key": "",
    "api_base": "https://api.m-team.cc",
    "web_base": "https://kp.m-team.cc",
    "proxy": "",
    "mode": "movie",
    "page_size": 50,
    "auto_download": True,
    "hobby_max_versions": 3,
    "running": False,
    "keywords": [],
    "exclude_keywords": [],
    "keyword_match": "any",
    "interval_min": 300,
    "interval_max": 900,
    "human_mode": True,
    "action_delay_min": 2,
    "action_delay_max": 8,
    "page_delay_min": 5,
    "page_delay_max": 15,
    "max_actions_per_hour": 40,
    "quiet_start": "",
    "quiet_end": "",
    "ua_rotate": True,
    "client_version": "1.1.4",
    "web_version": "1140",
    "ratio_assist": True,
    "ratio_max_size_gb": 80,
    "ratio_min_size_gb": 5,
    "ratio_min_seeders": 1,
    "ratio_max_seeders": 8,
    "ratio_min_leechers": 0,
    "ratio_pages": 3,
    "ratio_prefer_free": True,
    "ratio_top_n": 8,
    "ratio_auto_download": False,
    "ratio_schedule_enabled": False,
    "ratio_schedule_start": "14:00",
    "ratio_schedule_end": "18:00",
    "ratio_schedule_weekdays": [0, 1, 2, 3, 4, 5, 6],
    "ratio_schedule_last_at": "",
    "ratio_schedule_next_at": "",
    "tr_servers": [],
    "tr_default_id": "",
    "tr_auto_server_id": "",
    "tr_ratio_server_id": "",
    "tr_auto_hobby": True,
    "tr_auto_ratio": True,
    "tr_auto_manual": True,
    "tr_manage_enabled": False,
    "tr_manage_interval_min": 60,
    "tr_manage_delete_data": True,
    "tr_manage_only_finished": True,
    "tr_manage_rule_ratio": True,
    "tr_manage_min_ratio": 1.0,
    "tr_manage_rule_seed_days": True,
    "tr_manage_seed_days": 3,
    "tr_manage_rule_idle_days": False,
    "tr_manage_idle_days": 7,
    "tr_manage_rule_error": False,
    "tr_manage_rule_max_seed": False,
    "tr_manage_max_seed": 100,
    "tr_manage_last_at": "",
    "tr_manage_next_at": "",
    "tr_manage_last_result": "",
    "checkin_enabled": False,
    "checkin_start": "09:00",
    "checkin_end": "12:00",
    "checkin_min_actions": 2,
    "checkin_max_actions": 5,
    "checkin_last_at": "",
    "checkin_next_at": "",
    "wish_enabled": False,
    "wish_token": "",
    "wish_title": "想看清单",
    "wish_intro": "留下片名或关键词，我们会参考收录到监控列表。",
    "ink_city": "四川省成都市郫都区",
    "ink_wt": "0",
}

_lock = Lock()
_hour_actions: list = []


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(data)
    from app.transmission import migrate_tr_servers

    before = bool(cfg.get("tr_servers"))
    cfg = migrate_tr_servers(cfg)
    if not before and cfg.get("tr_servers"):
        save_config(cfg)
    return cfg


def save_config(cfg: dict):
    ensure_dirs()
    with _lock:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_downloaded() -> set:
    ensure_dirs()
    if not DOWNLOADED_FILE.exists():
        return set()
    with open(DOWNLOADED_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_downloaded(ids: set):
    ensure_dirs()
    with _lock:
        with open(DOWNLOADED_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(ids), f, ensure_ascii=False)


def load_tasks() -> list:
    ensure_dirs()
    if not TASKS_FILE.exists():
        return []
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_tasks(items: list):
    ensure_dirs()
    with _lock:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)


def upsert_task(task: dict) -> dict:
    from app.timeutil import now_str

    items = load_tasks()
    tid = str(task.get("id") or "")
    now = now_str()
    task = dict(task)
    task["id"] = tid
    task["updated_at"] = now
    found = False
    for i, old in enumerate(items):
        if str(old.get("id")) == tid:
            merged = dict(old)
            merged.update(task)
            if not merged.get("created_at"):
                merged["created_at"] = now
            items[i] = merged
            task = merged
            found = True
            break
    if not found:
        task["created_at"] = now
        items.insert(0, task)
    save_tasks(items[:500])
    return task


def remove_task(torrent_id: str) -> bool:
    tid = str(torrent_id)
    items = load_tasks()
    new_items = [x for x in items if str(x.get("id")) != tid]
    if len(new_items) == len(items):
        return False
    save_tasks(new_items)
    return True


def save_ratio_tips(items: list):
    ensure_dirs()
    with _lock:
        with open(RATIO_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)


def load_ratio_tips() -> list:
    ensure_dirs()
    if not RATIO_FILE.exists():
        return []
    with open(RATIO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_profile_snapshot(stats: dict):
    from app.timeutil import now_str

    ensure_dirs()
    now = now_str()
    row = dict(stats)
    row["ts"] = now
    with _lock:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(row, f, ensure_ascii=False, indent=2)
        history = []
        if PROFILE_HISTORY_FILE.exists():
            try:
                with open(PROFILE_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f) or []
            except Exception:
                history = []
        if history:
            last = history[-1]
            same = all(
                str(last.get(k)) == str(row.get(k))
                for k in ("bonus", "share_rate", "uploaded", "downloaded", "seeding", "leeching", "invites", "invite_limit")
            )
            if same:
                history[-1] = row
            else:
                history.append(row)
        else:
            history.append(row)
        with open(PROFILE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-500:], f, ensure_ascii=False, indent=2)
    return row


def load_profile_snapshot() -> dict:
    ensure_dirs()
    if not PROFILE_FILE.exists():
        return {}
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        return json.load(f) or {}


def load_profile_history(limit: int = 100) -> list:
    ensure_dirs()
    if not PROFILE_HISTORY_FILE.exists():
        return []
    with open(PROFILE_HISTORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f) or []
    return data[-limit:]


def _append_event(kind: str, action: str, message: str, level: str = "info", detail: dict = None) -> dict:
    from app.timeutil import now_str

    ensure_dirs()
    path = {
        "access": ACCESS_LOG_FILE,
        "pt": PT_LOG_FILE,
        "download": DOWNLOAD_LOG_FILE,
        "ink": INK_LOG_FILE,
    }.get(kind, ACCESS_LOG_FILE)
    row = {
        "ts": now_str(),
        "level": level or "info",
        "kind": kind,
        "action": action or "event",
        "message": message or "",
        "detail": detail or {},
    }
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    return row


def append_log(msg: str, action: str = "system", level: str = "info", **detail):
    return append_access_log(msg, action=action, level=level, **detail)


def append_access_log(msg: str, action: str = "access", level: str = "info", **detail):
    return _append_event("access", action, msg, level=level, detail=detail or None)


def append_pt_log(msg: str, action: str = "pt", level: str = "info", **detail):
    return _append_event("pt", action, msg, level=level, detail=detail or None)


def append_download_log(msg: str, action: str = "download", level: str = "info", **detail):
    return _append_event("download", action, msg, level=level, detail=detail or None)


def append_ink_log(msg: str, action: str = "ink_refresh", level: str = "info", **detail):
    return _append_event("ink", action, msg, level=level, detail=detail or None)


def _ink_device_key(devid: str) -> str:
    return (devid or "").strip() or "_last"


def load_ink_devices() -> dict:
    ensure_dirs()
    if not INK_DEVICE_FILE.exists():
        return {}
    try:
        with open(INK_DEVICE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_ink_device(devid: str = "") -> dict:
    data = load_ink_devices()
    key = _ink_device_key(devid)
    row = data.get(key) if isinstance(data.get(key), dict) else None
    if row:
        return row
    if key != "_last" and isinstance(data.get("_last"), dict):
        return data["_last"]
    return {}


def save_ink_device(devid: str = "", **fields):
    from app.timeutil import now_str

    ensure_dirs()
    data = load_ink_devices()
    key = _ink_device_key(devid)
    row = dict(data.get(key) or {}) if isinstance(data.get(key), dict) else {}
    for k, v in (fields or {}).items():
        if v is None or v == "":
            continue
        row[k] = v
    row["ts"] = now_str()
    data[key] = row
    data["_last"] = dict(row)
    with _lock:
        with open(INK_DEVICE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return row


def seed_ink_device_from_logs():
    """从墨水屏日志回填最近一次电量到设备缓存。"""
    if load_ink_device("_last").get("battery_pct") not in (None, ""):
        return
    if not INK_LOG_FILE.exists():
        return
    try:
        with open(INK_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        detail = row.get("detail") or {}
        pct = detail.get("battery_pct")
        if pct in (None, ""):
            continue
        try:
            pct_n = int(pct)
        except Exception:
            continue
        save_ink_device(
            detail.get("devid") or "_last",
            battery_pct=pct_n,
            battery=detail.get("battery") or str(pct_n),
            bv=detail.get("bv") or "",
            model=detail.get("model") or "",
            fwv=detail.get("fwv") or "",
        )
        return


def _parse_log_line(line: str) -> dict:
    text = (line or "").rstrip("\n")
    if not text:
        return {}
    if text.startswith("{"):
        try:
            row = json.loads(text)
            if isinstance(row, dict) and row.get("message") is not None:
                return row
        except Exception:
            pass
    ts = ""
    msg = text
    if text.startswith("[") and "]" in text:
        ts = text[1:text.index("]")]
        msg = text[text.index("]") + 1 :].strip()
    return {"ts": ts, "level": "info", "action": "legacy", "message": msg, "detail": {}}


def _read_events(path: Path, limit: int = 50, page: int = 1) -> tuple:
    ensure_dirs()
    page = max(1, int(page or 1))
    limit = max(1, min(200, int(limit or 50)))
    if not path.exists():
        return [], 0, page, limit
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    items = []
    for line in lines:
        row = _parse_log_line(line)
        if row:
            items.append(row)
    items.reverse()
    total = len(items)
    offset = (page - 1) * limit
    return items[offset : offset + limit], total, page, limit


def read_logs(limit: int = 50, kind: str = "access", page: int = 1) -> dict:
    if kind == "download":
        path = DOWNLOAD_LOG_FILE
    elif kind == "pt":
        path = PT_LOG_FILE
    elif kind == "ink":
        path = INK_LOG_FILE
    else:
        path = ACCESS_LOG_FILE
        if not path.exists() and LOG_FILE.exists():
            path = LOG_FILE
    items, total, page, limit = _read_events(path, limit=limit, page=page)
    pages = max(1, (total + limit - 1) // limit) if total else 1
    if page > pages:
        page = pages
        items, total, page, limit = _read_events(path, limit=limit, page=page)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": limit,
        "pages": pages,
    }


def count_logs(kind: str = "access") -> int:
    path = {
        "download": DOWNLOAD_LOG_FILE,
        "pt": PT_LOG_FILE,
        "access": ACCESS_LOG_FILE,
        "ink": INK_LOG_FILE,
    }.get(kind, ACCESS_LOG_FILE)
    if not path.exists():
        if kind == "access" and LOG_FILE.exists():
            path = LOG_FILE
        else:
            return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def record_action():
    import time

    now = time.time()
    with _lock:
        _hour_actions[:] = [t for t in _hour_actions if now - t < 3600]
        _hour_actions.append(now)


def actions_last_hour() -> int:
    import time

    now = time.time()
    with _lock:
        _hour_actions[:] = [t for t in _hour_actions if now - t < 3600]
        return len(_hour_actions)


def load_wishes() -> list:
    ensure_dirs()
    if not WISH_FILE.exists():
        return []
    with open(WISH_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_wishes(items: list):
    ensure_dirs()
    with _lock:
        with open(WISH_FILE, "w", encoding="utf-8") as f:
            json.dump(items[:1000], f, ensure_ascii=False, indent=2)


def add_wish(row: dict) -> dict:
    from app.timeutil import now_str
    import uuid

    items = load_wishes()
    item = {
        "id": str(uuid.uuid4())[:8],
        "ts": now_str(),
        "nickname": (row.get("nickname") or "").strip()[:40] or "匿名",
        "keywords": (row.get("keywords") or "").strip()[:200],
        "note": (row.get("note") or "").strip()[:500],
        "ip": (row.get("ip") or "")[:64],
        "ua": (row.get("ua") or "")[:200],
        "status": "new",
        "adopted_at": "",
    }
    items.insert(0, item)
    save_wishes(items)
    return item


def update_wish(wish_id: str, **fields) -> dict:
    items = load_wishes()
    for i, x in enumerate(items):
        if str(x.get("id")) == str(wish_id):
            row = dict(x)
            row.update(fields)
            items[i] = row
            save_wishes(items)
            return row
    return {}


def delete_wish(wish_id: str) -> bool:
    items = load_wishes()
    new_items = [x for x in items if str(x.get("id")) != str(wish_id)]
    if len(new_items) == len(items):
        return False
    save_wishes(new_items)
    return True


def ensure_wish_token(force: bool = False) -> str:
    import secrets

    cfg = load_config()
    token = (cfg.get("wish_token") or "").strip()
    if force or not token:
        token = secrets.token_urlsafe(10)
        cfg["wish_token"] = token
        save_config(cfg)
    return token
