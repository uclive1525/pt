import io
import math
import time
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.store import load_config, load_profile_snapshot, load_tasks
from app.timeutil import now

W, H = 400, 300
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)

# jcalendar 用文泉驿常规字库；此处优先微米黑，勿用 Bold/描边
_FONT_CANDIDATES = [
    (Path(__file__).resolve().parent.parent / "fonts" / "ink.ttc", 0),
    (Path(__file__).resolve().parent.parent / "fonts" / "ink.ttf", 0),
    (Path(__file__).resolve().parent.parent / "fonts" / "ink.otf", 0),
    (Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"), 0),
    (Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"), 0),
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 2),
    (Path("/System/Library/Fonts/STHeiti Light.ttc"), 1),
    (Path("/System/Library/Fonts/Hiragino Sans GB.ttc"), 0),
    (Path("/System/Library/Fonts/PingFang.ttc"), 0),
    (Path("/Library/Fonts/Arial Unicode.ttf"), 0),
]
_FONT_PATH = None
_FONT_INDEX = 0
_FONT_CACHE = {}

_STATUS = {
    "downloaded": "已下",
    "matched": "匹配",
    "pending": "待下",
    "failed": "失败",
}

_CN_NUM = "〇一二三四五六七八九"
_CN_DAY = [
    "",
    "初一",
    "初二",
    "初三",
    "初四",
    "初五",
    "初六",
    "初七",
    "初八",
    "初九",
    "初十",
    "十一",
    "十二",
    "十三",
    "十四",
    "十五",
    "十六",
    "十七",
    "十八",
    "十九",
    "二十",
    "廿一",
    "廿二",
    "廿三",
    "廿四",
    "廿五",
    "廿六",
    "廿七",
    "廿八",
    "廿九",
    "三十",
]
_CN_MONTH = ["", "正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]
_WEEK = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 1900-2100 农历数据（香港天文台算法常用表）
_LUNAR_INFO = [
    0x04BD8, 0x04AE0, 0x0A570, 0x054D5, 0x0D260, 0x0D950, 0x16554, 0x056A0, 0x09AD0, 0x055D2,
    0x04AE0, 0x0A5B6, 0x0A4D0, 0x0D250, 0x1D255, 0x0B540, 0x0D6A0, 0x0ADA2, 0x095B0, 0x14977,
    0x04970, 0x0A4B0, 0x0B4B5, 0x06A50, 0x06D40, 0x1AB54, 0x02B60, 0x09570, 0x052F2, 0x04970,
    0x06566, 0x0D4A0, 0x0EA50, 0x06E95, 0x05AD0, 0x02B60, 0x186E3, 0x092E0, 0x1C8D7, 0x0C950,
    0x0D4A0, 0x1D8A6, 0x0B550, 0x056A0, 0x1A5B4, 0x025D0, 0x092D0, 0x0D2B2, 0x0A950, 0x0B557,
    0x06CA0, 0x0B550, 0x15355, 0x04DA0, 0x0A5B0, 0x14573, 0x052B0, 0x0A9A8, 0x0E950, 0x06AA0,
    0x0AEA6, 0x0AB50, 0x04B60, 0x0AAE4, 0x0A570, 0x05260, 0x0F263, 0x0D950, 0x05B57, 0x056A0,
    0x096D0, 0x04DD5, 0x04AD0, 0x0A4D0, 0x0D4D4, 0x0D250, 0x0D558, 0x0B540, 0x0B6A0, 0x195A6,
    0x095B0, 0x049B0, 0x0A974, 0x0A4B0, 0x0B27A, 0x06A50, 0x06D40, 0x0AF46, 0x0AB60, 0x09570,
    0x04AF5, 0x04970, 0x064B0, 0x074A3, 0x0EA50, 0x06B58, 0x05AC0, 0x0AB60, 0x096D5, 0x092E0,
    0x0C960, 0x0D954, 0x0D4A0, 0x0DA50, 0x07552, 0x056A0, 0x0ABB7, 0x025D0, 0x092D0, 0x0CAB5,
    0x0A950, 0x0B4A0, 0x0BAA4, 0x0AD50, 0x055D9, 0x04BA0, 0x0A5B0, 0x15176, 0x052B0, 0x0A930,
    0x07954, 0x06AA0, 0x0AD50, 0x05B52, 0x04B60, 0x0A6E6, 0x0A4E0, 0x0D260, 0x0EA65, 0x0D530,
    0x05AA0, 0x076A3, 0x096D0, 0x04AFB, 0x04AD0, 0x0A4D0, 0x1D0B6, 0x0D250, 0x0D520, 0x0DD45,
    0x0B5A0, 0x056D0, 0x055B2, 0x049B0, 0x0A577, 0x0A4B0, 0x0AA50, 0x1B255, 0x06D20, 0x0ADA0,
    0x14B63, 0x09370, 0x049F8, 0x04970, 0x064B0, 0x168A6, 0x0EA50, 0x06B20, 0x1A6C4, 0x0AAE0,
    0x0A2E0, 0x0D2E3, 0x0C960, 0x0D557, 0x0D4A0, 0x0DA50, 0x05D55, 0x056A0, 0x0A6D0, 0x055D4,
    0x052D0, 0x0A9B8, 0x0A950, 0x0B4A0, 0x0B6A6, 0x0AD50, 0x055A0, 0x0ABA4, 0x0A5B0, 0x052B0,
    0x0B273, 0x06930, 0x07337, 0x06AA0, 0x0AD50, 0x14B55, 0x04B60, 0x0A570, 0x054E4, 0x0D160,
    0x0E968, 0x0D520, 0x0DAA0, 0x16AA6, 0x056D0, 0x04AE0, 0x0A9D4, 0x0A2D0, 0x0D150, 0x0F252,
    0x0D520,
]

_wx_cache = {"t": 0.0, "city": "", "data": {}}
_geo_cache = {}


def _pick_font_file():
    global _FONT_PATH, _FONT_INDEX
    if _FONT_PATH is not None:
        return _FONT_PATH, _FONT_INDEX
    for p, idx in _FONT_CANDIDATES:
        if not p.exists():
            continue
        try:
            ImageFont.truetype(str(p), size=16, index=idx)
            _FONT_PATH, _FONT_INDEX = p, idx
            return _FONT_PATH, _FONT_INDEX
        except Exception:
            continue
    _FONT_PATH, _FONT_INDEX = Path(""), 0
    return _FONT_PATH, _FONT_INDEX


def _font(size: int):
    size = int(size)
    hit = _FONT_CACHE.get(size)
    if hit is not None:
        return hit
    p, idx = _pick_font_file()
    if p and p.exists():
        try:
            f = ImageFont.truetype(str(p), size=size, index=idx)
            _FONT_CACHE[size] = f
            return f
        except Exception:
            pass
    f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def _short(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _tw(font, text) -> float:
    try:
        b = font.getbbox(text)
        return float(b[2] - b[0])
    except Exception:
        return float(len(text) * max(6, getattr(font, "size", 12) // 2))


def _text(img: Image.Image, xy, text, font, fill=BLACK, heavy=False):
    text = "" if text is None else str(text)
    if not text:
        return
    d = ImageDraw.Draw(img)
    x, y = int(round(xy[0])), int(round(xy[1]))
    d.text((x, y), text, font=font, fill=fill)


def _quantize_bwr(img: Image.Image) -> Image.Image:
    """灰边并入笔画，避免汉字断笔；严格三色输出。"""
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = px[x, y][:3]
            if (r, g, b) in (BLACK, WHITE, RED):
                continue
            if r >= 150 and g <= 130 and b <= 130 and r - max(g, b) >= 25:
                px[x, y] = RED
            elif (r + g + b) / 3 <= 200:
                px[x, y] = BLACK
            else:
                px[x, y] = WHITE
    return img


def _encode_bmp_demo(img: Image.Image) -> bytes:
    """与 inkServerDemo 一致的 24bit 底朝上 BGR BMP。"""
    im = img.convert("RGB")
    w, h = im.size
    row_size = ((w * 3 + 3) // 4) * 4
    pad = row_size - w * 3
    pixels = im.load()
    data = bytearray(row_size * h)
    for y in range(h):
        src_y = h - 1 - y
        off = y * row_size
        for x in range(w):
            r, g, b = pixels[x, src_y]
            i = off + x * 3
            data[i] = b
            data[i + 1] = g
            data[i + 2] = r
        for p in range(pad):
            data[off + w * 3 + p] = 0
    file_size = 54 + len(data)
    header = bytearray(54)
    header[0:2] = b"BM"
    header[2:6] = file_size.to_bytes(4, "little")
    header[10:14] = (54).to_bytes(4, "little")
    header[14:18] = (40).to_bytes(4, "little")
    header[18:22] = int(w).to_bytes(4, "little", signed=True)
    header[22:26] = int(h).to_bytes(4, "little", signed=True)
    header[26:28] = (1).to_bytes(2, "little")
    header[28:30] = (24).to_bytes(2, "little")
    header[34:38] = len(data).to_bytes(4, "little")
    header[38:42] = (2835).to_bytes(4, "little", signed=True)
    header[42:46] = (2835).to_bytes(4, "little", signed=True)
    return bytes(header) + bytes(data)


def _leap_month(y: int) -> int:
    return _LUNAR_INFO[y - 1900] & 0xF


def _leap_days(y: int) -> int:
    if _leap_month(y):
        return 30 if (_LUNAR_INFO[y - 1900] & 0x10000) else 29
    return 0


def _month_days(y: int, m: int) -> int:
    return 30 if (_LUNAR_INFO[y - 1900] & (0x10000 >> m)) else 29


def _year_days(y: int) -> int:
    sum_d = 348
    i = 0x8000
    while i > 0x8:
        sum_d += 1 if (_LUNAR_INFO[y - 1900] & i) else 0
        i >>= 1
    return sum_d + _leap_days(y)


def _solar_to_lunar(d: date):
    base = date(1900, 1, 31)
    offset = (d - base).days
    ly = 1900
    while ly < 2100:
        yd = _year_days(ly)
        if offset < yd:
            break
        offset -= yd
        ly += 1
    leap = _leap_month(ly)
    is_leap = False
    lm = 1
    while lm < 13:
        if leap > 0 and lm == leap + 1 and not is_leap:
            lm -= 1
            is_leap = True
            days = _leap_days(ly)
        else:
            days = _month_days(ly, lm)
        if offset < days:
            break
        offset -= days
        if is_leap and lm == leap + 1:
            is_leap = False
        lm += 1
    ld = offset + 1
    if lm > 12:
        lm = 12
    if ld < 1:
        ld = 1
    if ld > 30:
        ld = 30
    return ly, lm, ld, is_leap


def _lunar_text(d: date) -> str:
    _, m, day, is_leap = _solar_to_lunar(d)
    prefix = "闰" if is_leap else ""
    return f"{prefix}{_CN_MONTH[m]}月{_CN_DAY[day]}"


def _lunar_ymd(y: int, m: int, day: int, leap: bool = False) -> date:
    base = date(1900, 1, 31)
    offset = 0
    for i in range(1900, y):
        offset += _year_days(i)
    leap_m = _leap_month(y)
    for i in range(1, m):
        offset += _month_days(y, i)
        if leap_m == i:
            offset += _leap_days(y)
    if leap and leap_m == m:
        offset += _month_days(y, m)
    offset += day - 1
    return base + timedelta(days=offset)


def _next_festival(today: date):
    items = []
    for y in (today.year, today.year + 1):
        items.append((_lunar_ymd(y, 1, 1), "春节"))
        items.append((_lunar_ymd(y, 1, 15), "元宵节"))
        items.append((_lunar_ymd(y, 5, 5), "端午节"))
        items.append((_lunar_ymd(y, 8, 15), "中秋节"))
        items.append((date(y, 10, 1), "国庆节"))
        items.append((date(y, 1, 1), "元旦"))
    items = sorted((d, n) for d, n in items if d >= today)
    if not items:
        return "春节", 0
    d, name = items[0]
    return name, (d - today).days


def _cn_loc_label(parts) -> str:
    """把 [区/名, 市, 省] 拼成 省市区，去掉「成都+成都市」重复。"""
    items = [str(p).strip() for p in (parts or []) if str(p).strip() and str(p).strip() not in ("中国", "China")]
    if not items:
        return ""
    if len(items) >= 3:
        district, city, province = items[0], items[1], items[2]
        d0 = district.replace("市", "").replace("区", "").replace("县", "")
        c0 = city.replace("市", "").replace("区", "").replace("县", "")
        if district == city or d0 == c0 or city.startswith(district):
            return f"{province}{city}"
        return f"{province}{city}{district}"
    if len(items) == 2:
        return f"{items[1]}{items[0]}"
    return items[0]


def _loc_from_nominatim(row: dict) -> str:
    disp = (row.get("display_name") or "").strip()
    if disp:
        parts = [p.strip() for p in disp.split(",")]
        label = _cn_loc_label(parts)
        if label:
            return label
    addr = row.get("address") or {}
    state = (addr.get("state") or addr.get("province") or "").strip()
    city = (addr.get("city") or addr.get("municipality") or "").strip()
    district = (
        addr.get("suburb")
        or addr.get("county")
        or addr.get("district")
        or addr.get("town")
        or addr.get("city_district")
        or ""
    ).strip()
    # Nominatim 常把区填到 city；若 city 已是区且有 state，用 display 优先已处理
    bits = [x for x in (state, city, district) if x]
    # 去重保序
    seen = set()
    uniq = []
    for b in bits:
        if b in seen:
            continue
        seen.add(b)
        uniq.append(b)
    return "".join(uniq)


def _norm_admin(name: str, suffix: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    if any(s.endswith(x) for x in ("省", "市", "区", "县", "州", "盟", "旗")):
        return s
    return s + suffix


def _resolve_city(city: str):
    city = (city or "四川省成都市郫都区").strip() or "四川省成都市郫都区"
    hit = _geo_cache.get(city)
    if hit:
        return hit
    # 1) Nominatim：支持区县级
    try:
        import httpx

        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": city,
                "format": "json",
                "addressdetails": 1,
                "limit": 3,
                "accept-language": "zh",
                "countrycodes": "cn",
            },
            headers={"User-Agent": "mt-pt-ink/1.0"},
            timeout=8.0,
        )
        rows = r.json() or []
        if rows:
            row = rows[0]
            lat = float(row["lat"])
            lon = float(row["lon"])
            loc = _loc_from_nominatim(row) or city
            info = (lat, lon, loc)
            _geo_cache[city] = info
            return info
    except Exception:
        pass
    # 2) Open-Meteo 兜底
    try:
        import httpx

        r = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 5, "language": "zh"},
            timeout=6.0,
        )
        results = (r.json() or {}).get("results") or []
        cn = [x for x in results if (x.get("country_code") or "").upper() == "CN"] or results
        if cn:
            row = cn[0]
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            admin1 = _norm_admin(row.get("admin1") or "", "省")
            admin2 = _norm_admin(row.get("admin2") or "", "市")
            name = (row.get("name") or "").strip()
            bits = []
            for p in (admin1, admin2, name):
                if p and p not in bits:
                    bits.append(p)
            loc = "".join(bits) or city
            info = (lat, lon, loc)
            _geo_cache[city] = info
            return info
    except Exception:
        pass
    fallback = {
        "四川省成都市郫都区": (30.7980, 103.8986, "四川省成都市郫都区"),
        "成都市郫都区": (30.7980, 103.8986, "四川省成都市郫都区"),
        "郫都区": (30.7980, 103.8986, "四川省成都市郫都区"),
        "四川省成都市": (30.6667, 104.0667, "四川省成都市"),
        "成都": (30.6667, 104.0667, "四川省成都市"),
        "上海": (31.23, 121.47, "上海市"),
        "北京": (39.90, 116.41, "北京市"),
        "深圳": (22.54, 114.06, "广东省深圳市"),
        "广州": (23.13, 113.26, "广东省广州市"),
        "杭州": (30.25, 120.17, "浙江省杭州市"),
    }
    if city in fallback:
        return fallback[city]
    for k, v in fallback.items():
        if k in city or city in k:
            return v
    return (30.7980, 103.8986, city if ("省" in city or "市" in city or "区" in city) else "四川省成都市郫都区")


def _fetch_weather(city: str) -> dict:
    city = (city or "四川省成都市郫都区").strip() or "四川省成都市郫都区"
    now_t = time.time()
    if _wx_cache.get("city") == city and now_t - float(_wx_cache.get("t") or 0) < 1800:
        return _wx_cache.get("data") or {}
    lat, lon, loc = _resolve_city(city)
    out = {"temp": None, "humidity": None, "aqi": None, "loc": loc, "code": None, "lat": lat, "lon": lon}
    try:
        import httpx

        with httpx.Client(timeout=8.0) as c:
            wr = c.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,weather_code",
                    "timezone": "Asia/Shanghai",
                },
            )
            cur = (wr.json() or {}).get("current") or {}
            if cur.get("temperature_2m") is not None:
                out["temp"] = int(round(float(cur["temperature_2m"])))
            if cur.get("relative_humidity_2m") is not None:
                out["humidity"] = int(cur["relative_humidity_2m"])
            out["code"] = cur.get("weather_code")
            ar = c.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "us_aqi",
                    "timezone": "Asia/Shanghai",
                },
            )
            ac = (ar.json() or {}).get("current") or {}
            if ac.get("us_aqi") is not None:
                out["aqi"] = int(ac["us_aqi"])
    except Exception:
        pass
    _wx_cache["t"] = now_t
    _wx_cache["city"] = city
    _wx_cache["data"] = out
    return out


def _draw_weather_icon(d, x, y, code, rainy=False):
    # 约 28x28
    if rainy or (code is not None and int(code) >= 51):
        d.ellipse((x + 2, y + 6, x + 16, y + 18), outline=BLACK, width=2)
        d.ellipse((x + 8, y + 2, x + 24, y + 16), outline=BLACK, width=2)
        for i in range(3):
            d.line((x + 6 + i * 6, y + 20, x + 4 + i * 6, y + 26), fill=RED, width=2)
        return
    d.ellipse((x + 6, y + 6, x + 22, y + 22), outline=BLACK, width=2)
    d.ellipse((x + 9, y + 9, x + 19, y + 19), fill=RED, outline=RED)
    for ang in range(0, 360, 45):
        rad = math.radians(ang)
        cx, cy = x + 14, y + 14
        d.line(
            (cx + int(10 * math.cos(rad)), cy + int(10 * math.sin(rad)), cx + int(13 * math.cos(rad)), cy + int(13 * math.sin(rad))),
            fill=BLACK,
            width=2,
        )


def _tr_snapshot() -> dict:
    try:
        from app.transmission import collect_tr_overview

        return collect_tr_overview(None) or {}
    except Exception as e:
        return {"stats": {}, "servers": [], "errors": [{"error": str(e)}]}


def _task_sort_key(t: dict):
    order = {"failed": 0, "pending": 1, "matched": 2, "downloaded": 3}
    return (order.get(t.get("status") or "", 9), -(len(t.get("updated_at") or "")), t.get("updated_at") or "")


def _bv_to_pct(v: float):
    """锂电分段（与常见 ESP32 墨水屏固件一致）。"""
    if v > 20:
        v = v / 1000.0
    if v <= 0:
        return None
    table = (
        (4.20, 100),
        (4.10, 90),
        (4.00, 80),
        (3.90, 65),
        (3.80, 45),
        (3.70, 25),
        (3.60, 12),
        (3.50, 5),
        (3.30, 0),
    )
    if v >= table[0][0]:
        return 100
    if v <= table[-1][0]:
        return 0
    for i in range(len(table) - 1):
        v1, p1 = table[i]
        v0, p0 = table[i + 1]
        if v0 <= v <= v1:
            t = (v - v0) / (v1 - v0) if v1 != v0 else 0
            return int(round(p0 + t * (p1 - p0)))
    return None


def _parse_battery(meta: dict):
    """inkServerDemo：battery=0-100；否则 bv 电压(mV/V)。"""
    meta = meta or {}
    for key in ("battery", "bat", "soc"):
        bat = meta.get(key)
        if bat in (None, ""):
            continue
        try:
            n = float(str(bat).strip().rstrip("%"))
            if 0 <= n <= 100:
                return int(round(n))
            if n > 100:
                pct = _bv_to_pct(n)
                if pct is not None:
                    return pct
        except Exception:
            pass
    for key in ("bv", "batteryValue", "voltage", "volt"):
        bv = meta.get(key)
        if bv in (None, ""):
            continue
        try:
            pct = _bv_to_pct(float(str(bv).strip().rstrip("vVmM")))
            if pct is not None:
                return pct
        except Exception:
            pass
    logs = str(meta.get("logs") or "")
    if logs:
        import re

        m = re.search(r"(?:battery|bat|soc)\s*[:=]\s*(\d{1,3})", logs, re.I)
        if m:
            n = int(m.group(1))
            if 0 <= n <= 100:
                return n
        m = re.search(r"(?:bv|volt(?:age)?)\s*[:=]\s*(\d+(?:\.\d+)?)", logs, re.I)
        if m:
            try:
                return _bv_to_pct(float(m.group(1)))
            except Exception:
                pass
    return None


def build_panel(meta: dict = None) -> bytes:
    meta = meta or {}
    cfg = load_config()
    snap = load_profile_snapshot() or {}
    tasks = [x for x in load_tasks() if (x.get("source") or "hobby") == "hobby"]
    tasks_sorted = sorted(tasks, key=_task_sort_key)
    n_pending = len([x for x in tasks if x.get("status") in ("pending", "matched")])
    n_done = len([x for x in tasks if x.get("status") == "downloaded"])
    n_fail = len([x for x in tasks if x.get("status") == "failed"])

    tr = _tr_snapshot()
    st = tr.get("stats") or {}
    servers = tr.get("servers") or []
    ok_n = len([s for s in servers if s.get("ok")])
    err_n = len([s for s in servers if not s.get("ok")])
    total_n = len(servers) or len([s for s in (cfg.get("tr_servers") or []) if s.get("enabled")])

    dt = now()
    today = dt.date()
    wx = _fetch_weather(cfg.get("ink_city") or "四川省成都市郫都区")
    fest_name, fest_days = _next_festival(today)
    lunar = _lunar_text(today)
    week = _WEEK[today.weekday()]

    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f16 = _font(17)
    f14 = _font(15)
    f13 = _font(14)
    f12 = _font(13)

    # 外框；全页左右内容边距统一
    d.rounded_rectangle((4, 4, W - 5, H - 5), radius=10, outline=BLACK, width=2)
    M = 12
    left, right = M, W - M

    top_y0, top_y1 = 8, 78
    foot_y0, foot_y1 = H - 36, H - 8
    mid_y0, mid_y1 = top_y1 + 2, foot_y0 - 2

    # 顶部分栏
    x1, x2 = 138, 250
    d.line((left, top_y1, right, top_y1), fill=BLACK, width=2)
    d.line((x1, top_y0 + 4, x1, top_y1 - 2), fill=BLACK, width=1)
    d.line((x2, top_y0 + 4, x2, top_y1 - 2), fill=BLACK, width=1)

    # 中/右两行基线；左：天气图标 + 温湿度空气左对齐
    f28 = _font(28)
    row1_y, row2_y = 18, 48
    wx1_y, wx2_y, wx3_y = 14, 34, 54
    tx = left + 38
    code = wx.get("code")
    rainy = code is not None and int(code) >= 51
    icon_h = 28
    icon_y = wx1_y + ((wx3_y + 14) - wx1_y - icon_h) // 2
    _draw_weather_icon(d, left, icon_y, code, rainy=rainy)
    temp = wx.get("temp")
    hum = wx.get("humidity")
    aqi = wx.get("aqi")
    _text(img, (tx, wx1_y), f"温度: {temp if temp is not None else '-'}°C", f13)
    _text(img, (tx, wx2_y), f"湿度: {hum if hum is not None else '-'}%", f13)
    air_s = f"空气: {aqi}" if aqi is not None else f"时间: {dt.strftime('%H:%M')}"
    air_fill = RED if (aqi is not None and aqi > 100) else BLACK
    _text(img, (tx, wx3_y), air_s, f13, air_fill)

    ym_s = f"{today.year}年{today.month:02d}月"
    day_s = f"{today.day:02d}"
    ym_font = f13 if d.textlength(ym_s, font=f14) > (x2 - x1 - 2 * M) else f14
    ymw = _tw(ym_font, ym_s)
    dw = _tw(f28, day_s)
    cx = (x1 + x2) // 2
    _text(img, (cx - ymw / 2, row1_y), ym_s, ym_font)
    _text(img, (cx - dw / 2, row2_y - 4), day_s, f28, RED, heavy=True)

    lw = _tw(f16, lunar)
    ww = _tw(f16, week)
    rx = (x2 + right) // 2
    _text(img, (rx - lw / 2, row1_y), lunar, f16)
    _text(img, (rx - ww / 2, row2_y), week, f16, RED, heavy=True)

    # 中间：种控台（高度限制在页脚之上）
    uid = str(snap.get("uid") or "-").strip() or "-"
    data_ts = (snap.get("ts") or "").strip()
    if len(data_ts) >= 16:
        sync_md = data_ts[5:16]
    elif len(data_ts) >= 10:
        sync_md = data_ts[5:10]
    elif data_ts:
        sync_md = data_ts
    else:
        sync_md = "--"

    ratio = snap.get("share_rate")
    bonus = snap.get("bonus")
    up = snap.get("uploaded_text") or "-"
    down = snap.get("downloaded_text") or "-"
    seed = snap.get("seeding")
    leech = snap.get("leeching")

    cols = 4
    y_limit = foot_y0 - 4

    def _cell(txt, font, col, yy, fill=BLACK, heavy=False, n=cols):
        if yy > y_limit - 12:
            return
        cw = (right - left) / n
        x = left + col * cw
        _text(img, (x, yy), txt, font, fill, heavy=heavy)

    y = mid_y0 + 4
    gap = 8
    from app.transmission import TransmissionClient

    free_bytes = int(st.get("free_bytes") or 0)
    total_bytes = int(st.get("total_bytes") or 0)
    free_text = (st.get("free_text") or "").strip()
    total_text = (st.get("total_text") or "").strip()
    if (not free_text or free_text == "-") or not total_bytes:
        free_bytes = 0
        total_bytes = 0
        for s in servers or []:
            if s.get("ok"):
                free_bytes += int(s.get("free_bytes") or 0)
                total_bytes += int(s.get("total_bytes") or 0)
        if free_bytes > 0:
            free_text = TransmissionClient._fmt_bytes(free_bytes)
        if total_bytes > 0:
            total_text = TransmissionClient._fmt_bytes(total_bytes)
    if free_text and free_text != "-" and total_text:
        space_s = f"磁盘:{free_text} / {total_text}"
    elif free_text and free_text != "-":
        space_s = f"磁盘:{free_text}"
    else:
        space_s = ""
    space_fill = RED if free_bytes and free_bytes < 20 * 1024 ** 3 else BLACK
    right_s = f"同步{sync_md}"
    _text(img, (left, y), "种控台", f13, RED)
    y += 16
    uid_s = f"UID {uid}"
    _text(img, (left, y), uid_s, f12)
    _text(img, (right - _tw(f12, right_s), y), right_s, f12)
    if space_s:
        _text(img, ((left + right - _tw(f12, space_s)) / 2, y), space_s, f12, space_fill)

    y += 18
    for i, (k, v, c) in enumerate([
        ("分享率", f"{ratio if ratio is not None else '-'}", RED),
        ("魔力", f"{bonus if bonus is not None else '-'}", RED),
        ("上传", up, BLACK),
        ("下载", down, RED),
    ]):
        _cell(k, f12, i, y)
        _cell(_short(str(v), 9), f14, i, y + 15, c)

    y += 36
    for i, t in enumerate([
        f"站做种 {seed if seed is not None else '-'}",
        f"站下载 {leech if leech is not None else '-'}",
        f"暂停 {st.get('paused', 0)}",
        f"异常 {st.get('error', 0)}",
    ]):
        _cell(t, f12, i, y, RED if (i == 3 and st.get("error")) else BLACK)

    y += 18
    if y < y_limit:
        d.line((left, y, right, y), fill=BLACK, width=1)
    y += 6
    status = f"{ok_n}/{total_n}" if total_n else "0"
    rd = st.get("rate_down_text") or "0"
    ru = st.get("rate_up_text") or "0"
    for i, (t, c) in enumerate([
        ("TR汇总", BLACK),
        (f"{status}台", RED if err_n else BLACK),
        (f"↓{rd}", BLACK),
        (f"↑{ru}", RED),
    ]):
        _cell(t, f13, i, y, c)

    y += 17
    tr_color = RED if err_n or st.get("error") else BLACK
    for i, t in enumerate([
        f"任务 {st.get('total', 0)}",
        f"下 {st.get('downloading', 0)}",
        f"种 {st.get('seeding', 0)}",
        f"停 {st.get('paused', 0)}",
    ]):
        _cell(t, f12, i, y, tr_color)

    y += 16
    for i, (t, c) in enumerate([
        (f"错 {st.get('error', 0)}", RED if st.get("error") else BLACK),
        (f"量 {st.get('size_text') or '-'}", BLACK),
        (f"↑ {st.get('uploaded_text') or '-'}", RED),
        (f"↓ {st.get('downloaded_text') or '-'}", BLACK),
    ]):
        _cell(t, f12, i, y, c)

    y += 17
    if y < y_limit:
        d.line((left, y, right, y), fill=BLACK, width=1)
    sec_top = y + 1
    mon_color = RED if (n_fail or n_pending) else BLACK
    mon_cells = [
        ("监控", BLACK),
        (f"共 {len(tasks)}", mon_color),
        (f"待 {n_pending}", mon_color),
        (f"已 {n_done}" + (f" 败{n_fail}" if n_fail else ""), mon_color),
    ]
    task_lines = []
    if tasks_sorted:
        for t in tasks_sorted[:2]:
            st_name = _STATUS.get(t.get("status") or "", "-")
            title = _short(t.get("cn_name") or t.get("name") or "-", 14)
            color = RED if t.get("status") in ("failed", "pending") else BLACK
            task_lines.append((f"{st_name}  {title}", color))
    line_h = 15
    block_h = line_h + len(task_lines) * line_h
    avail = max(0, foot_y0 - sec_top)
    y = sec_top + max(0, (avail - block_h) // 2)
    if y <= y_limit - 12:
        for i, (t, c) in enumerate(mon_cells):
            _cell(t, f13, i, y, c)
    y += line_h
    for txt, fill in task_lines:
        if y > y_limit - 12:
            break
        _text(img, (left, y), txt, f12, fill)
        y += line_h

    # 底栏最后画，避免被中间内容压住
    d.rectangle((6, foot_y0, W - 7, H - 6), fill=WHITE)
    d.line((left, foot_y0, right, foot_y0), fill=BLACK, width=2)
    loc = _short(wx.get("loc") or (cfg.get("ink_city") or "四川省成都市郫都区"), 14)
    fest = f"距{fest_name}还有{fest_days}天"
    _text(img, (left, foot_y0 + 8), loc, f14)
    fw = _tw(f14, fest)
    _text(img, (right - fw, foot_y0 + 8), fest, f14, RED)

    _quantize_bwr(img)
    return _encode_bmp_demo(img)


def fetch_ota(model: str, devid: str) -> tuple:
    if not model:
        return "", ""
    try:
        import httpx

        r = httpx.get(
            "https://funnycoo.cn:4001/getOtaInfo",
            params={"model": model, "devid": devid or "", "devId": devid or ""},
            timeout=8.0,
        )
        data = r.json()
        if data.get("success") and isinstance(data.get("data"), dict):
            return str(data["data"].get("ver") or ""), str(data["data"].get("md5") or "")
    except Exception:
        pass
    return "", ""
