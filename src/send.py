#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 PushPlus 把 digest.md 推送到微信；失败重试一次。仅用标准库。"""
import argparse
import json
import os
import sys
import time
import urllib.request

def _setup_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_stdout()

API_URLS = [
    "https://www.pushplus.plus/send",
    "http://www.pushplus.plus/send",
]


def log(msg):
    print("[send] " + msg, flush=True)


def send(token, title, content, timeout=30):
    body = {"token": token, "title": title, "content": content, "template": "markdown"}
    last_err = "未知错误"
    for url in API_URLS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    text = resp.read().decode("utf-8", "ignore")
                j = json.loads(text)
                code = j.get("code")
                if code == 200:
                    log("发送成功：{0}".format(url))
                    return True
                last_err = "PushPlus 返回 code={0} msg={1}".format(code, j.get("msg"))
                log("发送未成功：{0}".format(last_err))
            except Exception as e:
                last_err = str(e)
                log("发送异常：{0}".format(e))
            if attempt == 0:
                log("5 秒后重试...")
                time.sleep(5)
    log("最终失败：{0}".format(last_err))
    return False


def default_title(content):
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "每日新闻热点"


def main():
    ap = argparse.ArgumentParser(description="通过 PushPlus 推送 digest.md")
    ap.add_argument("--in", dest="inp", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "digest.md"))
    ap.add_argument("--title", default=None, help="推送标题，默认取 digest 的一级标题")
    ap.add_argument("--dry-run", action="store_true", help="仅打印，不实际发送")
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8") as f:
        content = f.read()

    title = args.title or default_title(content)

    if args.dry_run:
        print("== 标题 ==")
        print(title)
        print("== 内容（前 1000 字符）==")
        print(content[:1000])
        sys.exit(0)

    token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if not token:
        print("错误：未设置 PUSHPLUS_TOKEN 环境变量", file=sys.stderr)
        sys.exit(2)

    ok = send(token, title, content)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
