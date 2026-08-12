# 每日新闻热点推送

每天 **08:00（北京时间）** 自动抓取过去 24 小时的国内外热点新闻，用 DeepSeek 生成中文精选摘要，通过 **PushPlus 推送到微信**。运行在 GitHub Actions 云端，**电脑关机也能推送**。

## 板块

| 板块 | 数据源 |
| --- | --- |
| 国内新消费 | 新浪滚动、东方财富快讯、IT之家（按关键词筛选） |
| 国际新消费 | Retail Dive、TechCrunch（按关键词筛选） |
| 国内科技 | IT之家、新浪滚动 |
| 国际科技 | TechCrunch |
| 中国股市 | 东方财富快讯 + 上证/深证/创业板指数行情 |
| 印尼股市 | Google News（印尼市场）、CNBC Indonesia + 雅加达综合指数（IHSG，Yahoo Finance） |
| 中东局势 | BBC Middle East、半岛电视台 |

每个新闻板块默认 5 条，每条带原文链接；股市板块附指数最新收盘与涨跌幅；周末/节假日显示最近收盘并注明「休市」。

## 目录结构

- `.github/workflows/daily-news.yml` — 定时任务（cron 08:00 北京时间 + 手动触发）
- `src/sources.json` — 数据源、关键词、指数、条数配置
- `src/fetch.py` — 抓取 + 24 小时过滤 + 去重，生成 `data/raw.json`
- `src/summarize.py` — DeepSeek 生成中文摘要，生成 `data/digest.md`；未配置 Key 或失败时自动降级为纯标题+链接
- `src/send.py` — PushPlus 推送，失败重试一次
- 仅使用 Python 标准库，无第三方依赖

## 部署步骤

1. 把本项目推送到 GitHub **私有**仓库（代码不含任何密钥）：
   ```bash
   git init && git add . && git commit -m "init: 每日新闻热点推送"
   gh repo create daily-news-push --private --source=. --push
   ```
2. 在仓库 **Settings → Secrets and variables → Actions → New repository secret** 添加：
   - `PUSHPLUS_TOKEN` — 在 pushplus.plus 微信扫码注册，个人中心获取 token
   - `DEEPSEEK_API_KEY` — 在 platform.deepseek.com 创建 API Key（费用约每天几分钱）
   - （可选）`LLM_BASE_URL` / `LLM_MODEL` — 切换其他 OpenAI 兼容服务，默认 `https://api.deepseek.com` / `deepseek-chat`
3. 在 Actions 页点 **Run workflow** 手动触发一次，验证微信收到推送。
4. 之后每天 08:00 自动运行；每次运行都会上传 `digest.md` 制品，可在 Actions 运行页查看。

## 本地测试

```bash
python src/fetch.py --out data/raw.json          # 抓取并保存候选新闻
python src/summarize.py --in data/raw.json --out data/digest.md   # 生成摘要（无 Key 时走纯标题模式）
python src/send.py --in data/digest.md --dry-run  # 预览将推送的内容
python src/send.py --in data/digest.md            # 真实推送（需设置 PUSHPLUS_TOKEN）
```

设置环境变量示例（PowerShell）：
```powershell
$env:PUSHPLUS_TOKEN = "你的token"
$env:DEEPSEEK_API_KEY = "你的key"
```

## 配置调整

- 每板块条数：改 `sources.json` 的 `items_per_section`。
- 板块/关键词/数据源：编辑 `sources.json` 的 `sections` 与 `sources`。
- 抓取时间窗口：`fetch.py --hours 24`（默认 24 小时）。
- 摘要语言风格：修改 `src/summarize.py` 的提示词。

## 常见问题

- **收不到推送**：检查 `PUSHPLUS_TOKEN` 是否正确、是否已关注 PushPlus 公众号；查看 Actions 运行日志与制品内容。
- **股市指数显示「获取失败」**：新浪/Yahoo 偶发拒绝访问，脚本会自动降级/跳过，不影响新闻部分。
- **内容只有标题没有摘要**：未配置 `DEEPSEEK_API_KEY`，或 AI 调用失败（已自动降级）。
- **周末/节假日**：股市板块显示最近收盘并注明休市；新闻板块照常推送。

## 免责声明

本工具仅做个人资讯聚合，所有内容与链接均来自公开新闻源，版权归原作者/原媒体所有。
