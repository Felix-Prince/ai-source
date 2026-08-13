# ai-source · AI 资讯采集 pipeline

一套**完全自采、完全可控**的 AI 资讯采集系统。定时从官方 RSS 抓取 AI 相关内容，归一化、去重、AI 相关性评分后，产出结构化 JSON 并 git 版本化，供外部 agent 或可视化看板消费。

> 设计原则：采集层**零模型依赖**（纯规则代码）、**零密钥**、数据**git 版本化**、**抓用解耦**（消费方只读静态 JSON，不实时爬）。完整方法论见 [HANDOFF.md](HANDOFF.md)。

---

## 一、数据产物（消费方入口）

外部 agent 通过 HTTP GET 拉取（**不需要 clone 仓库**），每次就是一个请求：

| 文件 | URL | 说明 |
|------|-----|------|
| `latest-24h.json` | `https://raw.githubusercontent.com/Felix-Prince/ai-source/main/data/latest-24h.json` | ★ 近 24h 已过滤 AI 相关条目（ai_score ≥ 1.5，importance 排序） |
| `archive.json` | `https://raw.githubusercontent.com/Felix-Prince/ai-source/main/data/archive.json` | 滚动 30 天全量，去重用 |
| `source-status.json` | `https://raw.githubusercontent.com/Felix-Prince/ai-source/main/data/source-status.json` | 各信源健康看板 |
| `batches.json` | `https://raw.githubusercontent.com/Felix-Prince/ai-source/main/data/batches.json` | 采集批次日志（每 6h 一条，供时间轴） |

拉取示例：

```bash
curl -s https://raw.githubusercontent.com/Felix-Prince/ai-source/main/data/latest-24h.json | jq '.items[:5]'
```

### `latest-24h.json` 结构

```jsonc
{
  "meta": {
    "generated_at": "2026-08-13T15:25:30Z",   // UTC
    "generated_ts": 1786634730,                 // 秒级时间戳
    "window_hours": 24,
    "total": 19
  },
  "items": [
    {
      "id": "qbitai:ab12cd34ef56",
      "source": "qbitai",
      "source_label": "量子位",
      "title": "…",
      "url": "https://www.qbitai.com/...",
      "summary": "…",
      "published_at": "2026-08-13T07:00:00+00:00",  // UTC
      "published_ts": 1786561200,
      "category": "domestic",           // domestic | international
      "lang": "zh",                     // zh | en
      "tier": 1,                        // 0=官方一手源 1=媒体RSS
      "ai_score": 2.0,                  // AI 相关性 0~3，低于 1.5 不进产物
      "importance": 1.889              // tier × ai_score × 新鲜度
    }
  ]
}
```

### 可视化看板

- 主看板：<https://felix-prince.github.io/ai-source/>（源健康徽章 + 6h 采集时间轴，条目卡片可点击）
- 独立源健康页：<https://felix-prince.github.io/ai-source/health.html>

---

## 二、架构

```
GitHub Actions (每 6h 定时, 0/6/12/18 点 UTC)
   ↓ scripts/collect.py
   ↓ 读 config/sources.yaml（信源注册表）
   ↓ fetchers/rss.py（feedparser 解析，重试3/超时60/伪装UA/限并发）
   ↓ normalize.py（RawItem → 结构化条目）
   ↓ dedupe.py（哈希精确 + SequenceMatcher 近似>0.8）
   ↓ score.py（AI 关键词相关性 + tier×新鲜度 importance，阈值 ≥ 1.5）
   ↓ health.py（写 source-status.json）
   ↓ 输出 data/latest-24h.json + archive.json + batches.json
   ↓ git commit data/ 回 main（git 版本化）+ 部署 Pages
```

信源阶梯：官方 RSS 为主干 → 别人仓库 Actions feed → newsletter 归档 → 静态页 → 密钥 API（梯级 6，未启用）→ 私人邮箱/cookies（**不碰**）。当前启用 **9 个**源（国内 4：36氪/量子位/钛媒体/cnBeta；国际 5：OpenAI/The Verge/TechCrunch/Ars/VentureBeat，见 [config/sources.yaml](config/sources.yaml)）。

---

## 三、本地开发

```bash
# 1. 装依赖（Python 3.7+；macOS 下用 python3）
python3 -m pip install -r requirements.txt

# 2. 跑采集（本地单机验证）
python3 scripts/collect.py --output-dir data --window-hours 24

# 3. 跑测试
python3 -m unittest discover -s tests
```

主要文件：

| 文件 | 职责 |
|------|------|
| `scripts/collect.py` | 主入口：读源→抓→归一→评分→去重→过滤→写产物 |
| `scripts/fetchers/base.py` | 公共抓取层（重试/超时/UA/限并发） |
| `scripts/fetchers/rss.py` | RSS/Atom 解析 |
| `scripts/normalize.py` | 归一化到统一 schema |
| `scripts/dedupe.py` | 精确 + 近似去重 |
| `scripts/score.py` | AI 关键词评分 + importance |
| `scripts/health.py` | 源健康看板 |
| `config/sources.yaml` | 信源注册表（name/url/type/category/tier/enabled） |

---

## 四、CI/CD

- `.github/workflows/collect.yml` — 每 6h 定时采集（`23 */6 * * *` UTC，即 0/6/12/18 点），产物 commit 回 main，随后部署 GitHub Pages；支持 `workflow_dispatch` 手动触发

手动触发一次采集：

```bash
gh workflow run collect.yml --repo Felix-Prince/ai-source --ref main
```

---

## 五、信源健康监控

每次运行都会刷新 `data/source-status.json`，单源失败不阻断整轮：

```jsonc
{
  "kr36": {
    "status": "failed",      // ok | failed | disabled
    "last_run_at": "...",
    "item_count": 0,
    "fail_count": 1,
    "error": "GET ... failed after 3 tries: ..."  // 失败时记录原因
  }
}
```

持续失败的源可在 `config/sources.yaml` 里 `enabled: false` 关掉，或替换 URL。已知情况：

- **36氪**（2026-08-13 起）：源端风控，所有端点返回 HTML 挑战页，保持 `enabled: true` 观察
- **cnBeta**（2026-08-13 修复）：`.tw` 镜像 TLS 证书链缺中间证书，GH Actions 下 SSL 校验失败 → 该源配置 `insecure_tls: true` 单源豁免（见 [config/sources.yaml](config/sources.yaml)）

---

## 六、项目结构

```
ai-source/
├── README.md               # 本文档
├── HANDOFF.md              # 设计文档与架构决策（D1-D3）
├── requirements.txt
├── index.html              # 可视化主看板
├── health.html             # 独立源健康页
├── config/sources.yaml     # 信源注册表
├── scripts/                # 采集 pipeline 代码
│   ├── collect.py
│   ├── fetchers/{base,rss}.py
│   ├── normalize.py / dedupe.py / score.py / health.py
├── data/                   # 产物（git 版本化，自动提交）
│   ├── latest-24h.json / archive.json / source-status.json / batches.json
├── .github/workflows/collect.yml   # 采集 + Pages 部署（二合一）
└── tests/test_collect.py
```

---

## 不在范围

- 微信公众号覆盖（用官方 RSS 媒体替代）
- 完整故事线合并（只去重，预留 hook）
- 付费源 X/TikHub（梯级 6，按预算门控后续扩展）
- 下游交付格式锁定（实现时按实际数据形态定）
