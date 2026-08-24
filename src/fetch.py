#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取新闻源并生成 raw.json：7 个板块的候选条目 + 指数行情。仅用 Python 标准库。"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

def _setup_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_stdout()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(BASE_DIR, "sources.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BEIJING = timezone(timedelta(hours=8))


def log(msg):
    print("[fetch] " + msg, flush=True)


def http_get(url, referer=None, timeout=20, tries=3):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    last_err = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset()
                return raw.decode(charset or "utf-8", "ignore")
        except Exception as e:
            last_err = e
            if attempt < tries - 1:
                log("请求重试({0}/3)：{1}".format(attempt + 2, e))
                time.sleep(1.5 * (attempt + 1))
    raise last_err


def strip_tags(html):
    if not html:
        return ""
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def local_child(el, name):
    for c in el:
        if c.tag.split("}")[-1] == name:
            return c
    return None


def local_text(el, name):
    c = local_child(el, name)
    if c is None or c.text is None:
        return ""
    return c.text.strip()


def norm_title(t):
    return re.sub(r"\s+", "", t or "").lower()


def parse_rss(source):
    text = http_get(source["url"])
    root = ET.fromstring(text)
    items = []
    for el in root.iter():
        if el.tag.split("}")[-1] != "item":
            continue
        title = local_text(el, "title")
        link = local_text(el, "link")
        pub = local_text(el, "pubDate")
        if not title or not link or not pub:
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        desc = strip_tags(local_text(el, "description"))
        items.append({
            "title": title,
            "link": link,
            "time": dt,
            "summary": desc,
            "source": source["name"],
        })
    return items


def parse_sina_roll(source):
    text = http_get(source["url"], referer="https://finance.sina.com.cn/")
    data = json.loads(text)
    rows = ((data or {}).get("result") or {}).get("data") or []
    items = []
    for it in rows:
        title = (it.get("title") or "").strip()
        link = (it.get("url") or "").strip()
        ctime = it.get("ctime")
        if not title or not link or not ctime:
            continue
        try:
            dt = datetime.fromtimestamp(int(ctime), tz=timezone.utc)
        except Exception:
            continue
        items.append({
            "title": title,
            "link": link,
            "time": dt,
            "summary": (it.get("intro") or "").strip(),
            "source": source["name"],
        })
    return items


def parse_eastmoney(source):
    text = http_get(source["url"], referer="https://finance.eastmoney.com/")
    idx = text.find("ajaxResult=")
    if idx < 0:
        raise ValueError("响应格式异常：未找到 ajaxResult")
    raw = text[idx + len("ajaxResult="):].strip()
    if raw.endswith(";"):
        raw = raw[:-1]
    data = json.loads(raw)
    rows = data.get("LivesList") or []
    cn = timezone(timedelta(hours=8))
    items = []
    for it in rows:
        title = (it.get("title") or "").strip()
        link = (it.get("url_w") or "").strip()
        show = (it.get("showtime") or "").strip()
        if not title or not link or not show:
            continue
        try:
            dt = datetime.strptime(show, "%Y-%m-%d %H:%M:%S").replace(tzinfo=cn).astimezone(timezone.utc)
        except Exception:
            continue
        items.append({
            "title": title,
            "link": link,
            "time": dt,
            "summary": strip_tags(it.get("digest") or ""),
            "source": source["name"],
        })
    return items


PARSERS = {
    "rss": parse_rss,
    "sina_roll": parse_sina_roll,
    "eastmoney": parse_eastmoney,
}


def parse_sina_quotes(symbols):
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    try:
        text = raw.decode("utf-8")
        if "\ufffd" in text or ("上证指数" not in text and "深证成指" not in text):
            text = raw.decode("gbk", "ignore")
    except UnicodeDecodeError:
        text = raw.decode("gbk", "ignore")
    result = {}
    for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', text):
        sym, fields = m.group(1), m.group(2).split(",")
        if len(fields) < 4:
            continue
        try:
            prev = float(fields[2])
            price = float(fields[3]) or prev
        except ValueError:
            continue
        pct = (price - prev) / prev * 100 if prev else 0.0
        result[sym] = {"price": price, "prev": prev, "change": price - prev, "pct": pct}
    return result


def parse_yahoo_bars(symbol):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=10d&interval=1d".format(
        urllib.parse.quote(symbol, safe="")
    )
    text = http_get(url, referer="https://finance.yahoo.com/")
    j = json.loads(text)
    res = j["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    timestamps = res["timestamp"]
    vals = [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]
    if len(vals) < 2:
        raise ValueError("K 线数据不足")
    price = vals[-1][1]
    prev = vals[-2][1]
    pct = (price - prev) / prev * 100 if prev else 0.0
    return {"price": price, "prev": prev, "change": price - prev, "pct": pct}


def market_note(offset_hours, trading_hours):
    now = datetime.now(timezone(timedelta(hours=offset_hours)))
    if now.weekday() >= 5:
        return "周末休市，显示最近收盘"
    hm = now.strftime("%H:%M")
    for start, end in trading_hours:
        if start <= hm <= end:
            return "交易中（实时）"
    if hm < trading_hours[0][0]:
        return "盘前，显示上一交易日收盘"
    return "已收盘（显示今日收盘）"


def get_quotes(cfg):
    quotes = {}
    for sec_name, qcfg in (cfg.get("indices") or {}).items():
        lines = []
        note = None
        try:
            if qcfg.get("sina"):
                labels = qcfg.get("labels") or {}
                sina_ok = False
                try:
                    q = parse_sina_quotes(qcfg["sina"])
                    for sym in qcfg["sina"]:
                        if sym in q:
                            d = q[sym]
                            lines.append("{0} {1:.2f}（{2:+.2f}%）".format(labels.get(sym, sym), d["price"], d["pct"]))
                            sina_ok = True
                except Exception as e:
                    log("{0} 新浪行情失败：{1}".format(sec_name, e))
                if not sina_ok:
                    for symbol, label in (qcfg.get("yahoo_fallback") or {}).items():
                        try:
                            d = parse_yahoo_bars(symbol)
                            lines.append("{0} {1:.2f}（{2:+.2f}%）".format(label, d["price"], d["pct"]))
                        except Exception as e:
                            log("{0} Yahoo 行情失败：{1}".format(label, e))
            for item in qcfg.get("yahoo") or []:
                try:
                    d = parse_yahoo_bars(item["symbol"])
                    lines.append("{0} {1:.2f}（{2:+.2f}%）".format(item["label"], d["price"], d["pct"]))
                except Exception as e:
                    log("{0} 行情失败：{1}".format(item["label"], e))
            note = market_note(qcfg.get("utc_offset_hours", 8), qcfg.get("trading_hours", [["09:00", "15:00"]]))
        except Exception as e:
            log("{0} 行情获取异常：{1}".format(sec_name, e))
        quotes[sec_name] = {"lines": lines, "note": note}
    return quotes


def collect_section_items(sec, cache, now, cutoff):
    keywords = [k.lower() for k in (sec.get("keywords") or [])]
    seen = {}
    for src_name in sec.get("sources") or []:
        for it in cache.get(src_name, []):
            if it["time"] < cutoff or it["time"] > now + timedelta(hours=2):
                continue
            if keywords:
                hay = (it["title"] + " " + (it["summary"] or "")).lower()
                if not any(k in hay for k in keywords):
                    continue
            key = norm_title(it["title"])
            if key not in seen or it["time"] > seen[key]["time"]:
                seen[key] = it
    return sorted(seen.values(), key=lambda x: x["time"], reverse=True)


def build_sections(cfg, cache, hours):
    now = datetime.now(timezone.utc)
    raw_per = int(cfg.get("raw_per_section", 12))
    sections = {}
    section_hours = {}
    for sec_name, sec in (cfg.get("sections") or {}).items():
        sec_hours = float(sec.get("hours", hours))
        lst = collect_section_items(sec, cache, now, now - timedelta(hours=sec_hours))
        eff = sec_hours
        if not lst and sec.get("fallback_hours"):
            eff = float(sec["fallback_hours"])
            lst = collect_section_items(sec, cache, now, now - timedelta(hours=eff))
        section_hours[sec_name] = eff
        sections[sec_name] = [
            {
                "title": it["title"],
                "link": it["link"],
                "time_iso": it["time"].isoformat(timespec="seconds"),
                "source": it["source"],
                "summary": (it["summary"] or "")[:300],
            }
            for it in lst[:raw_per]
        ]
    return sections, section_hours


def fetch_source(source, cache):
    if source["name"] in cache:
        return cache[source["name"]]
    parser = PARSERS.get(source.get("type"))
    if parser is None:
        log("跳过未知类型：{0}".format(source.get("type")))
        cache[source["name"]] = []
        return []
    try:
        items = parser(source)
        log("{0}：{1} 条".format(source["name"], len(items)))
    except Exception as e:
        log("{0} 抓取失败：{1}".format(source["name"], e))
        items = []
    cache[source["name"]] = items
    return items


def main():
    ap = argparse.ArgumentParser(description="抓取新闻并生成 raw.json")
    ap.add_argument("--out", default=os.path.join(BASE_DIR, "..", "data", "raw.json"))
    ap.add_argument("--hours", type=float, default=24.0, help="抓取最近 N 小时（默认 24）")
    args = ap.parse_args()

    with open(SOURCES_FILE, encoding="utf-8-sig") as f:
        cfg = json.load(f)

    cache = {}
    for src in cfg.get("sources") or []:
        fetch_source(src, cache)

    sections, section_hours = build_sections(cfg, cache, args.hours)
    quotes = get_quotes(cfg)

    now = datetime.now(BEIJING)
    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "date_label": "{0}月{1}日".format(now.month, now.day),
        "items_per_section": int(cfg.get("items_per_section", 5)),
        "hours": args.hours,
        "section_hours": section_hours,
        "sections": sections,
        "quotes": quotes,
    }
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    log("已写入 {0}".format(out_path))
    for name, items in sections.items():
        log("  {0}：{1} 条候选".format(name, len(items)))
    for name, q in quotes.items():
        log("  {0} 行情：{1}".format(name, "；".join(q["lines"]) or "无数据"))
    sys.exit(0)


if __name__ == "__main__":
    main()
