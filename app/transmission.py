import base64
import uuid
from typing import Optional

import httpx

from app.store import append_download_log, load_config, save_config


class TransmissionError(RuntimeError):
    pass


def _rpc_url(url: str) -> str:
    u = (url or "").rstrip("/")
    if not u.endswith("/transmission/rpc"):
        if u.endswith("/transmission"):
            u = u + "/rpc"
        else:
            u = u + "/transmission/rpc"
    return u


def migrate_tr_servers(cfg: dict) -> dict:
    servers = cfg.get("tr_servers")
    if isinstance(servers, list) and servers:
        return cfg
    url = (cfg.get("tr_url") or "").strip()
    if not url and not cfg.get("tr_enabled"):
        cfg["tr_servers"] = cfg.get("tr_servers") or []
        return cfg
    sid = str(uuid.uuid4())[:8]
    cfg["tr_servers"] = [
        {
            "id": sid,
            "name": "默认",
            "enabled": bool(cfg.get("tr_enabled")),
            "url": url or "http://host.docker.internal:9091",
            "user": cfg.get("tr_user") or "",
            "pass": cfg.get("tr_pass") or "",
            "download_dir": cfg.get("tr_download_dir") or "",
            "paused": bool(cfg.get("tr_paused", False)),
        }
    ]
    cfg["tr_default_id"] = sid
    cfg["tr_auto_server_id"] = sid
    cfg["tr_ratio_server_id"] = sid
    return cfg


def list_servers(cfg: dict = None) -> list:
    cfg = migrate_tr_servers(dict(cfg or load_config()))
    return cfg.get("tr_servers") or []


def get_server(server_id: str = None, cfg: dict = None) -> dict:
    cfg = migrate_tr_servers(dict(cfg or load_config()))
    servers = cfg.get("tr_servers") or []
    sid = (server_id or "").strip()
    if sid:
        for s in servers:
            if str(s.get("id")) == sid:
                return s
        raise TransmissionError(f"Transmission 服务不存在: {sid}")
    for key in ("tr_default_id", "tr_auto_server_id"):
        did = (cfg.get(key) or "").strip()
        if did:
            for s in servers:
                if str(s.get("id")) == did:
                    return s
    enabled = [s for s in servers if s.get("enabled") and (s.get("url") or "").strip()]
    if enabled:
        return enabled[0]
    if servers:
        return servers[0]
    raise TransmissionError("未配置 Transmission 服务")


def resolve_torrent_file(torrent_id: str):
    from pathlib import Path

    from app.store import DOWNLOAD_DIR, load_tasks

    tid = str(torrent_id)
    for t in load_tasks():
        if str(t.get("id")) == tid and t.get("file"):
            path = DOWNLOAD_DIR / t["file"]
            if path.exists() and path.stat().st_size > 50:
                return path
    matches = sorted(DOWNLOAD_DIR.glob(f"{tid}_*.torrent"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in matches:
        if path.exists() and path.stat().st_size > 50:
            return path
    return None


def mask_servers(servers: list) -> list:
    out = []
    for s in servers or []:
        row = dict(s)
        if row.get("pass"):
            row["pass_set"] = True
            row["pass"] = ""
        else:
            row["pass_set"] = False
            row["pass"] = ""
        out.append(row)
    return out


class TransmissionClient:
    def __init__(self, server: dict = None):
        self.server = server or {}
        self._session_id: Optional[str] = None

    @classmethod
    def from_id(cls, server_id: str = None) -> "TransmissionClient":
        return cls(get_server(server_id))

    def _auth(self) -> Optional[tuple]:
        user = (self.server.get("user") or "").strip()
        pwd = self.server.get("pass") or ""
        if user:
            return (user, pwd)
        return None

    def _call(self, method: str, arguments: dict = None) -> dict:
        url = _rpc_url(self.server.get("url") or "")
        if not url.startswith("http"):
            raise TransmissionError("Transmission RPC 地址无效")
        payload = {"method": method, "arguments": arguments or {}}
        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["X-Transmission-Session-Id"] = self._session_id
        auth = self._auth()
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as c:
                r = c.post(url, json=payload, headers=headers, auth=auth)
                if r.status_code == 409:
                    self._session_id = r.headers.get("X-Transmission-Session-Id") or r.headers.get(
                        "x-transmission-session-id"
                    )
                    if not self._session_id:
                        raise TransmissionError("Transmission 未返回 Session-Id")
                    headers["X-Transmission-Session-Id"] = self._session_id
                    r = c.post(url, json=payload, headers=headers, auth=auth)
                if r.status_code == 401:
                    raise TransmissionError("Transmission 认证失败，请检查用户名密码")
                if r.status_code >= 400:
                    raise TransmissionError(f"Transmission HTTP {r.status_code}")
                data = r.json()
                if data.get("result") != "success":
                    raise TransmissionError(data.get("result") or "Transmission 调用失败")
                return data.get("arguments") or {}
        except TransmissionError:
            raise
        except httpx.TimeoutException:
            raise TransmissionError(f"连接 Transmission 超时：{url}")
        except httpx.ConnectError as e:
            raise TransmissionError(f"无法连接 Transmission：{url}（{e}）")
        except Exception as e:
            raise TransmissionError(str(e))

    def test(self) -> dict:
        args = self._call("session-get", {"fields": ["version", "download-dir", "rpc-version"]})
        return {
            "ok": True,
            "id": self.server.get("id"),
            "name": self.server.get("name") or "",
            "version": args.get("version"),
            "rpc_version": args.get("rpc-version"),
            "download_dir": args.get("download-dir"),
        }

    def add_torrent(self, torrent_bytes: bytes, paused: bool = None, download_dir: str = None) -> dict:
        if paused is None:
            paused = bool(self.server.get("paused", False))
        directory = (
            download_dir if download_dir is not None else self.server.get("download_dir") or ""
        ).strip()
        arguments = {
            "metainfo": base64.b64encode(torrent_bytes).decode("ascii"),
            "paused": paused,
        }
        if directory:
            arguments["download-dir"] = directory
        args = self._call("torrent-add", arguments)
        added = args.get("torrent-added") or args.get("torrent-duplicate") or {}
        dup = "torrent-duplicate" in args
        name = added.get("name") or "-"
        tid = added.get("id")
        label = self.server.get("name") or self.server.get("id") or "TR"
        append_download_log(
            f"Transmission[{label}] {'重复跳过' if dup else '已添加'} id={tid} name={name}",
            action="tr_push",
            server_id=self.server.get("id"),
            server_name=label,
            server_url=self.server.get("url") or "",
            torrent_id=tid,
            torrent_name=name,
            duplicate=dup,
            paused=paused,
            download_dir=directory or "",
        )
        return {
            "ok": True,
            "duplicate": dup,
            "id": tid,
            "name": name,
            "server_id": self.server.get("id"),
            "server_name": label,
        }

    @staticmethod
    def _status_label(code: int) -> str:
        return {
            0: "已暂停",
            1: "等待校验",
            2: "校验中",
            3: "等待下载",
            4: "下载中",
            5: "等待做种",
            6: "做种中",
        }.get(int(code or 0), f"状态{code}")

    @staticmethod
    def _fmt_bytes(n) -> str:
        try:
            v = float(n or 0)
        except Exception:
            return "-"
        for u in ("B", "KB", "MB", "GB", "TB"):
            if abs(v) < 1024:
                return f"{v:.1f}{u}"
            v /= 1024
        return f"{v:.1f}PB"

    @staticmethod
    def _fmt_speed(n) -> str:
        try:
            v = float(n or 0)
        except Exception:
            return "0B/s"
        if v < 1024:
            return f"{v:.0f}B/s"
        if v < 1024 ** 2:
            return f"{v/1024:.1f}KB/s"
        return f"{v/1024**2:.2f}MB/s"

    def start_torrents(self, ids: list) -> dict:
        ids = [int(x) for x in ids if x is not None]
        if not ids:
            raise TransmissionError("未指定任务")
        self._call("torrent-start", {"ids": ids})
        return {"ok": True, "action": "start", "ids": ids, "server_id": self.server.get("id")}

    def stop_torrents(self, ids: list) -> dict:
        ids = [int(x) for x in ids if x is not None]
        if not ids:
            raise TransmissionError("未指定任务")
        self._call("torrent-stop", {"ids": ids})
        return {"ok": True, "action": "stop", "ids": ids, "server_id": self.server.get("id")}

    def remove_torrents(self, ids: list, delete_data: bool = False) -> dict:
        ids = [int(x) for x in ids if x is not None]
        if not ids:
            raise TransmissionError("未指定任务")
        self._call("torrent-remove", {"ids": ids, "delete-local-data": bool(delete_data)})
        label = self.server.get("name") or self.server.get("id") or "TR"
        append_download_log(
            f"Transmission[{label}] 删除任务 ids={ids} delete_data={bool(delete_data)}",
            action="tr_remove",
            server_id=self.server.get("id"),
            server_name=label,
            ids=ids,
            delete_data=bool(delete_data),
        )
        return {
            "ok": True,
            "action": "remove_data" if delete_data else "remove",
            "ids": ids,
            "delete_data": bool(delete_data),
            "server_id": self.server.get("id"),
            "server_name": label,
        }

    def list_torrents(self) -> dict:
        fields = [
            "id", "name", "status", "percentDone", "rateDownload", "rateUpload",
            "uploadedEver", "downloadedEver", "totalSize", "leftUntilDone", "eta",
            "error", "errorString", "peersConnected", "uploadRatio", "addedDate",
            "doneDate", "activityDate", "secondsSeeding", "isFinished", "isStalled",
            "downloadDir",
        ]
        args = self._call("torrent-get", {"fields": fields})
        items = []
        stats = {
            "total": 0, "downloading": 0, "seeding": 0, "paused": 0, "checking": 0,
            "error": 0, "done": 0, "size_bytes": 0, "downloaded_bytes": 0,
            "uploaded_bytes": 0, "rate_down": 0, "rate_up": 0,
        }
        for t in args.get("torrents") or []:
            status = int(t.get("status") or 0)
            err = int(t.get("error") or 0)
            pct = float(t.get("percentDone") or 0)
            size = int(t.get("totalSize") or 0)
            down = int(t.get("downloadedEver") or 0)
            up = int(t.get("uploadedEver") or 0)
            rd = int(t.get("rateDownload") or 0)
            ru = int(t.get("rateUpload") or 0)
            row = {
                "id": t.get("id"),
                "name": t.get("name") or "-",
                "status": status,
                "status_text": self._status_label(status),
                "percent": round(pct * 100, 1),
                "size": size,
                "size_text": self._fmt_bytes(size),
                "downloaded": down,
                "uploaded": up,
                "downloaded_text": self._fmt_bytes(down),
                "uploaded_text": self._fmt_bytes(up),
                "rate_down": rd,
                "rate_up": ru,
                "rate_down_text": self._fmt_speed(rd),
                "rate_up_text": self._fmt_speed(ru),
                "ratio": round(float(t.get("uploadRatio") or 0), 2),
                "peers": int(t.get("peersConnected") or 0),
                "eta": int(t.get("eta") or -1),
                "error": err,
                "error_string": t.get("errorString") or "",
                "stalled": bool(t.get("isStalled")),
                "finished": bool(t.get("isFinished")) or pct >= 1,
                "download_dir": t.get("downloadDir") or "",
                "added": int(t.get("addedDate") or 0),
                "done": int(t.get("doneDate") or 0),
                "activity": int(t.get("activityDate") or 0),
                "seed_seconds": int(t.get("secondsSeeding") or 0),
                "server_id": self.server.get("id"),
                "server_name": self.server.get("name") or "",
            }
            items.append(row)
            stats["total"] += 1
            stats["size_bytes"] += size
            stats["downloaded_bytes"] += down
            stats["uploaded_bytes"] += up
            stats["rate_down"] += rd
            stats["rate_up"] += ru
            if err:
                stats["error"] += 1
            elif status == 4:
                stats["downloading"] += 1
            elif status == 6:
                stats["seeding"] += 1
            elif status == 0:
                stats["paused"] += 1
            elif status in (1, 2):
                stats["checking"] += 1
            if row["finished"]:
                stats["done"] += 1
        items.sort(key=lambda x: (-x["rate_down"], -x["rate_up"], -x["percent"], x["name"]))
        stats["size_text"] = self._fmt_bytes(stats["size_bytes"])
        stats["downloaded_text"] = self._fmt_bytes(stats["downloaded_bytes"])
        stats["uploaded_text"] = self._fmt_bytes(stats["uploaded_bytes"])
        stats["rate_down_text"] = self._fmt_speed(stats["rate_down"])
        stats["rate_up_text"] = self._fmt_speed(stats["rate_up"])
        ratio = 0.0
        if stats["downloaded_bytes"] > 0:
            ratio = stats["uploaded_bytes"] / stats["downloaded_bytes"]
        stats["ratio"] = round(ratio, 2)
        return {
            "ok": True,
            "server_id": self.server.get("id"),
            "server_name": self.server.get("name") or "",
            "items": items,
            "stats": stats,
        }

    def session_stats(self) -> dict:
        args = self._call("session-stats")
        cur = args.get("current-stats") or {}
        cum = args.get("cumulative-stats") or {}
        return {
            "ok": True,
            "server_id": self.server.get("id"),
            "server_name": self.server.get("name") or "",
            "active_torrent_count": args.get("activeTorrentCount") or 0,
            "paused_torrent_count": args.get("pausedTorrentCount") or 0,
            "torrent_count": args.get("torrentCount") or 0,
            "download_speed": args.get("downloadSpeed") or 0,
            "upload_speed": args.get("uploadSpeed") or 0,
            "download_speed_text": self._fmt_speed(args.get("downloadSpeed") or 0),
            "upload_speed_text": self._fmt_speed(args.get("uploadSpeed") or 0),
            "current": {
                "downloaded": cur.get("downloadedBytes") or 0,
                "uploaded": cur.get("uploadedBytes") or 0,
                "downloaded_text": self._fmt_bytes(cur.get("downloadedBytes") or 0),
                "uploaded_text": self._fmt_bytes(cur.get("uploadedBytes") or 0),
                "files_added": cur.get("filesAdded") or 0,
                "seconds_active": cur.get("secondsActive") or 0,
            },
            "cumulative": {
                "downloaded": cum.get("downloadedBytes") or 0,
                "uploaded": cum.get("uploadedBytes") or 0,
                "downloaded_text": self._fmt_bytes(cum.get("downloadedBytes") or 0),
                "uploaded_text": self._fmt_bytes(cum.get("uploadedBytes") or 0),
                "files_added": cum.get("filesAdded") or 0,
                "seconds_active": cum.get("secondsActive") or 0,
                "session_count": cum.get("sessionCount") or 0,
            },
        }

    def free_space(self, path: str = None) -> dict:
        directory = (path if path is not None else self.server.get("download_dir") or "").strip()
        if not directory:
            sess = self._call("session-get", {"fields": ["download-dir"]})
            directory = (sess.get("download-dir") or "").strip()
        if not directory:
            raise TransmissionError("无下载目录，无法查询剩余空间")
        try:
            args = self._call("free-space", {"path": directory})
            free_b = int(args.get("size-bytes") or args.get("size_bytes") or 0)
            total_b = int(args.get("total-size") or args.get("total_size") or 0)
            path_out = (args.get("path") or directory) or ""
        except TransmissionError:
            # 旧版兼容
            sess = self._call("session-get", {"fields": ["download-dir", "download-dir-free-space"]})
            free_b = int(sess.get("download-dir-free-space") or 0)
            total_b = 0
            path_out = (sess.get("download-dir") or directory) or ""
        return {
            "ok": True,
            "path": path_out,
            "free_bytes": free_b,
            "free_text": self._fmt_bytes(free_b),
            "total_bytes": total_b,
            "total_text": self._fmt_bytes(total_b) if total_b else "",
        }


def collect_tr_overview(server_id: str = None) -> dict:
    cfg = load_config()
    servers = [s for s in (cfg.get("tr_servers") or []) if s.get("enabled") and (s.get("url") or "").strip()]
    if server_id:
        servers = [s for s in servers if str(s.get("id")) == str(server_id)]
        if not servers:
            raise TransmissionError("未找到启用的 Transmission 服务")
    if not servers:
        raise TransmissionError("未配置可用的 Transmission 服务")

    all_items = []
    server_rows = []
    agg = {
        "total": 0, "downloading": 0, "seeding": 0, "paused": 0, "checking": 0,
        "error": 0, "done": 0, "size_bytes": 0, "downloaded_bytes": 0,
        "uploaded_bytes": 0, "rate_down": 0, "rate_up": 0,
        "free_bytes": 0, "total_bytes": 0,
    }
    errors = []
    for s in servers:
        try:
            cli = TransmissionClient(s)
            data = cli.list_torrents()
            sess = cli.session_stats()
            space = {"free_bytes": 0, "free_text": "-", "total_bytes": 0, "total_text": "", "path": ""}
            try:
                space = cli.free_space()
            except Exception:
                pass
            st = data["stats"]
            for k in agg:
                if k.endswith("_text") or k == "ratio":
                    continue
                if k in ("free_bytes", "total_bytes"):
                    continue
                agg[k] = agg.get(k, 0) + int(st.get(k) or 0)
            agg["free_bytes"] += int(space.get("free_bytes") or 0)
            agg["total_bytes"] += int(space.get("total_bytes") or 0)
            all_items.extend(data["items"])
            server_rows.append({
                "id": s.get("id"),
                "name": s.get("name") or s.get("id"),
                "ok": True,
                "stats": st,
                "session": sess,
                "free_bytes": space.get("free_bytes") or 0,
                "free_text": space.get("free_text") or "-",
                "total_bytes": space.get("total_bytes") or 0,
                "total_text": space.get("total_text") or "",
                "download_dir": space.get("path") or "",
            })
        except Exception as e:
            errors.append({"id": s.get("id"), "name": s.get("name") or s.get("id"), "error": str(e)})
            server_rows.append({
                "id": s.get("id"),
                "name": s.get("name") or s.get("id"),
                "ok": False,
                "error": str(e),
            })

    agg["size_text"] = TransmissionClient._fmt_bytes(agg["size_bytes"])
    agg["downloaded_text"] = TransmissionClient._fmt_bytes(agg["downloaded_bytes"])
    agg["uploaded_text"] = TransmissionClient._fmt_bytes(agg["uploaded_bytes"])
    agg["rate_down_text"] = TransmissionClient._fmt_speed(agg["rate_down"])
    agg["rate_up_text"] = TransmissionClient._fmt_speed(agg["rate_up"])
    agg["free_text"] = TransmissionClient._fmt_bytes(agg["free_bytes"])
    agg["total_text"] = TransmissionClient._fmt_bytes(agg["total_bytes"]) if agg["total_bytes"] else ""
    agg["ratio"] = round(
        (agg["uploaded_bytes"] / agg["downloaded_bytes"]) if agg["downloaded_bytes"] else 0,
        2,
    )
    all_items.sort(key=lambda x: (-x["rate_down"], -x["rate_up"], -x["percent"], x["name"]))
    return {
        "ok": True,
        "server_id": server_id or "",
        "servers": server_rows,
        "stats": agg,
        "items": all_items,
        "errors": errors,
    }


def save_servers(servers: list, default_id: str = None, auto_server_id: str = None):
    cfg = load_config()
    cfg["tr_servers"] = servers
    if default_id is not None:
        cfg["tr_default_id"] = default_id
    if auto_server_id is not None:
        cfg["tr_auto_server_id"] = auto_server_id
    save_config(cfg)
    return cfg


def torrent_action(server_id: str, ids: list, action: str) -> dict:
    cli = TransmissionClient.from_id(server_id)
    act = (action or "").strip().lower()
    if act == "start":
        return cli.start_torrents(ids)
    if act == "stop":
        return cli.stop_torrents(ids)
    if act == "remove":
        return cli.remove_torrents(ids, delete_data=False)
    if act in ("remove_data", "remove-data", "purge"):
        return cli.remove_torrents(ids, delete_data=True)
    raise TransmissionError(f"不支持的操作: {action}")


def _match_rules(item: dict, cfg: dict, now_ts: int) -> list:
    reasons = []
    finished = bool(item.get("finished"))
    ratio = float(item.get("ratio") or 0)
    err = int(item.get("error") or 0)
    seed_sec = int(item.get("seed_seconds") or 0)
    done_ts = int(item.get("done") or 0)
    act_ts = int(item.get("activity") or 0)
    if done_ts <= 0 and finished:
        done_ts = int(item.get("added") or 0)

    if cfg.get("tr_manage_rule_error") and err:
        reasons.append("异常任务")

    if finished or not cfg.get("tr_manage_only_finished", True):
        if cfg.get("tr_manage_rule_ratio", True):
            min_ratio = float(cfg.get("tr_manage_min_ratio") or 1.0)
            if 0 <= ratio < 999 and ratio >= min_ratio:
                reasons.append(f"分享率≥{min_ratio}")
        if cfg.get("tr_manage_rule_seed_days", True):
            days = float(cfg.get("tr_manage_seed_days") or 3)
            need = max(0.1, days) * 86400
            lived = seed_sec if seed_sec > 0 else (max(0, now_ts - done_ts) if done_ts else 0)
            if lived >= need:
                reasons.append(f"做种≥{days}天")
        if cfg.get("tr_manage_rule_idle_days"):
            days = float(cfg.get("tr_manage_idle_days") or 7)
            need = max(0.1, days) * 86400
            idle_from = act_ts or done_ts
            if finished and idle_from and (now_ts - idle_from) >= need and int(item.get("rate_up") or 0) == 0:
                reasons.append(f"空闲≥{days}天")
    return reasons


def run_tr_manage(dry_run: bool = False, cfg: dict = None) -> dict:
    import time

    cfg = dict(cfg or load_config())
    now_ts = int(time.time())
    delete_data = bool(cfg.get("tr_manage_delete_data", True))
    servers = [s for s in (cfg.get("tr_servers") or []) if s.get("enabled") and (s.get("url") or "").strip()]
    removed = []
    skipped = []
    errors = []

    for s in servers:
        try:
            cli = TransmissionClient(s)
            data = cli.list_torrents()
            items = data.get("items") or []
            hit_ids = []
            hit_meta = []
            for it in items:
                reasons = _match_rules(it, cfg, now_ts)
                if reasons:
                    hit_ids.append(it["id"])
                    hit_meta.append({"id": it["id"], "name": it.get("name"), "reasons": reasons, "ratio": it.get("ratio")})

            if cfg.get("tr_manage_rule_max_seed"):
                max_n = max(1, int(cfg.get("tr_manage_max_seed") or 100))
                seeding = [
                    x for x in items
                    if x.get("finished") and int(x.get("status") or 0) in (5, 6) and x["id"] not in hit_ids
                ]
                if len(seeding) > max_n:
                    seeding.sort(key=lambda x: (float(x.get("ratio") or 0), int(x.get("seed_seconds") or 0)))
                    for it in seeding[: len(seeding) - max_n]:
                        hit_ids.append(it["id"])
                        hit_meta.append({
                            "id": it["id"],
                            "name": it.get("name"),
                            "reasons": [f"做种数超限>{max_n}"],
                            "ratio": it.get("ratio"),
                        })

            if hit_ids and not dry_run:
                cli.remove_torrents(hit_ids, delete_data=delete_data)
            for m in hit_meta:
                row = {
                    "server_id": s.get("id"),
                    "server_name": s.get("name") or s.get("id"),
                    "delete_data": delete_data,
                    "dry_run": bool(dry_run),
                    **m,
                }
                removed.append(row)
                if not dry_run:
                    append_download_log(
                        f"TR自动清理[{row['server_name']}] {m['name']} 原因={','.join(m['reasons'])}",
                        action="tr_auto_clean",
                        **row,
                    )
        except Exception as e:
            errors.append({"server_id": s.get("id"), "server_name": s.get("name"), "error": str(e)})

    result = {
        "ok": True,
        "dry_run": bool(dry_run),
        "removed": removed,
        "count": len(removed),
        "errors": errors,
        "skipped": skipped,
        "delete_data": delete_data,
    }
    if not dry_run:
        from app.timeutil import now_str

        cfg2 = load_config()
        cfg2["tr_manage_last_at"] = now_str()
        cfg2["tr_manage_last_result"] = f"清理{len(removed)}个" + (f" 错误{len(errors)}" if errors else "")
        save_config(cfg2)
    return result
