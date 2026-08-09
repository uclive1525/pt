import random
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.mteam import client, _in_quiet_hours
from app.store import actions_last_hour, append_access_log, load_config, save_config
from app.timeutil import TZ_NAME, fmt, now

scheduler = BackgroundScheduler(timezone=TZ_NAME)
_job_id = "mt_scan"
_checkin_job_id = "mt_checkin"
_ratio_job_id = "mt_ratio"
_tr_manage_job_id = "mt_tr_manage"


def _next_seconds() -> int:
    cfg = load_config()
    lo = int(cfg.get("interval_min") or 300)
    hi = int(cfg.get("interval_max") or 900)
    if hi < lo:
        lo, hi = hi, lo
    base = random.randint(lo, hi)
    jitter = int(base * random.uniform(-0.12, 0.18))
    return max(60, base + jitter)


def _parse_hm(s: str):
    parts = (s or "09:00").strip().split(":")
    h = max(0, min(23, int(parts[0])))
    m = max(0, min(59, int(parts[1]))) if len(parts) > 1 else 0
    return h, m


def _window_for_day(day: datetime, start_hm, end_hm):
    sh, sm = start_hm
    eh, em = end_hm
    start = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = day.replace(hour=eh, minute=em, second=0, microsecond=0)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def compute_next_in_window(cfg: dict, start_key: str, end_key: str, last_key: str,
                           default_start: str = "09:00", default_end: str = "12:00") -> datetime:
    start_hm = _parse_hm(cfg.get(start_key) or default_start)
    end_hm = _parse_hm(cfg.get(end_key) or default_end)
    n = now()
    last = (cfg.get(last_key) or "")[:10]
    today = n.strftime("%Y-%m-%d")
    day0 = n.replace(hour=0, minute=0, second=0, microsecond=0)
    win_start, win_end = _window_for_day(day0, start_hm, end_hm)

    if last == today:
        tomorrow = day0 + timedelta(days=1)
        ws, we = _window_for_day(tomorrow, start_hm, end_hm)
        span = max(0, int((we - ws).total_seconds()))
        return ws + timedelta(seconds=random.randint(0, span))

    if n < win_start:
        span = max(0, int((win_end - win_start).total_seconds()))
        return win_start + timedelta(seconds=random.randint(0, span))

    if n < win_end:
        remain = max(60, int((win_end - n).total_seconds()))
        return n + timedelta(seconds=random.randint(30, min(remain, 600)))

    tomorrow = day0 + timedelta(days=1)
    ws, we = _window_for_day(tomorrow, start_hm, end_hm)
    span = max(0, int((we - ws).total_seconds()))
    return ws + timedelta(seconds=random.randint(0, span))


def compute_next_checkin(cfg: dict = None) -> datetime:
    return compute_next_in_window(
        cfg or load_config(), "checkin_start", "checkin_end", "checkin_last_at", "09:00", "12:00"
    )


def _ratio_weekdays(cfg: dict) -> set:
    raw = cfg.get("ratio_schedule_weekdays")
    if not isinstance(raw, list) or not raw:
        return {0, 1, 2, 3, 4, 5, 6}
    out = set()
    for x in raw:
        try:
            d = int(x)
        except Exception:
            continue
        if 0 <= d <= 6:
            out.add(d)
    return out or {0, 1, 2, 3, 4, 5, 6}


def compute_next_ratio(cfg: dict = None) -> datetime:
    cfg = cfg or load_config()
    start_hm = _parse_hm(cfg.get("ratio_schedule_start") or "14:00")
    end_hm = _parse_hm(cfg.get("ratio_schedule_end") or "18:00")
    weekdays = _ratio_weekdays(cfg)
    n = now()
    last = (cfg.get("ratio_schedule_last_at") or "")[:10]
    today = n.strftime("%Y-%m-%d")
    day0 = n.replace(hour=0, minute=0, second=0, microsecond=0)

    for offset in range(0, 15):
        day = day0 + timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        win_start, win_end = _window_for_day(day, start_hm, end_hm)
        day_key = day.strftime("%Y-%m-%d")
        if day_key == today and last == today:
            continue
        if n < win_start:
            span = max(0, int((win_end - win_start).total_seconds()))
            return win_start + timedelta(seconds=random.randint(0, span))
        if n < win_end and day_key == today:
            remain = max(60, int((win_end - n).total_seconds()))
            return n + timedelta(seconds=random.randint(30, min(remain, 600)))
        if n >= win_end and day_key == today:
            continue
        if day_key > today:
            span = max(0, int((win_end - win_start).total_seconds()))
            return win_start + timedelta(seconds=random.randint(0, span))

    tomorrow = day0 + timedelta(days=1)
    ws, we = _window_for_day(tomorrow, start_hm, end_hm)
    span = max(0, int((we - ws).total_seconds()))
    return ws + timedelta(seconds=random.randint(0, span))


def _run_once():
    try:
        cfg = load_config()
        if _in_quiet_hours(cfg):
            append_access_log("静默时段，延后调度", action="scheduler", reason="quiet")
        else:
            append_access_log("开始拟人化扫描", action="scheduler", event="scan_start")
            result = client.match_and_download()
            append_access_log(
                f"扫描完成 matched={len(result.get('matched') or [])} downloaded={len(result.get('downloaded') or [])}",
                action="scheduler",
                event="scan_done",
                matched=len(result.get("matched") or []),
                downloaded=len(result.get("downloaded") or []),
            )
    except Exception as e:
        append_access_log(f"扫描异常: {e}", action="scheduler", level="error", error=str(e))
    finally:
        if load_config().get("running"):
            _schedule_next()


def _schedule_next(delay_sec=None):
    sec = int(delay_sec) if delay_sec is not None else _next_seconds()
    sec = max(1, sec)
    run_at = now() + timedelta(seconds=sec)
    if scheduler.get_job(_job_id):
        scheduler.remove_job(_job_id)
    scheduler.add_job(_run_once, "date", run_date=run_at, id=_job_id, replace_existing=True)
    next_s = fmt(run_at)
    append_access_log(
        f"下次执行: {next_s} (间隔 {sec}s)",
        action="scheduler",
        event="schedule",
        next_run=next_s,
        interval_sec=sec,
    )


def start_scheduler():
    cfg = load_config()
    cfg["running"] = True
    save_config(cfg)
    if not scheduler.running:
        scheduler.start()
    _schedule_next(delay_sec=random.randint(3, 8))
    append_access_log("调度已启动（拟人随机间隔）", action="scheduler", event="start")


def stop_scheduler():
    cfg = load_config()
    cfg["running"] = False
    save_config(cfg)
    if scheduler.get_job(_job_id):
        scheduler.remove_job(_job_id)
    append_access_log("调度已停止", action="scheduler", event="stop")


def _run_checkin():
    try:
        cfg = load_config()
        if not cfg.get("checkin_enabled"):
            return
        append_access_log("开始自动签到/保活", action="checkin", event="start")
        result = client.auto_checkin()
        append_access_log(
            f"自动签到完成 browsed={result.get('browsed')}",
            action="checkin",
            event="done",
            browsed=result.get("browsed"),
        )
    except Exception as e:
        append_access_log(f"自动签到异常: {e}", action="checkin", level="error", error=str(e))
    finally:
        if load_config().get("checkin_enabled"):
            schedule_checkin()


def schedule_checkin():
    cfg = load_config()
    if not cfg.get("checkin_enabled"):
        if scheduler.get_job(_checkin_job_id):
            scheduler.remove_job(_checkin_job_id)
        cfg["checkin_next_at"] = ""
        save_config(cfg)
        return None
    if not scheduler.running:
        scheduler.start()
    run_at = compute_next_checkin(cfg)
    if scheduler.get_job(_checkin_job_id):
        scheduler.remove_job(_checkin_job_id)
    scheduler.add_job(_run_checkin, "date", run_date=run_at, id=_checkin_job_id, replace_existing=True)
    cfg = load_config()
    cfg["checkin_next_at"] = fmt(run_at)
    save_config(cfg)
    append_access_log(
        f"下次自动签到: {cfg['checkin_next_at']}",
        action="checkin",
        event="schedule",
        next_run=cfg["checkin_next_at"],
    )
    return run_at


def stop_checkin():
    if scheduler.get_job(_checkin_job_id):
        scheduler.remove_job(_checkin_job_id)
    cfg = load_config()
    cfg["checkin_next_at"] = ""
    save_config(cfg)


def _run_ratio_schedule():
    reschedule = True
    try:
        cfg = load_config()
        if not cfg.get("ratio_schedule_enabled"):
            return
        if not cfg.get("ratio_assist"):
            append_access_log("定时分享监控跳过：未启用分享率辅助", action="ratio_tips", event="skip")
            return
        if now().weekday() not in _ratio_weekdays(cfg):
            append_access_log("定时分享监控跳过：非选定星期", action="ratio_tips", event="skip_weekday")
            return
        if _in_quiet_hours(cfg):
            append_access_log("定时分享监控：静默时段延后", action="ratio_tips", reason="quiet")
            schedule_ratio(delay_sec=random.randint(600, 1200))
            reschedule = False
            return
        limit = int(cfg.get("max_actions_per_hour") or 40)
        used = actions_last_hour()
        need = max(1, min(5, int(cfg.get("ratio_pages") or 3))) + 2
        if used + need > limit:
            append_access_log(
                f"定时分享监控延后：小时配额不足 {used}/{limit}",
                action="ratio_tips",
                level="warn",
                event="defer",
                used=used,
                limit=limit,
            )
            schedule_ratio(delay_sec=random.randint(900, 1800))
            reschedule = False
            return
        append_access_log("开始定时分享监控", action="ratio_tips", event="start")
        items = client.ratio_tips()
        cfg = load_config()
        cfg["ratio_schedule_last_at"] = fmt(now())
        save_config(cfg)
        append_access_log(
            f"定时分享监控完成 候选={len(items or [])}",
            action="ratio_tips",
            event="done",
            count=len(items or []),
        )
    except Exception as e:
        append_access_log(f"定时分享监控异常: {e}", action="ratio_tips", level="error", error=str(e))
    finally:
        if reschedule and load_config().get("ratio_schedule_enabled"):
            schedule_ratio()


def schedule_ratio(delay_sec=None):
    cfg = load_config()
    if not cfg.get("ratio_schedule_enabled"):
        if scheduler.get_job(_ratio_job_id):
            scheduler.remove_job(_ratio_job_id)
        cfg["ratio_schedule_next_at"] = ""
        save_config(cfg)
        return None
    if not scheduler.running:
        scheduler.start()
    if delay_sec is not None:
        run_at = now() + timedelta(seconds=max(60, int(delay_sec)))
    else:
        run_at = compute_next_ratio(cfg)
    if scheduler.get_job(_ratio_job_id):
        scheduler.remove_job(_ratio_job_id)
    scheduler.add_job(_run_ratio_schedule, "date", run_date=run_at, id=_ratio_job_id, replace_existing=True)
    cfg = load_config()
    cfg["ratio_schedule_next_at"] = fmt(run_at)
    save_config(cfg)
    append_access_log(
        f"下次定时分享监控: {cfg['ratio_schedule_next_at']}",
        action="ratio_tips",
        event="schedule",
        next_run=cfg["ratio_schedule_next_at"],
    )
    return run_at


def stop_ratio():
    if scheduler.get_job(_ratio_job_id):
        scheduler.remove_job(_ratio_job_id)
    cfg = load_config()
    cfg["ratio_schedule_next_at"] = ""
    save_config(cfg)


def _run_tr_manage():
    try:
        cfg = load_config()
        if not cfg.get("tr_manage_enabled"):
            return
        from app.transmission import run_tr_manage

        result = run_tr_manage(dry_run=False, cfg=cfg)
        append_access_log(
            f"TR自动清理完成 count={result.get('count')} errors={len(result.get('errors') or [])}",
            action="tr_manage",
            event="done",
            count=result.get("count"),
            errors=len(result.get("errors") or []),
        )
    except Exception as e:
        append_access_log(f"TR自动清理异常: {e}", action="tr_manage", level="error", error=str(e))
    finally:
        if load_config().get("tr_manage_enabled"):
            schedule_tr_manage()


def schedule_tr_manage(delay_sec=None):
    cfg = load_config()
    if not cfg.get("tr_manage_enabled"):
        if scheduler.get_job(_tr_manage_job_id):
            scheduler.remove_job(_tr_manage_job_id)
        cfg["tr_manage_next_at"] = ""
        save_config(cfg)
        return None
    if not scheduler.running:
        scheduler.start()
    mins = max(5, int(cfg.get("tr_manage_interval_min") or 60))
    sec = int(delay_sec) if delay_sec is not None else mins * 60
    run_at = now() + timedelta(seconds=max(30, sec))
    if scheduler.get_job(_tr_manage_job_id):
        scheduler.remove_job(_tr_manage_job_id)
    scheduler.add_job(_run_tr_manage, "date", run_date=run_at, id=_tr_manage_job_id, replace_existing=True)
    cfg = load_config()
    cfg["tr_manage_next_at"] = fmt(run_at)
    save_config(cfg)
    append_access_log(
        f"下次TR自动清理: {cfg['tr_manage_next_at']}",
        action="tr_manage",
        event="schedule",
        next_run=cfg["tr_manage_next_at"],
    )
    return run_at


def stop_tr_manage():
    if scheduler.get_job(_tr_manage_job_id):
        scheduler.remove_job(_tr_manage_job_id)
    cfg = load_config()
    cfg["tr_manage_next_at"] = ""
    save_config(cfg)


def status() -> dict:
    job = scheduler.get_job(_job_id) if scheduler.running else None
    cjob = scheduler.get_job(_checkin_job_id) if scheduler.running else None
    rjob = scheduler.get_job(_ratio_job_id) if scheduler.running else None
    tjob = scheduler.get_job(_tr_manage_job_id) if scheduler.running else None
    cfg = load_config()
    return {
        "running": bool(cfg.get("running")),
        "scheduler": scheduler.running,
        "next_run": fmt(job.next_run_time) if job and job.next_run_time else None,
        "actions_last_hour": actions_last_hour(),
        "max_actions_per_hour": cfg.get("max_actions_per_hour"),
        "human_mode": cfg.get("human_mode"),
        "quiet": _in_quiet_hours(cfg),
        "checkin_enabled": bool(cfg.get("checkin_enabled")),
        "checkin_next_at": (
            fmt(cjob.next_run_time)
            if cjob and cjob.next_run_time
            else (cfg.get("checkin_next_at") or "")
        ),
        "checkin_last_at": cfg.get("checkin_last_at") or "",
        "ratio_schedule_enabled": bool(cfg.get("ratio_schedule_enabled")),
        "ratio_schedule_next_at": (
            fmt(rjob.next_run_time)
            if rjob and rjob.next_run_time
            else (cfg.get("ratio_schedule_next_at") or "")
        ),
        "ratio_schedule_last_at": cfg.get("ratio_schedule_last_at") or "",
        "tr_manage_enabled": bool(cfg.get("tr_manage_enabled")),
        "tr_manage_next_at": (
            fmt(tjob.next_run_time)
            if tjob and tjob.next_run_time
            else (cfg.get("tr_manage_next_at") or "")
        ),
        "tr_manage_last_at": cfg.get("tr_manage_last_at") or "",
        "tr_manage_last_result": cfg.get("tr_manage_last_result") or "",
        "timezone": TZ_NAME,
    }
