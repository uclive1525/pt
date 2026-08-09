import math
import random
import re
import time
from datetime import datetime
from typing import Optional

import httpx

from app.store import (
    DOWNLOAD_DIR,
    actions_last_hour,
    append_access_log,
    append_download_log,
    append_log,
    append_pt_log,
    load_config,
    load_downloaded,
    load_tasks,
    record_action,
    save_config,
    save_downloaded,
    save_profile_snapshot,
    save_ratio_tips,
    upsert_task,
)
from app.timeutil import APP_TZ, now

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


def _in_quiet_hours(cfg: dict) -> bool:
    qs, qe = (cfg.get("quiet_start") or "").strip(), (cfg.get("quiet_end") or "").strip()
    if not qs or not qe:
        return False
    try:
        from app.timeutil import now_hm

        now = now_hm()
        if qs <= qe:
            return qs <= now <= qe
        return now >= qs or now <= qe
    except Exception:
        return False


def human_sleep(kind: str = "action"):
    cfg = load_config()
    if not cfg.get("human_mode", True):
        return
    if kind == "page":
        lo = float(cfg.get("page_delay_min") or 5)
        hi = float(cfg.get("page_delay_max") or 15)
    else:
        lo = float(cfg.get("action_delay_min") or 2)
        hi = float(cfg.get("action_delay_max") or 8)
    if hi < lo:
        lo, hi = hi, lo
    sec = random.uniform(lo, hi)
    append_log(f"拟人等待 {sec:.1f}s ({kind})", action="human_delay", seconds=round(sec, 2), kind_delay=kind)
    time.sleep(sec)


def check_rate_limit():
    cfg = load_config()
    limit = int(cfg.get("max_actions_per_hour") or 40)
    n = actions_last_hour()
    if n >= limit:
        raise RuntimeError(f"小时操作上限已达 {n}/{limit}，暂停以避免风控")


def fmt_size(n) -> str:
    try:
        v = float(n)
    except Exception:
        return str(n or "-")
    for u in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024:
            return f"{v:.2f}{u}"
        v /= 1024
    return f"{v:.2f}PB"


def _parse_created(s: str):
    text = (s or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            chunk = text[:19] if "T" in text or " " in text else text[:10]
            return datetime.strptime(chunk, fmt if len(chunk) > 10 else "%Y-%m-%d").replace(tzinfo=APP_TZ)
        except Exception:
            continue
    return None


def _weeks_alive(created: str) -> float:
    dt = _parse_created(created)
    if not dt:
        return 0.0
    return max(0.0, (now() - dt).total_seconds() / (7 * 86400))


def _magic_a(size_gb: float, seeders: int, weeks: float) -> float:
    t0, n0 = 4.0, 7.0
    age = 1.0 - (10.0 ** (-(weeks / t0)))
    n = max(0, int(seeders or 0))
    seed_f = 1.0 + math.sqrt(2.0) * (10.0 ** (-(n - 1) / (n0 - 1)))
    return max(0.0, age * float(size_gb or 0) * seed_f)


def _magic_b(a: float) -> float:
    return 50.0 * (2.0 / math.pi) * math.atan(float(a or 0) / 300.0)


class MTeamClient:
    def __init__(self):
        self.token: Optional[str] = None
        self._captcha_id: Optional[str] = None
        self._ua = USER_AGENTS[0]

    def _cfg(self):
        return load_config()

    def _pick_ua(self) -> str:
        cfg = self._cfg()
        if cfg.get("ua_rotate", True):
            self._ua = random.choice(USER_AGENTS)
        return self._ua

    def _normalize_key(self, key: str) -> str:
        k = (key or "").strip().strip('"').strip("'")
        k = "".join(k.split())
        return k

    def _headers(self, json_body: bool = True, api_key: str = None) -> dict:
        cfg = self._cfg()
        key = self._normalize_key(api_key if api_key is not None else (cfg.get("api_key") or ""))
        h = {
            "User-Agent": self._pick_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": cfg["web_base"].rstrip("/") + "/",
            "Origin": cfg["web_base"].rstrip("/"),
        }
        if json_body:
            h["Content-Type"] = "application/json"
        if key:
            h["x-api-key"] = key
        return h

    def _client(self) -> httpx.Client:
        cfg = self._cfg()
        kwargs = {"timeout": 60.0, "follow_redirects": True}
        if cfg.get("proxy"):
            kwargs["proxy"] = cfg["proxy"]
        return httpx.Client(**kwargs)

    def _api(self, path: str) -> str:
        return self._cfg()["api_base"].rstrip("/") + path

    def _before_call(self, kind="action", human: bool = True):
        check_rate_limit()
        if human:
            human_sleep(kind)
        record_action()

    def test_connection(self, api_key: str = None) -> dict:
        cfg = self._cfg()
        key = self._normalize_key(api_key if api_key is not None else (cfg.get("api_key") or ""))
        if not key:
            raise RuntimeError("请先粘贴 API Key")
        bases = []
        for b in [cfg.get("api_base"), "https://api.m-team.cc", "https://api.m-team.io"]:
            b = (b or "").rstrip("/")
            if b and b not in bases:
                bases.append(b)
        last_msg = "连接失败"
        with self._client() as c:
            for base in bases:
                r = c.post(
                    base + "/api/member/profile",
                    headers=self._headers(api_key=key),
                    json={},
                )
                try:
                    data = r.json()
                except Exception:
                    last_msg = f"{base} HTTP {r.status_code}"
                    continue
                msg = data.get("message") or data.get("msg") or ""
                if data.get("code") not in (0, "0"):
                    last_msg = f"{base}: {msg or '失败'}"
                    continue
                p = data.get("data") or {}
                member = p.get("member") or p
                name = member.get("username") or member.get("name") or member.get("nickname") or "-"
                # persist working key/base
                cfg["api_key"] = key
                cfg["api_base"] = base
                from app.store import save_config

                save_config(cfg)
                fp = f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "****"
                append_log(f"API Key 校验成功: {name} @ {base}", action="pt_login", username=name, api_base=base, fingerprint=fp)
                return {"ok": True, "username": name, "api_base": base, "fingerprint": fp, "profile": p}
        raise RuntimeError(
            f"{last_msg}。请确认粘贴的是【控制台→实验室→存取令牌】的完整 Access Token（不是登录密码）"
        )

    def fetch_captcha(self) -> dict:
        paths = [
            ("GET", "/api/captcha/image"),
            ("POST", "/api/captcha/gen"),
            ("GET", "/api/captcha"),
        ]
        last_err = None
        self._before_call()
        with self._client() as c:
            for method, path in paths:
                try:
                    if method == "GET":
                        r = c.get(self._api(path), headers=self._headers(False))
                    else:
                        r = c.post(self._api(path), headers=self._headers(), json={})
                    if r.status_code >= 400:
                        continue
                    data = r.json()
                    payload = data.get("data") if isinstance(data.get("data"), dict) else (data.get("data") or data)
                    if isinstance(payload, str):
                        payload = {"image": payload}
                    self._captcha_id = (
                        (payload or {}).get("id")
                        or (payload or {}).get("captchaId")
                        or (payload or {}).get("key")
                        or data.get("id")
                    )
                    image = (
                        (payload or {}).get("image")
                        or (payload or {}).get("img")
                        or (payload or {}).get("base64")
                        or (payload or {}).get("captcha")
                    )
                    if not image:
                        continue
                    if not str(image).startswith("data:"):
                        image = f"data:image/png;base64,{image}"
                    append_log(f"获取验证码成功 via {path}")
                    return {"captcha_id": self._captcha_id, "image": image}
                except Exception as e:
                    last_err = e
        raise RuntimeError(f"获取验证码失败: {last_err}（建议改用 API Key）")

    def login(self, username: str, password: str, captcha: str, captcha_id: str = "") -> dict:
        cid = captcha_id or self._captcha_id
        bodies = [
            {"username": username, "password": password, "code": captcha, "captchaId": cid},
            {"username": username, "password": password, "captcha": captcha, "id": cid},
            {"username": username, "password": password, "otpCode": captcha},
        ]
        last_msg = "登录失败"
        self._before_call()
        with self._client() as c:
            for body in bodies:
                body = {k: v for k, v in body.items() if v is not None and v != ""}
                r = c.post(self._api("/api/login"), headers=self._headers(), json=body)
                try:
                    data = r.json()
                except Exception:
                    continue
                code = data.get("code")
                if code not in (0, "0", 200, "200"):
                    last_msg = data.get("message") or data.get("msg") or str(data)
                    continue
                token = (
                    data.get("data")
                    if isinstance(data.get("data"), str)
                    else (data.get("data") or {}).get("token")
                    or (data.get("data") or {}).get("authorization")
                    or data.get("token")
                )
                if token:
                    self.token = token if str(token).startswith("Bearer") else f"Bearer {token}"
                append_log(f"站点登录成功: {username}")
                return {"ok": True, "token": self.token, "raw": data}
        append_log(f"站点登录失败: {last_msg}")
        raise RuntimeError(f"{last_msg}（站点限制第三方 /login 时请使用 API Key）")

    def update_last_browse(self) -> bool:
        try:
            self._before_call(human=True)
            with self._client() as c:
                r = c.post(self._api("/api/member/updateLastBrowse"), headers=self._headers(), json={})
                if r.status_code >= 400:
                    return False
                data = r.json()
                ok = data.get("code") in (0, "0", None) or data.get("success") is True
                msg = "更新最后浏览时间" + ("成功" if ok else f"失败: {data.get('message') or data}")
                append_pt_log(msg, action="checkin", event="update_last_browse", ok=ok)
                append_access_log(msg, action="checkin", event="update_last_browse", ok=ok)
                return bool(ok)
        except Exception as e:
            append_pt_log(f"更新最后浏览失败: {e}", action="checkin", level="error", error=str(e))
            append_access_log(f"更新最后浏览失败: {e}", action="checkin", level="error", error=str(e))
            return False

    def auto_checkin(self) -> dict:
        """每日保活：随机浏览列表，避免长期未活跃。"""
        cfg = self._cfg()
        if not cfg.get("api_key") and not self.token:
            raise RuntimeError("请先配置 API Key")
        lo = max(1, int(cfg.get("checkin_min_actions") or 2))
        hi = max(lo, int(cfg.get("checkin_max_actions") or 5))
        n = random.randint(lo, hi)
        modes = ["movie", "tvshow", "normal"]
        base_mode = cfg.get("mode") or "movie"
        if base_mode not in modes:
            modes.append(base_mode)
        events = []
        browsed = 0

        if self.update_last_browse():
            events.append("updateLastBrowse")

        for i in range(n):
            mode = random.choice(modes)
            page = random.randint(1, 3)
            try:
                if i > 0:
                    human_sleep("page")
                items = self.search(keyword="", mode=mode, page=page, page_size=min(50, int(cfg.get("page_size") or 50)))
                browsed += 1
                events.append(f"search:{mode}:p{page}:{len(items)}")
            except Exception as e:
                events.append(f"search_err:{e}")
                append_pt_log(f"保活浏览失败: {e}", action="checkin", level="error", error=str(e))
                append_access_log(f"保活浏览失败: {e}", action="checkin", level="error", error=str(e))

        try:
            human_sleep("action")
            self.personal_stats(save=True)
            events.append("profile")
        except Exception as e:
            events.append(f"profile_err:{e}")

        from app.timeutil import now_str

        now = now_str()
        cfg = load_config()
        cfg["checkin_last_at"] = now
        save_config(cfg)
        append_pt_log(
            f"自动签到/保活完成 浏览{browsed}次",
            action="checkin",
            event="done",
            browsed=browsed,
            actions=events,
            at=now,
        )
        append_access_log(
            f"自动签到完成 浏览{browsed}次",
            action="checkin",
            browsed=browsed,
            actions=events,
        )
        return {"ok": True, "browsed": browsed, "events": events, "at": now}

    def profile(self) -> dict:
        self._before_call(human=False)
        with self._client() as c:
            r = c.post(self._api("/api/member/profile"), headers=self._headers(), json={})
            r.raise_for_status()
            data = r.json()
            if data.get("code") not in (0, "0"):
                raise RuntimeError(data.get("message") or str(data))
            p = data.get("data") or {}
            if isinstance(p.get("member"), dict) and not p.get("memberCount"):
                m = dict(p.get("member") or {})
                for k in ("memberCount", "memberStatus", "seedtime", "leechtime"):
                    if k in p and k not in m:
                        m[k] = p[k]
                return m
            return p

    def peer_status(self) -> dict:
        self._before_call(human=False)
        with self._client() as c:
            r = c.post(self._api("/api/tracker/myPeerStatus"), headers=self._headers(), json={})
            r.raise_for_status()
            data = r.json()
            if data.get("code") not in (0, "0"):
                raise RuntimeError(data.get("message") or str(data))
            return data.get("data") or {}

    def personal_stats(self, save: bool = True) -> dict:
        p = self.profile()
        try:
            peer = self.peer_status()
        except Exception:
            peer = {}
        mc = p.get("memberCount") or {}
        ms = p.get("memberStatus") or {}
        uploaded = int(mc.get("uploaded") or 0)
        downloaded = int(mc.get("downloaded") or 0)
        stats = {
            "username": p.get("username") or "",
            "uid": str(p.get("id") or ""),
            "bonus": float(mc.get("bonus") or 0),
            "invites": int(p.get("invites") or 0),
            "invite_limit": int(p.get("limitInvites") or 0),
            "share_rate": float(mc.get("shareRate") or 0),
            "uploaded": uploaded,
            "downloaded": downloaded,
            "uploaded_text": fmt_size(uploaded),
            "downloaded_text": fmt_size(downloaded),
            "seeding": int(peer.get("seeder") or 0),
            "leeching": int(peer.get("leecher") or 0),
            "seedtime": int(p.get("seedtime") or 0),
            "leechtime": int(p.get("leechtime") or 0),
            "last_login": (ms.get("lastLogin") or ""),
            "last_browse": (ms.get("lastBrowse") or ""),
            "vip": bool(ms.get("vip")),
            "donor": bool(ms.get("donor")),
            "email": p.get("email") or "",
        }
        if save:
            save_profile_snapshot(stats)
            append_access_log(
                f"个人数据同步 uid={stats['uid']} ratio={stats['share_rate']} "
                f"up={stats['uploaded_text']} down={stats['downloaded_text']} "
                f"seed={stats['seeding']} leech={stats['leeching']} bonus={stats['bonus']}",
                action="profile_sync",
                uid=stats["uid"],
                username=stats.get("username"),
                share_rate=stats["share_rate"],
                uploaded=stats["uploaded_text"],
                downloaded=stats["downloaded_text"],
                seeding=stats["seeding"],
                leeching=stats["leeching"],
                bonus=stats["bonus"],
            )
        return stats

    def search(self, keyword: str = "", mode: str = "movie", page: int = 1, page_size: int = 50, extra: dict = None) -> list:
        body = {
            "keyword": keyword,
            "mode": mode,
            "categories": [],
            "pageNumber": page,
            "pageSize": page_size,
            "visible": 1,
        }
        if extra:
            body.update(extra)
        self._before_call("page" if page > 1 else "action")
        with self._client() as c:
            r = c.post(self._api("/api/torrent/search"), headers=self._headers(), json=body)
            r.raise_for_status()
            data = r.json()
            if data.get("code") not in (0, "0"):
                raise RuntimeError(data.get("message") or str(data))
            items = (data.get("data") or {}).get("data") or []
            sample = []
            for it in items[:5]:
                m = self._torrent_meta(it)
                sample.append({
                    "id": m["id"],
                    "name": m["name"],
                    "cn_name": m.get("cn_name") or "",
                    "size": m.get("size_text"),
                    "seeders": m.get("seeders"),
                    "douban_rating": m.get("douban_rating") or "",
                })
            append_pt_log(
                f"搜索种子 mode={mode} keyword={keyword!r} page={page} 结果={len(items)}",
                action="search",
                mode=mode,
                keyword=keyword,
                page=page,
                page_size=page_size,
                result_count=len(items),
                sample=sample,
            )
            return items

    def gen_dl_token(self, torrent_id: str, human: bool = True) -> str:
        self._before_call(human=human)
        with self._client() as c:
            r = c.post(
                self._api("/api/torrent/genDlToken"),
                headers=self._headers(False),
                data={"id": str(torrent_id)},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") not in (0, "0"):
                raise RuntimeError(data.get("message") or str(data))
            url = data.get("data")
            if not url:
                raise RuntimeError("未获取到下载链接")
            append_pt_log(
                f"获取下载令牌成功 id={torrent_id}",
                action="gen_dl_token",
                torrent_id=str(torrent_id),
            )
            return url

    def download_torrent(self, torrent_id: str, name: str = "", meta: dict = None, source: str = "manual", human: bool = True, push_tr: bool = True) -> str:
        url = self.gen_dl_token(torrent_id, human=human)
        safe = re.sub(r'[\\/:*?"<>|]+', "_", name or torrent_id)[:120]
        path = DOWNLOAD_DIR / f"{torrent_id}_{safe}.torrent"
        with self._client() as c:
            r = c.get(url, headers=self._headers(False))
            r.raise_for_status()
            if not r.content or len(r.content) < 50:
                raise RuntimeError("种子内容为空")
            path.write_bytes(r.content)
        done = load_downloaded()
        done.add(str(torrent_id))
        save_downloaded(done)
        append_download_log(
            f"种子文件已保存 id={torrent_id} name={name or '-'} size={len(r.content)}B",
            action="torrent_save",
            torrent_id=str(torrent_id),
            name=name or (meta or {}).get("name") or "",
            cn_name=(meta or {}).get("cn_name") or "",
            file=path.name,
            bytes=len(r.content),
            size_text=(meta or {}).get("size_text") or "",
            source=source,
            discount=(meta or {}).get("discount") or "",
            seeders=(meta or {}).get("seeders"),
            douban_rating=(meta or {}).get("douban_rating") or "",
        )
        row = {
            "id": str(torrent_id),
            "name": name or (meta or {}).get("name") or torrent_id,
            "cn_name": (meta or {}).get("cn_name") or "",
            "small_descr": (meta or {}).get("small_descr") or "",
            "cover": (meta or {}).get("cover") or "",
            "douban": (meta or {}).get("douban") or "",
            "douban_rating": (meta or {}).get("douban_rating") or "",
            "imdb": (meta or {}).get("imdb") or "",
            "imdb_rating": (meta or {}).get("imdb_rating") or "",
            "labels": (meta or {}).get("labels") or [],
            "size": (meta or {}).get("size"),
            "size_text": (meta or {}).get("size_text") or "-",
            "seeders": (meta or {}).get("seeders"),
            "leechers": (meta or {}).get("leechers"),
            "downloads": (meta or {}).get("downloads"),
            "discount": (meta or {}).get("discount") or "",
            "keyword": (meta or {}).get("keyword") or "",
            "source": source,
            "status": "downloaded",
            "file": path.name,
        }
        tr_info = self._maybe_push_transmission(path.read_bytes(), source) if push_tr else {}
        if tr_info.get("error"):
            row["tr_status"] = "error"
            row["tr_error"] = tr_info["error"]
        elif tr_info.get("ok"):
            row["tr_id"] = tr_info.get("id")
            row["tr_status"] = "duplicate" if tr_info.get("duplicate") else "added"
            row["tr_server"] = tr_info.get("server_name") or ""
        upsert_task(row)
        return str(path)

    def _maybe_push_transmission(self, torrent_bytes: bytes, source: str, server_id: str = None) -> dict:
        from app.transmission import TransmissionClient, get_server

        cfg = self._cfg()
        if source == "hobby" and not cfg.get("tr_auto_hobby", True):
            return {}
        if source == "ratio" and not cfg.get("tr_auto_ratio", True):
            append_download_log("分享监控已下载但未开启 TR 推送", action="tr_push", level="info", source=source)
            return {}
        if source == "manual" and not cfg.get("tr_auto_manual", True):
            return {}
        if source == "ratio":
            sid = server_id or cfg.get("tr_ratio_server_id") or cfg.get("tr_auto_server_id") or cfg.get("tr_default_id") or ""
        else:
            sid = server_id or cfg.get("tr_auto_server_id") or cfg.get("tr_default_id") or ""
        try:
            server = get_server(sid, cfg)
            if not server.get("enabled"):
                append_download_log(
                    f"Transmission 服务未启用，跳过推送: {server.get('name') or sid}",
                    action="tr_push",
                    level="warn",
                    server_id=sid or "",
                    source=source,
                )
                return {}
            if not (server.get("url") or "").strip():
                append_download_log(
                    "Transmission URL 为空，跳过推送",
                    action="tr_push",
                    level="warn",
                    server_id=sid or "",
                    source=source,
                )
                return {}
            return TransmissionClient(server).add_torrent(torrent_bytes)
        except Exception as e:
            append_download_log(
                f"Transmission 推送失败: {e}",
                action="tr_push",
                level="error",
                error=str(e),
                server_id=sid or "",
                source=source,
            )
            return {"error": str(e)}

    def push_to_transmission(self, torrent_bytes: bytes, server_id: str = None) -> dict:
        from app.transmission import TransmissionClient, get_server

        server = get_server(server_id)
        if not server.get("enabled"):
            raise RuntimeError(f"Transmission「{server.get('name') or server.get('id')}」未启用")
        if not (server.get("url") or "").strip():
            raise RuntimeError("请先配置 Transmission RPC 地址")
        return TransmissionClient(server).add_torrent(torrent_bytes)

    def download_to_tr(self, torrent_id: str, name: str = "", meta: dict = None, server_id: str = None) -> dict:
        from pathlib import Path

        from app.store import load_tasks, upsert_task
        from app.transmission import resolve_torrent_file

        tid = str(torrent_id)
        path = resolve_torrent_file(tid)
        reused = bool(path)
        if not path:
            path = Path(
                self.download_torrent(
                    tid, name, meta=meta, source="manual", human=True, push_tr=False
                )
            )
        data = path.read_bytes()
        if len(data) < 50:
            raise RuntimeError("种子文件无效")
        tr = self.push_to_transmission(data, server_id=server_id)
        row = {"id": tid, "file": path.name, "status": "downloaded"}
        if name:
            row["name"] = name
        if meta:
            for k in (
                "cn_name", "small_descr", "cover", "douban", "douban_rating",
                "imdb", "imdb_rating", "labels", "size", "size_text",
                "seeders", "leechers", "downloads", "discount", "keyword", "source",
            ):
                if meta.get(k) not in (None, ""):
                    row[k] = meta.get(k)
        if not row.get("source"):
            for t in load_tasks():
                if str(t.get("id")) == tid and t.get("source"):
                    row["source"] = t.get("source")
                    break
            else:
                row["source"] = "manual"
        row["tr_id"] = tr.get("id")
        row["tr_status"] = "duplicate" if tr.get("duplicate") else "added"
        row["tr_server"] = tr.get("server_name") or ""
        row["tr_server_id"] = tr.get("server_id") or server_id or ""
        row.pop("tr_error", None)
        upsert_task(row)
        return {"ok": True, "file": path.name, "reused": reused, "tr": tr}

    def _match_kw(self, title: str, keywords: list, exclude: list, match: str, extra: str = "") -> bool:
        t = f"{title} {extra}".lower()
        if exclude and any(x.lower() in t for x in exclude if x.strip()):
            return False
        kws = [k for k in keywords if k and str(k).strip()]
        if not kws:
            return False
        hits = [k.lower() in t for k in kws]
        return all(hits) if match == "all" else any(hits)

    def _task_text(self, m: dict) -> str:
        return f"{m.get('name') or ''} {m.get('cn_name') or ''} {m.get('small_descr') or ''}"

    def _hit_keyword(self, m: dict, keywords: list, prefer: str = "") -> str:
        text = self._task_text(m).lower()
        if prefer and prefer.lower() in text:
            return prefer
        for k in keywords:
            if k and k.lower() in text:
                return k
        return prefer or (keywords[0] if keywords else "")

    def _clarity_score(self, m: dict) -> int:
        text = self._task_text(m).lower()
        score = 0
        if re.search(r"2160p|3840\s*x|uhd|4k\b", text):
            score += 100
        elif re.search(r"1080p|1920\s*x|fhd", text):
            score += 70
        elif re.search(r"720p", text):
            score += 40
        elif re.search(r"480p|576p", text):
            score += 15
        if re.search(r"\bremux\b", text):
            score += 18
        elif re.search(r"blu-?ray|bdremux|bdrip|bdr\b", text):
            score += 12
        elif re.search(r"web-?dl|webrip", text):
            score += 6
        elif re.search(r"hdtv|hdrip", text):
            score += 3
        if re.search(r"\b(cam|ts|telesync|hdcam|tc)\b", text):
            score -= 40
        return score

    def _version_rank(self, m: dict) -> tuple:
        clarity = self._clarity_score(m)
        size_gb = float(m.get("size_gb") or 0)
        return (clarity, size_gb, int(m.get("seeders") or 0))

    def _pick_top_versions(self, items: list, limit: int = 3) -> list:
        if not items:
            return []
        ranked = sorted(items, key=self._version_rank, reverse=True)
        picked, seen = [], set()
        for m in ranked:
            tid = str(m.get("id") or "")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            picked.append(m)
            if len(picked) >= limit:
                break
        return picked

    def prune_hobby_tasks(self) -> dict:
        from app.store import save_tasks

        cfg = self._cfg()
        keywords = [k.strip() for k in cfg.get("keywords") or [] if k.strip()]
        exclude = [k.strip() for k in cfg.get("exclude_keywords") or [] if k.strip()]
        match = cfg.get("keyword_match") or "any"
        items = load_tasks()
        keep = []
        removed = 0
        for t in items:
            if (t.get("source") or "hobby") != "hobby":
                keep.append(t)
                continue
            if not keywords or not self._match_kw(
                t.get("name") or "", keywords, exclude, match, extra=self._task_text(t)
            ):
                removed += 1
                continue
            row = dict(t)
            if not row.get("keyword"):
                row["keyword"] = self._hit_keyword(row, keywords)
            keep.append(row)
        save_tasks(keep)
        hobby_left = len([x for x in keep if (x.get("source") or "hobby") == "hobby"])
        append_access_log(
            f"爱好任务对齐 keywords={keywords} 保留={hobby_left} 移除={removed}",
            action="hobby_prune",
            keywords=keywords,
            kept=hobby_left,
            removed=removed,
        )
        return {"kept": hobby_left, "removed": removed, "keywords": keywords}

    def _torrent_meta(self, t: dict) -> dict:
        st = t.get("status") or {}
        size = t.get("size")
        try:
            size_gb = float(size) / (1024**3)
        except Exception:
            size_gb = 0
        downloads = int(st.get("timesCompleted") or st.get("downloads") or t.get("timesCompleted") or 0)
        seeders = int(st.get("seeders") or 0)
        leechers = int(st.get("leechers") or 0)
        discount = st.get("discount") or ""
        small = (t.get("smallDescr") or t.get("small_descr") or "").strip()
        images = t.get("imageList") or t.get("images") or []
        cover = ""
        if isinstance(images, list) and images:
            cover = str(images[0] or "")
        elif isinstance(t.get("cover"), str):
            cover = t.get("cover") or ""
        labels = t.get("labelsNew") or t.get("labels") or []
        if isinstance(labels, str):
            labels = [x for x in labels.split(",") if x.strip()] if labels not in ("0", "") else []
        douban_rating = t.get("doubanRating") or t.get("douban_rating") or ""
        imdb_rating = t.get("imdbRating") or t.get("imdb_rating") or ""
        if douban_rating is None:
            douban_rating = ""
        if imdb_rating is None:
            imdb_rating = ""
        return {
            "id": str(t.get("id") or ""),
            "name": t.get("name") or t.get("title") or "",
            "cn_name": self._cn_title(small),
            "small_descr": small,
            "cover": cover,
            "douban": t.get("douban") or "",
            "douban_rating": str(douban_rating).strip(),
            "imdb": t.get("imdb") or "",
            "imdb_rating": str(imdb_rating).strip(),
            "labels": labels if isinstance(labels, list) else [],
            "size": size,
            "size_text": fmt_size(size),
            "size_gb": round(size_gb, 2),
            "downloads": downloads,
            "seeders": seeders,
            "leechers": leechers,
            "discount": discount,
            "free": discount in ("FREE", "PERCENT_50", "PERCENT_30", "PERCENT_70", "free", "50%", "30%", "70%"),
            "created_date": t.get("createdDate") or "",
        }

    @staticmethod
    def _cn_title(small: str) -> str:
        s = (small or "").strip()
        if not s:
            return ""
        s = re.sub(r"^【[^】]*】\s*", "", s)
        s = re.sub(r"^\[.*?\]\s*", "", s)
        if "|" in s:
            s = s.split("|", 1)[0].strip()
        return s[:100]

    def torrent_detail(self, torrent_id: str) -> dict:
        self._before_call(human=False)
        with self._client() as c:
            r = c.post(
                self._api("/api/torrent/detail"),
                headers=self._headers(False),
                data={"id": str(torrent_id)},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") not in (0, "0"):
                raise RuntimeError(data.get("message") or str(data))
            return data.get("data") or {}

    def enrich_tasks(self, limit: int = 40) -> dict:
        items = load_tasks()
        updated = 0
        errors = []
        for t in items:
            if updated >= limit:
                break
            if t.get("cover") and t.get("cn_name") and t.get("douban_rating"):
                continue
            tid = str(t.get("id") or "")
            if not tid:
                continue
            try:
                detail = self.torrent_detail(tid)
                meta = self._torrent_meta(detail)
                upsert_task({
                    "id": tid,
                    "name": meta.get("name") or t.get("name"),
                    "cn_name": meta.get("cn_name") or t.get("cn_name") or "",
                    "small_descr": meta.get("small_descr") or t.get("small_descr") or "",
                    "cover": meta.get("cover") or t.get("cover") or "",
                    "douban": meta.get("douban") or t.get("douban") or "",
                    "douban_rating": meta.get("douban_rating") or t.get("douban_rating") or "",
                    "imdb": meta.get("imdb") or t.get("imdb") or "",
                    "imdb_rating": meta.get("imdb_rating") or t.get("imdb_rating") or "",
                    "labels": meta.get("labels") or t.get("labels") or [],
                    "size": meta.get("size") or t.get("size"),
                    "size_text": meta.get("size_text") or t.get("size_text") or "-",
                    "size_gb": meta.get("size_gb") or t.get("size_gb"),
                    "downloads": meta.get("downloads") if meta.get("downloads") is not None else t.get("downloads"),
                    "seeders": meta.get("seeders") if meta.get("seeders") is not None else t.get("seeders"),
                    "leechers": meta.get("leechers") if meta.get("leechers") is not None else t.get("leechers"),
                    "discount": meta.get("discount") or t.get("discount") or "",
                    "source": t.get("source") or "hobby",
                    "status": t.get("status") or "matched",
                    "keyword": t.get("keyword") or "",
                })
                updated += 1
            except Exception as e:
                errors.append(f"{tid}:{e}")
        append_pt_log(
            f"任务详情补全 updated={updated} errors={len(errors)}",
            action="enrich",
            updated=updated,
            error_count=len(errors),
            errors=errors[:10],
        )
        return {"updated": updated, "errors": errors[:10]}

    def ratio_tips(self) -> list:
        cfg = self._cfg()
        if not cfg.get("api_key") and not self.token:
            raise RuntimeError("请配置 API Key 或先登录站点")
        mode = cfg.get("mode") or "movie"
        page_size = int(cfg.get("page_size") or 50)
        pages = max(1, min(5, int(cfg.get("ratio_pages") or 3)))
        max_gb = float(cfg.get("ratio_max_size_gb") or 0)
        min_gb = float(cfg.get("ratio_min_size_gb") or 0)
        min_seed = int(cfg.get("ratio_min_seeders") or 0)
        max_seed = int(cfg.get("ratio_max_seeders") or 0)
        min_leech = int(cfg.get("ratio_min_leechers") or 0)
        prefer_free = bool(cfg.get("ratio_prefer_free", True))
        top_n = int(cfg.get("ratio_top_n") or 8)

        sorts = [
            {"sortField": "size", "sortDirection": "DESC"},
            {"sortField": "seeders", "sortDirection": "ASC"},
            {},
        ]
        pool = {}
        first = True
        for extra in sorts:
            for page in range(1, pages + 1):
                if not first:
                    human_sleep("page")
                first = False
                items = self.search(
                    keyword="",
                    mode=mode,
                    page=page,
                    page_size=page_size,
                    extra=extra or None,
                )
                for t in items:
                    m = self._torrent_meta(t)
                    if m["id"]:
                        pool[m["id"]] = m

        scored = []
        for m in pool.values():
            size_gb = float(m.get("size_gb") or 0)
            seeders = int(m.get("seeders") or 0)
            leechers = int(m.get("leechers") or 0)
            if max_gb > 0 and size_gb > max_gb:
                continue
            if min_gb > 0 and size_gb < min_gb:
                continue
            if size_gb < 0.01:
                continue
            if seeders < min_seed:
                continue
            if max_seed > 0 and seeders > max_seed:
                continue
            if leechers < min_leech:
                continue

            weeks = _weeks_alive(m.get("created_date") or "")
            a = _magic_a(size_gb, seeders, weeks)
            b_est = _magic_b(a)
            demand = leechers / (seeders + 1)
            tips = []
            score = a

            if weeks >= 8:
                tips.append(f"存活久({weeks:.1f}周)")
            elif weeks >= 2:
                tips.append(f"已存活{weeks:.1f}周")
            else:
                tips.append(f"较新({weeks:.1f}周)")
                score *= 0.55

            if seeders <= 2:
                tips.append(f"做种极少({seeders})")
            elif seeders <= 6:
                tips.append(f"做种少({seeders})")
            else:
                tips.append(f"做种{seeders}")

            if size_gb >= 40:
                tips.append(f"体积大({size_gb:.0f}GB)")
            elif size_gb >= 15:
                tips.append(f"体积适中({size_gb:.0f}GB)")
            else:
                tips.append(f"{size_gb:.1f}GB")

            score += 0.1
            if m.get("free") or discount_ok(m.get("discount") or ""):
                tips.append(f"优惠:{m.get('discount') or 'FREE'}")
                disc = str(m.get("discount") or "").upper()
                if "FREE" in disc or m.get("free"):
                    score += a * 0.08
                else:
                    score += a * 0.04
            elif prefer_free:
                score *= 0.85

            if leechers >= 5:
                tips.append(f"有下载({leechers})")
                score += min(a * 0.05, 5)

            if not tips:
                tips.append("魔力候选")

            m["score"] = round(score, 1)
            m["magic_a"] = round(a, 2)
            m["magic_b"] = round(b_est, 2)
            m["weeks"] = round(weeks, 2)
            m["demand"] = round(demand, 2)
            m["tips"] = " · ".join(tips)
            m["reason"] = "按魔力公式：大体积×少做种×存活久，优先刷魔力值"
            scored.append(m)

        scored.sort(key=lambda x: (-x["score"], -x.get("magic_a", 0), -x.get("weeks", 0), x["seeders"]))
        result = scored[:top_n]
        save_ratio_tips(result)
        append_pt_log(
            f"分享监控(魔力) 候选池={len(pool)} 推荐={len(result)}",
            action="ratio_tips",
            pool=len(pool),
            count=len(result),
            pages=pages,
            max_gb=max_gb,
            min_gb=min_gb,
            min_seeders=min_seed,
            max_seeders=max_seed,
            min_leechers=min_leech,
            items=[
                {
                    "id": x["id"],
                    "name": x.get("cn_name") or x["name"],
                    "score": x.get("score"),
                    "magic_a": x.get("magic_a"),
                    "weeks": x.get("weeks"),
                    "seeders": x.get("seeders"),
                    "tips": x.get("tips"),
                }
                for x in result
            ],
        )
        if cfg.get("ratio_auto_download"):
            done = load_downloaded()
            for m in result:
                if m["id"] in done:
                    continue
                try:
                    self.download_torrent(m["id"], m["name"], meta=m, source="ratio")
                except Exception as e:
                    append_download_log(
                        f"分享监控自动下载失败 id={m['id']}: {e}",
                        action="ratio_auto_dl",
                        level="error",
                        torrent_id=m["id"],
                        name=m.get("name"),
                        error=str(e),
                    )
        return result

    def match_and_download(self) -> dict:
        cfg = self._cfg()
        if _in_quiet_hours(cfg):
            append_access_log("处于静默时段，跳过本轮", action="scan_skip", reason="quiet")
            return {"matched": [], "downloaded": [], "skipped": "quiet"}
        if not cfg.get("api_key") and not self.token:
            raise RuntimeError("请配置 API Key 或先登录站点")
        keywords = [k.strip() for k in cfg.get("keywords") or [] if k.strip()]
        exclude = [k.strip() for k in cfg.get("exclude_keywords") or [] if k.strip()]
        match = cfg.get("keyword_match") or "any"
        if not keywords:
            pruned = self.prune_hobby_tasks()
            append_access_log("未配置爱好关键词，跳过扫描", action="scan_skip", reason="no_keywords")
            return {"matched": [], "downloaded": [], "skipped": "no_keywords", "pruned": pruned}
        done = load_downloaded()
        found, downloaded = [], []
        seen = set()
        by_kw = {k: [] for k in keywords}
        max_ver = max(1, min(10, int(cfg.get("hobby_max_versions") or 3)))

        for i, kw in enumerate(keywords):
            if i > 0:
                human_sleep("page")
            items = self.search(
                keyword=kw,
                mode=cfg.get("mode") or "movie",
                page=1,
                page_size=int(cfg.get("page_size") or 50),
            )
            for t in items:
                m = self._torrent_meta(t)
                if not m["id"] or m["id"] in seen:
                    continue
                extra = f"{m.get('cn_name','')} {m.get('small_descr','')}"
                blob = f"{m['name']} {extra}".lower()
                if exclude and any(x.lower() in blob for x in exclude if x.strip()):
                    continue
                if match == "all":
                    if not self._match_kw(m["name"], keywords, [], "all", extra=extra):
                        continue
                elif kw.lower() not in blob:
                    continue
                hit = self._hit_keyword(m, keywords, prefer=kw)
                m["keyword"] = hit
                m["clarity"] = self._clarity_score(m)
                seen.add(m["id"])
                by_kw.setdefault(hit or kw, []).append(m)

        selected = []
        for kw, pool in by_kw.items():
            if not pool:
                continue
            already = [m for m in pool if m["id"] in done]
            pending = [m for m in pool if m["id"] not in done]
            keep_already = self._pick_top_versions(already, max_ver)
            slots = max(0, max_ver - len(keep_already))
            pick_new = self._pick_top_versions(pending, slots) if slots else []
            for m in keep_already + pick_new:
                selected.append(m)

        for m in selected:
            hit = m.get("keyword") or ""
            found.append(m)
            upsert_task({
                **m,
                "keyword": hit,
                "source": "hobby",
                "status": "matched" if m["id"] in done else "pending",
                "pick_reason": f"清晰度{m.get('clarity', 0)}/体积{m.get('size_gb', 0)}GB",
            })
            if cfg.get("auto_download") and m["id"] not in done:
                try:
                    self.download_torrent(m["id"], m["name"], meta={**m, "keyword": hit}, source="hobby")
                    downloaded.append(m["id"])
                    done.add(m["id"])
                except Exception as e:
                    upsert_task({**m, "keyword": hit, "source": "hobby", "status": "failed", "error": str(e)})
                    append_download_log(
                        f"爱好下载失败 id={m['id']} name={m['name']}: {e}",
                        action="hobby_dl",
                        level="error",
                        torrent_id=m["id"],
                        name=m.get("name"),
                        keyword=hit,
                        error=str(e),
                    )
            elif m["id"] in done:
                upsert_task({**m, "keyword": hit, "source": "hobby", "status": "downloaded"})

        pruned = self.prune_hobby_tasks()
        ratio = []
        if cfg.get("ratio_assist") and not cfg.get("ratio_schedule_enabled"):
            try:
                ratio = self.ratio_tips()
            except Exception as e:
                append_pt_log(f"分享监控失败: {e}", action="ratio_tips", level="error", error=str(e))
        try:
            self.personal_stats(save=True)
        except Exception as e:
            append_access_log(f"个人数据快照失败: {e}", action="profile_sync", level="error", error=str(e))
        append_pt_log(
            f"本轮扫描完成 精选={len(found)} 新下载={len(downloaded)} 每词最多{max_ver}版 分享候选={len(ratio)} 清理={pruned.get('removed')}",
            action="scan",
            matched=len(found),
            downloaded=len(downloaded),
            max_versions=max_ver,
            ratio_count=len(ratio),
            pruned=pruned.get("removed"),
            keywords=keywords,
            matched_ids=[x.get("id") for x in found[:30]],
            downloaded_ids=downloaded[:30],
        )
        return {"matched": found, "downloaded": downloaded, "ratio_tips": ratio, "pruned": pruned}


def discount_ok(d: str) -> bool:
    if not d:
        return False
    u = str(d).upper()
    return any(x in u for x in ("FREE", "PERCENT", "50", "30", "70", "2X"))


client = MTeamClient()
