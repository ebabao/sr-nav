# 行业轮动增强 · 每日自动同步看板

参考 [ebabao/cta-nav](https://github.com/ebabao/cta-nav) 的「静态页 + 同源 JSON 接口」架构，
把 v1.0「行业轮动增强」（风格自适应动量轮动 + 回撤断路器）接入一个**每日自动抓数、自动同步、自动部署**的看板。

> 核心保证：**策略模型接口（data/*.json）与看板页面（index.html）永远同源**——
> 页面零外部依赖、不含硬编码数据，只 fetch `data/` 接口；模型跑完写入 `data/` 后刷新即生效，页面无需重建。

---

## 一、架构

```
strategy/  （策略模型工程，复用既有脚本，不重写）
  data/raw/*.csv             ← fetch_data.py（每日抓 7 宽基 + 中证800 + 国债ETF）
  output5/v1/*.csv           ← release_v1.py（v1.0 回测回放，end=最新交易日）
         │
         │  scripts/feed.py  唯一的转换器
         ▼
data/  （对外发布的同源接口，静态页直接 fetch）
  meta.json / nav.json / signal.json / holdings.json / attribution.json / audit.json / fetch_report.json
         │
         │  fetch(..., {cache:"no-store"})
         ▼
index.html （静态看板：区间切换 / 中证800基准 / 月度热力 / 年度归因 / 当前持仓 / 策略说明）
```

## 二、目录说明

| 路径 | 作用 |
|---|---|
| `index.html` | 静态看板（内联 ECharts、防 CDN 依赖、fetch 同源接口、区间/导航/刷新交互） |
| `data/*.json` | 同源策略数据接口（由 `feed.py` 生成） |
| `scripts/fetch_data.py` | **每日抓数**：按验证过的官方源抓最新收盘，重试上限 3、失败跳过沿用上一版 |
| `scripts/feed.py` | 模型输出 → 接口 的唯一转换器，数值全部真实重算 |
| `scripts/sync_daily.py` | 每日同步 7 步编排（快照/抓数/校验/回放/接口/幂等/审计） |
| `scripts/check_freshness.py` | 停更巡检与一行中文汇报，可下发 `workflow_dispatch` 重启 |
| `scripts/make_board.py` | 生成本地 `index.html`（离线构建用，线上不执行） |
| `strategy/` | 完整策略模型工程（代码 + 行情快照 + v1 结果快照），仓库自包含可离线回退 |
| `.github/workflows/` | `daily_sync.yml` / `watchdog.yml` / `deploy_pages.yml` |
| `requirements.txt` | 同步链路依赖 |

## 三、数据源与口径（均已实测与历史精确一致）

| 数据 | 数据源 | 代码 | 口径 |
|---|---|---|---|
| 沪深300 / 中证500 / 中证1000 | 中证指数官网 | H00300 / H00905 / H00852 | 全收益 |
| 科创50 / A500 / 中证800 | 中证指数官网 | 000688 / 000510 / 000906 | 价格指数（中证800仅基准） |
| 价值100 / 成长100 | 国证指数（akshare `index_hist_cni`） | 480081 / 480080 | 全收益 |
| 国债ETF 511010 | 新浪（akshare `fund_etf_hist_sina`） | sh511010 | ETF 收盘 |

实测校验：抓数脚本在 2026-11-18 收盘与本地历史逐项一致（如国债ETF 141.344、价值100 8290.7502），
并成功追加 2026-11-19、11-20 两日真实数据。

## 四、每日自动同步（daily_sync.yml，每日 06:00 北京时间 + 手动触发）

| 步骤 | 动作 | 约束 |
|---|---|---|
| 1/7 | 依赖与数据快照检查 | 缺源数据/脚本即终止（无回退基线不硬跑） |
| 2/7 | `fetch_data.py` 抓最新行情 | 整体重试上限 3；单品种失败 → 跳过并沿用上一版，不插值、不编造 |
| 3/7 | 数据质量校验 | 行数 ≥200、缺失率 ≤5%，否则回退 |
| 4/7 | `release_v1.py` 回放（子进程） | `end=最新交易日`，超时上限 1200s |
| 5/7 | `feed.py` 生成 `data/` 接口 | 注入 run_id / 指纹 / 同步状态 |
| 6/7 | 幂等判定 | 抓数 `added=0`（无新交易日）→ skipped，**接口字节不变**，仅更新 last_sync |
| 7/7 | 写 `audit.json` | 保留最近 60 条 |

**失败回退**：任一步失败 → 恢复数据快照 → 用上一版结果重放接口，`sync.fallback=true`、审计 `status=fallback`，如实披露。

**本地验证记录**：`--dry-run` / `snapshot` / `live`（含真实抓数追加 11-19、11-20）/ 幂等 skipped / 失败回退，五条路径全部实跑通过。

## 五、停更巡检与自动部署

- **watchdog.yml**（每 4 小时）：检查 `meta.sync.last_sync`，**超 26 小时无新同步判定停摆**，自动 `workflow_dispatch` 重启，一行中文汇报写入 Actions 摘要。
- **deploy_pages.yml**：只发布 `index.html` + `data/`（不发布策略源码与行情）。由 daily_sync 在提交变更后显式 `workflow_dispatch` 触发，绕开「GITHUB_TOKEN 的 push 不触发其它工作流」限制。

## 六、首次上线（推送前请确认仓库名）

```bash
# 1. 建公开仓库（示例名，实际以确认为准）
gh repo create ebabao/industry-rotation-nav --public --source=. --remote=origin --push

# 2. 启用 GitHub Pages：Settings → Pages → Source = GitHub Actions

# 3. 首次触发一次同步与部署
gh workflow run daily_sync.yml -f mode=live
```

上线后访问：`https://ebabao.github.io/industry-rotation-nav/`

---

> **免责声明**：本工程为量化策略研究，不构成投资建议。回测/模拟基于公开指数与 ETF 历史数据且含事后回溯区间，
> 历史表现不代表未来收益。投资有风险，决策需谨慎。
