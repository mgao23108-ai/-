#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于 raw.json 用 LLM 生成中文摘要 digest.md；未配置 Key 或调用失败时降级为纯标题+链接。仅用标准库。"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

def _setup_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_stdout()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BEIJING = timezone(timedelta(hours=8))
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def log(msg):
    print("[summarize] " + msg, flush=True)


def norm_title(t):
    return re.sub(r"\s+", "", t or "").lower()



def fmt_hours(h):
    try:
        f = float(h)
        return str(int(f)) if f.is_integer() else str(f)
    except Exception:
        return str(h)

def fmt_time(iso):
    try:
        dt = datetime.fromisoformat(iso)
        return dt.astimezone(BEIJING).strftime("%m-%d %H:%M")
    except Exception:
        return iso or ""


def build_prompt(data):
    n = int(data.get("items_per_section", 5))
    lines = []
    lines.append("当前北京时间：{0}。以下是最近 {1} 小时各板块候选新闻（已按时间倒序）。".format(data.get("generated_at"), fmt_hours(data.get("hours"))))
    lines.append("请为每个板块挑选最多 {0} 条最有价值、最适合每日晨报的新闻；板块候选为空则返回空数组。".format(n))
    lines.append("要求：")
    lines.append("1. 标题必须与候选中的标题逐字一致，不得改写、不得编造，不得添加候选之外的条目；")
    lines.append("2. 摘要用简体中文写 1-2 句，点出这条新闻的核心看点；")
    lines.append("3. 只输出一个合法 JSON 对象，不要输出任何其他文字、注释或 Markdown。")
    lines.append("JSON 格式：")
    lines.append('{"板块名": [{"title": "原文标题", "summary": "中文摘要"}], ...}')
    lines.append("")
    for sec, items in data.get("sections", {}).items():
        lines.append("## " + sec)
        if not items:
            lines.append("（无候选）")
            continue
        for i, it in enumerate(items, 1):
            lines.append("{0}. 标题：{1}".format(i, it.get("title", "")))
            lines.append("   链接：{0} ｜ 来源：{1} ｜ 时间：{2}".format(it.get("link", ""), it.get("source", ""), fmt_time(it.get("time_iso", ""))))
        lines.append("")
    return "\n".join(lines)


def extract_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM 输出中未找到 JSON 对象")
    return json.loads(text[start:end + 1])


def call_llm(prompt, api_key, base_url, model):
    url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    messages = [
        {
            "role": "system",
            "content": "你是一名严谨的中文新闻编辑。你只使用用户提供的材料，绝不编造标题或链接。输出必须是可以被 json.loads 直接解析的 JSON。",
        },
        {"role": "user", "content": prompt},
    ]
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 6000,
    }
    last_err = None
    for use_json_mode in (True, False):
        body = dict(payload)
        if use_json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                text = resp.read().decode("utf-8", "ignore")
            j = json.loads(text)
            content = j["choices"][0]["message"]["content"]
            return extract_json(content)
        except Exception as e:
            last_err = e
            log("LLM 调用失败（json_mode={0}）：{1}".format(use_json_mode, e))
    raise last_err if last_err else RuntimeError("LLM 调用失败")


def render(data, ai_by_section, ai_used):
    n = int(data.get("items_per_section", 5))
    now = datetime.now(BEIJING)
    weekday = "一二三四五六日"[now.weekday()]
    md = []
    md.append("# 📰 每日新闻热点 · {0}（星期{1}）".format(data.get("date_label", ""), weekday))
    md.append("")
    if ai_used:
        md.append("> 过去 {0} 小时国内外热点精选（AI 摘要）".format(fmt_hours(data.get("hours"))))
    else:
        md.append("> 过去 {0} 小时国内外热点精选（纯标题模式：未配置 LLM Key 或 AI 摘要失败）".format(fmt_hours(data.get("hours"))))
    md.append("")
    for sec, items in data.get("sections", {}).items():
        md.append("## " + sec)
        q = (data.get("quotes") or {}).get(sec)
        if q is not None:
            if q.get("lines"):
                md.append("**指数：** " + " ｜ ".join(q["lines"]))
            else:
                md.append("**指数：** 获取失败")
            if q.get("note"):
                md.append("> " + q["note"])
            md.append("")
        if not items:
            md.append("暂无 24 小时内热点。")
            md.append("")
            continue
        ai_map = {}
        if ai_by_section:
            for x in ai_by_section.get(sec) or []:
                if isinstance(x, dict) and x.get("title"):
                    ai_map[norm_title(x["title"])] = (x.get("summary") or "").strip()
        entries = []
        used = set()
        for it in items:
            key = norm_title(it.get("title", ""))
            if key in ai_map and key not in used:
                entries.append((it, ai_map[key]))
                used.add(key)
        for it in items:
            if len(entries) >= n:
                break
            key = norm_title(it.get("title", ""))
            if key not in used:
                entries.append((it, None))
                used.add(key)
        for idx, (it, summary) in enumerate(entries, 1):
            line = "{0}. **[{1}]({2})**".format(idx, it.get("title", ""), it.get("link", ""))
            if summary:
                line += "\n   " + summary
            line += "\n   —— {0} · {1}".format(it.get("source", ""), fmt_time(it.get("time_iso", "")))
            md.append(line)
        md.append("")
    md.append("---")
    md.append("生成时间：{0}（北京时间）｜数据来源见各条链接".format(now.strftime("%Y-%m-%d %H:%M")))
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description="生成中文摘要 digest.md")
    ap.add_argument("--in", dest="inp", default=os.path.join(BASE_DIR, "..", "data", "raw.json"))
    ap.add_argument("--out", dest="out", default=os.path.join(BASE_DIR, "..", "data", "digest.md"))
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8") as f:
        data = json.load(f)

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()

    ai_by_section = {}
    ai_used = False
    if api_key:
        try:
            prompt = build_prompt(data)
            result = call_llm(prompt, api_key, base_url, model)
            if isinstance(result, dict):
                for sec in data.get("sections", {}):
                    items = result.get(sec)
                    if isinstance(items, list):
                        ai_by_section[sec] = [x for x in items if isinstance(x, dict) and x.get("title")]
                ai_used = True
                log("AI 摘要生成成功")
            else:
                log("AI 输出格式异常，降级为纯标题模式")
        except Exception as e:
            log("AI 摘要失败，降级为纯标题模式：{0}".format(e))
    else:
        log("未设置 LLM_API_KEY，使用纯标题模式")

    md = render(data, ai_by_section, ai_used)
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    log("已写入 {0}（{1} 字符）".format(out_path, len(md)))
    sys.exit(0)


if __name__ == "__main__":
    main()
