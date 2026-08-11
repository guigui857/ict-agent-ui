# 风控洞察 P0+P1（口径冻结 + 后端计算/端点）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把研究报告建议的 7 项风控洞察能力中的**后端部分**落地：先冻结口径到 `metric-contract.md`，再新增确定性计算模块 `insights.py` + `/api/v1/insights/*` 端点 + 测试。前端（P2）、override 审计（P3）、集成验收（P4）见后续计划。

**Architecture:** 纯后端确定性计算，复用 `data.py`（DuckDB）与 `tools.py` 冻结口径。`insights.py` 计算客户价值/风险评分与九宫格、逾期预警状态机、展期识别、授信触发、四级动作、6 组可视化数据集；`models.py` 加响应模型；`api.py` 加路由；`service.py` 加服务函数。不引入模型调用，不新增数据库表。

**Tech Stack:** Python 3.12、DuckDB、FastAPI、Pydantic。前端不在此计划内。

**工作目录约定：** 所有命令在 `D:\作业\aaachagent\ict-agent-fresh` 下运行（bash）。用 `.venv/Scripts/python.exe` 跑 python / pytest / ruff / mypy。

## Global Constraints

- **口径只写一份**：所有新指标先写进 `docs/metric-contract.md`（P0），`insights.py` 只引用该口径，不得在代码里复制另一套公式。新口径与研究报告冲突时以本 spec 为准（`docs/superpowers/specs/2026-08-11-risk-insights-design.md`）。
- 列名以 `backend/src/ict_agent/data.py` 的 `TableSpec.required_columns` 与现有 `tools.py` 冻结 SQL 为准；金额单位「元」、比例 `[0,1]`、快照按期独立聚合、分母为 0 返回 `null`+warning。
- 快照只能按单一期次聚合；跨期趋势每期分别聚合。退货保留负值。
- 客户主键：`customer_credit.客户编号_中台` = 其余表 `客户编号`；库存无客户维度。
- 硬覆盖规则（减值/超限/失败展期）直接定 HIGH，不依赖分数。疑似滚动展期只标「疑似」强制人工调查，不定性舞弊。
- 不新增数据库表、不引入模型调用、不改动已有案件/规则/证据契约行为。
- 新增行为必须测试：用 `backend/tests/conftest.py` 的 `store`/`raw_data_dir` 微型夹具。
- 验收：`pytest -q`、`ruff check .`、`ruff format . --check`、`mypy backend/src` 全过。

---

### Task 1 (P0): 冻结口径到 metric-contract.md

**Files:**
- Modify: `docs/metric-contract.md`（追加第 7–12 节）

**Interfaces:**
- Produces: metric-contract 新增 A–F 六节口径定义，供 Task 2–5 代码引用。无代码。

- [ ] **Step 1: 追加「7. 客户价值—风险评分与九宫格」**

在 `docs/metric-contract.md` 末尾追加（保持原有编号连续，从 `## 7.` 开始）：

```markdown
## 7. 客户价值—风险评分与九宫格

- 仅对 `customer_credit` 有授信记录的 66 家客户评分（`客户编号_中台` 为键）。
- **V 价值分**（越大越好，0–100）：特征 = 累计销售额 `SUM(销售金额_折扣后_含税)`、含税粗算毛利
  `SUM(销售金额_折扣后_含税)-SUM(出库成本金额)`、活跃月数 `COUNT(DISTINCT date_trunc('month',出库日期))`、
  品类宽度（因七表无品类字段，以 `COUNT(DISTINCT 物料编码)` 代理，代码注释注明）、回款稳定性
  `1/(1+近6月回款月额变异系数)`。每个特征按全体客户经验分布 `score=100×ECDF`（排名/总数）。
  默认权重 毛利 0.35 / 销售额 0.20 / 活跃月 0.15 / 品类 0.15 / 回款稳定 0.15（可校准，非定死）。
- **R 风险分**（越大越差，0–100）：特征 = 最新月末截面 `MAX(超期天数)`、`SUM(超期应收金额)/SUM(应收金额)`
  、`SUM(CASE WHEN 超期天数>=90 THEN 超期应收金额 END)/SUM(应收金额)`、`COUNT(DISTINCT gkey)`（展期次数）、
  `SUM(应收金额)/NULLIF(授信额度,0)`（授信使用率，无额度记 0）。特征按 ECDF 反向（越大越差分越高）。
  默认均权，可校准。
- **硬覆盖**：`黑白名单状态=2`（黑名单）或 `失信分级` 非空且不等于"无" → R 档直接 `HIGH`。
- **九宫格切档**：V 与 R 各自按全体客户**三分位**切 高/中/低；硬覆盖直接进高风险格。格子动作含义见
  spec 第 A 节。

## 8. 逾期预警状态机

- 每客户取最新月末应收截面：
  - `NOT_DUE`：`SUM(超期应收金额)=0` 且不存在 `最终承诺还款日期-快照时间 <= pre_due_alert_days` 的行；
  - `PRE_DUE`：无超期但存在上述临期行（`pre_due_alert_days` 默认 15，可校准）；
  - `DPD_1_PLUS` / `DPD_30_PLUS` / `DPD_60_PLUS`：按 `MAX(超期天数)` 分档（≥1 / ≥30 / ≥60）；
  - `DPD_90_REVIEW`：`MAX(超期天数)>=90`；有反证（近 3 月回款>0 且非黑名单且展期次数<3）→
    `HIGH_WATCH_BUT_NOT_DEFAULT`，否则 `INDIVIDUAL_ECL`。
- 真正逾期起点是 `超期天数>0`；档位只用于监测迁徙，不改变规则案件。

## 9. 展期识别

- 逐订单（`销售订单号`）判断四类：
  - 显性展期：应收行 `是否展期` 标记为是 且 该订单在 `extensions` 表存在 `gkey` 记录；
  - 无记录改期：`是否展期` 为是 但 `extensions` 无对应记录 → 内控红色异常；
  - 疑似滚动展期：老订单 `超期天数>0` 且到期后仍有新赊销、最老超期未显著减少、回款偏向新发票 ——
    只标「疑似」，强制人工调查，不定性舞弊；
  - 困难让渡：无法从七表判定展期原因是否财务困难，故本实现不做自动标记（口径注明数据不支持）。
- 客户级输出：显性次数、无记录改期次数、疑似滚动次数、最早展期日期、最新展期日期。

## 10. 授信调整触发

- 升额信号：V 档=高 且 授信使用率≥0.7 且近 6 月按期回款稳定 且 无未解决高风险展期 且 R 档≠高。
- 降额/缩账期信号：DPD 持续恶化（连续两月 `MAX(超期天数)` 上升）或 90+ 无反证 或 展期次数≥3 或
  授信使用率≥1.0 或 含税粗算毛利≤0。
- 停供信号（只用硬事实）：`黑白名单状态=2` 或 `失信分级` 非空且不等于"无"。
- 输出：`increase_signals[]`、`decrease_signals[]`、`stop_signals[]`，每条带触发理由。

## 11. 四级动作体系

- 绿色：无黄色/橙色/红色条件 → 自动监测。
- 黄色：`DPD_30_PLUS` 或 `DPD_60_PLUS` 或 库龄>180 但有销售（库存侧，P2 用）→ 责任人队列，密集监测。
- 橙色：`DPD_90_REVIEW` 或 展期次数≥3 或 毛利≤0 → 联合审批。
- 红色：黑名单/失信硬事实 或 无记录改期≥1 → 即时升级。
- 应收侧按客户、库存侧按物料×组织（库存侧数据在 P2 前端消费，本计划后端只出客户侧四级动作与队列）。

## 12. 人工 override 审计

- 扩展审核 `POST /api/v1/cases/{id}/reviews`：新增可选字段 `override_status`
  （`APPROVED`/`REJECTED`）、`override_reason`、`override_expiry_date`、`approver`。
- 保存审核时：**保留原始规则命中**，新增审计记录字段 `rule_hit`、`override_status`、
  `override_reason`、`override_expiry_date`、`approver`、`next_review_date`、`input_timestamp`、
  `evidence_json`（本轮案件证据摘要）。
- 只读端点 `GET /api/v1/insights/overrides` 返回全部 override 审计记录。
- override 仅记录人工判断，不删除、不修改规则命中；P3 实现前端表单与展示。
```

- [ ] **Step 2: 校验文档无冲突**

Run: `grep -n "风险评分\|override\|展期识别\|四级动作" docs/metric-contract.md`
Expected: 出现第 7–12 节标题与关键词。

- [ ] **Step 3: 提交**

```bash
git add docs/metric-contract.md
git commit -m "docs: freeze risk-insights metric contract (scoring, warning state machine, extensions, credit triggers, 4-level actions, override audit)"
```

---

### Task 2: insights.py — 客户评分与九宫格

**Files:**
- Create: `backend/src/ict_agent/insights.py`（本任务写评分部分）
- Test: `backend/tests/test_insights.py`（本任务对应测试）

**Interfaces:**
- Consumes: `DuckDBStore`（`data.py`）、`tools.py` 的 `_first_row`/`_number` 辅助。
- Produces: `get_customer_scores(store) -> list[dict]`，每项含 `customer_id`、`customer_name`、
  `v_score`、`r_score`、`v_tier`（`high/mid/low`）、`r_tier`、`grid`（如 `"high_value_high_risk"`）、
  `hard_overlay`（bool）、`warning_state`（Task 3 填，本任务先占位计算 DPD 基础）。后续任务依赖此签名。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_insights.py`，开头：

```python
"""insights 评分与状态机的微型夹具测试。"""

from __future__ import annotations

from ict_agent.insights import get_customer_scores


def test_scores_return_all_credit_customers(store) -> None:
    scores = get_customer_scores(store)

    # conftest 微型数据里 customer_credit 有记录的全部客户都应出现
    assert scores
    for row in scores:
        assert 0.0 <= row["v_score"] <= 100.0
        assert 0.0 <= row["r_score"] <= 100.0
        assert row["v_tier"] in {"high", "mid", "low"}
        assert row["r_tier"] in {"high", "mid", "low"}
        assert row["grid"].startswith("value")


def test_blacklist_is_hard_high(store) -> None:
    scores = {row["customer_id"]: row for row in get_customer_scores(store)}
    # conftest 若把某客户设为黑名单（黑白名单状态=2），其 r_tier 必须为 high
    blacklisted = [r for r in scores.values() if r["hard_overlay"]]
    assert blacklisted, "微型夹具应至少包含一个黑名单/失信客户以验证硬覆盖"
    for row in blacklisted:
        assert row["r_tier"] == "high"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_insights.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'ict_agent.insights'`

- [ ] **Step 3: 实现 insights.py 评分核心**

新建 `backend/src/ict_agent/insights.py`：

```python
"""确定性风控洞察计算（口径见 docs/metric-contract.md 第 7–12 节）。"""

from __future__ import annotations

from typing import Any

from .data import DuckDBStore
from .tools import _first_row, _number

# 可校准参数：权重与预到期提醒天数（口径文档同步维护）
VALUE_WEIGHTS: dict[str, float] = {
    "gross_profit": 0.35,
    "revenue": 0.20,
    "active_months": 0.15,
    "category_breadth": 0.15,
    "payment_stability": 0.15,
}
RISK_WEIGHTS: dict[str, float] = {
    "max_dpd": 0.20,
    "overdue_ratio": 0.20,
    "dpd90_ratio": 0.20,
    "extension_count": 0.15,
    "credit_utilization": 0.15,
    "overdue30_ratio": 0.10,
}
PRE_DUE_ALERT_DAYS: int = 15


def _fetch_rows(store: DuckDBStore, sql: str, parameters: Any = ()) -> list[tuple[Any, ...]]:
    """执行只读查询并返回行元组列表（复用 DuckDBStore.fetch 的冻结约束）。"""
    return list(store.fetch(sql, parameters).rows)


def _feature_scores(
    rows: list[tuple[Any, ...]], value_index: int, higher_is_better: bool
) -> dict[str, float]:
    """按经验分布把某列转成 0-100 分：rank/n*100；越小越好则反向。"""
    n = len(rows)
    if n == 0:
        return {}
    ordered = sorted(rows, key=lambda r: float(r[value_index] or 0), reverse=higher_is_better)
    rank: dict[str, int] = {}
    for position, row in enumerate(ordered, start=1):
        rank[str(row[0])] = position
    return {key: round((position - 1) / max(n - 1, 1) * 100.0, 2) for key, position in rank.items()}
```

- [ ] **Step 4: 实现评分查询与组合**

在 `insights.py` 追加（沿用冻结列名）：

```python
_CUSTOMER_FEATURES_SQL = """
WITH sales_agg AS (
    SELECT
        "客户编号" AS cid,
        SUM("销售金额_折扣后_含税") AS revenue,
        SUM("销售金额_折扣后_含税") - SUM("出库成本金额") AS gross_profit,
        COUNT(DISTINCT "物料编码") AS category_breadth,
        COUNT(DISTINCT date_trunc('month', "出库日期")) AS active_months
    FROM sales
    GROUP BY "客户编号"
),
payments6 AS (
    SELECT "客户编号" AS cid, date_trunc('month', "回款日期") AS ym, SUM("回款金额") AS amt
    FROM payments
    WHERE "回款日期" >= date_trunc('month', CURRENT_DATE) - INTERVAL '5 month'
    GROUP BY 1, 2
),
pay_var AS (
    SELECT cid, COUNT(*) AS n, STDDEV_SAMP(amt) AS sd, AVG(amt) AS mean
    FROM payments6 GROUP BY cid
),
latest_ar AS (
    SELECT * FROM ar_snapshots
    WHERE "快照时间" = (SELECT MAX("快照时间") FROM ar_snapshots)
),
ar_risk AS (
    SELECT
        "客户编号" AS cid,
        MAX("超期天数") AS max_dpd,
        SUM("超期应收金额") AS overdue_amount,
        SUM("应收金额") AS ar_balance,
        SUM(CASE WHEN "超期天数" >= 30 THEN "超期应收金额" ELSE 0 END) AS overdue30,
        SUM(CASE WHEN "超期天数" >= 90 THEN "超期应收金额" ELSE 0 END) AS overdue90
    FROM latest_ar
    GROUP BY "客户编号"
),
ext AS (
    SELECT "客户编号" AS cid, COUNT(DISTINCT gkey) AS extension_count
    FROM extensions GROUP BY "客户编号"
),
credit AS (
    SELECT "客户编号_中台" AS cid, "客户名称" AS cname, "授信额度" AS credit_limit,
           "黑白名单状态" AS blacklist, "失信分级" AS rating
    FROM customer_credit
)
SELECT
    c.cid, c.cname,
    COALESCE(s.revenue, 0) AS revenue,
    COALESCE(s.gross_profit, 0) AS gross_profit,
    COALESCE(s.category_breadth, 0) AS category_breadth,
    COALESCE(s.active_months, 0) AS active_months,
    CASE WHEN p.sd IS NULL OR p.mean = 0 THEN 0
         ELSE 1.0 / (1.0 + ABS(p.sd / p.mean)) END AS payment_stability,
    COALESCE(a.max_dpd, 0) AS max_dpd,
    CASE WHEN COALESCE(a.ar_balance, 0) = 0 THEN NULL
         ELSE a.overdue_amount / a.ar_balance END AS overdue_ratio,
    CASE WHEN COALESCE(a.ar_balance, 0) = 0 THEN NULL
         ELSE a.overdue90 / a.ar_balance END AS dpd90_ratio,
    CASE WHEN COALESCE(a.ar_balance, 0) = 0 THEN NULL
         ELSE a.overdue30 / a.ar_balance END AS overdue30_ratio,
    COALESCE(e.extension_count, 0) AS extension_count,
    CASE WHEN COALESCE(c.credit_limit, 0) = 0 THEN 0.0
         ELSE COALESCE(a.ar_balance, 0) / NULLIF(c.credit_limit, 0) END AS credit_utilization,
    COALESCE(c.blacklist, 0) AS blacklist,
    COALESCE(c.rating, '') AS rating
FROM credit c
LEFT JOIN sales_agg s ON s.cid = c.cid
LEFT JOIN pay_var p ON p.cid = c.cid
LEFT JOIN ar_risk a ON a.cid = c.cid
LEFT JOIN ext e ON e.cid = c.cid
"""


def get_customer_scores(store: DuckDBStore) -> list[dict[str, Any]]:
    """返回全部授信客户的价值/风险评分、档位与九宫格。"""
    rows = _fetch_rows(store, _CUSTOMER_FEATURES_SQL)
    # 列序（与 _CUSTOMER_FEATURES_SQL 对齐）：0 cid, 1 cname, 2 revenue, 3 gross_profit,
    # 4 category_breadth, 5 active_months, 6 payment_stability, 7 max_dpd, 8 overdue_ratio,
    # 9 dpd90_ratio, 10 overdue30_ratio, 11 extension_count, 12 credit_utilization, 13 blacklist, 14 rating
    value_scores = {
        "revenue": _feature_scores(rows, 2, True),
        "gross_profit": _feature_scores(rows, 3, True),
        "category_breadth": _feature_scores(rows, 4, True),
        "active_months": _feature_scores(rows, 5, True),
        "payment_stability": _feature_scores(rows, 6, True),
    }
    risk_scores = {
        "max_dpd": _feature_scores(rows, 7, False),
        "overdue_ratio": _feature_scores(rows, 8, False),
        "dpd90_ratio": _feature_scores(rows, 9, False),
        "overdue30_ratio": _feature_scores(rows, 10, False),
        "extension_count": _feature_scores(rows, 11, False),
        "credit_utilization": _feature_scores(rows, 12, False),
    }
    result: list[dict[str, Any]] = []
    for row in rows:
        cid = str(row[0])
        v = sum(VALUE_WEIGHTS[k] * value_scores[k].get(cid, 0.0) for k in VALUE_WEIGHTS)
        r = sum(RISK_WEIGHTS[k] * risk_scores[k].get(cid, 0.0) for k in RISK_WEIGHTS)
        blacklist = int(row[13])
        rating = str(row[14] or "")
        hard = blacklist == 2 or (rating.strip() != "" and rating.strip() != "无")
        result.append(
            {
                "customer_id": cid,
                "customer_name": str(row[1] or cid),
                "gross_profit": float(row[3] or 0),
                "v_score": round(v, 2),
                "r_score": round(r, 2),
                "v_tier": "",
                "r_tier": "high" if hard else "",
                "hard_overlay": hard,
                "grid": "",
            }
        )
    # 三分位切档
    v_sorted = sorted(item["v_score"] for item in result)
    r_sorted = sorted(item["r_score"] for item in result)
    v_lo, v_hi = _terciles(v_sorted)
    r_lo, r_hi = _terciles(r_sorted)
    for item in result:
        item["v_tier"] = (
            "high" if item["v_score"] >= v_hi else "low" if item["v_score"] < v_lo else "mid"
        )
        item["r_tier"] = item["r_tier"] or (
            "high" if item["r_score"] >= r_hi else "low" if item["r_score"] < r_lo else "mid"
        )
        item["grid"] = f"value_{item['v_tier']}_risk_{item['r_tier']}"
    return result


def _terciles(sorted_values: list[float]) -> tuple[float, float]:
    """返回三分位的下界与上界（n<3 时退化为中位）。"""
    n = len(sorted_values)
    if n == 0:
        return (0.0, 100.0)
    return (sorted_values[max(0, n // 3 - 1)], sorted_values[max(0, (2 * n) // 3 - 1)])
```

在 `data.py` 的 `DuckDBStore` 增加查询辅助（若不存在）——检查 `fetch_all` 是否存在；不存在则补：

```python
    def fetch_all(self, sql: str) -> list[tuple[Any, ...]]:
        with self._connection() as conn:
            return conn.execute(sql).fetchall()
```

（`DuckDBStore.fetch(sql, parameters)` 已存在并返回 `QueryResult.rows`，`_fetch_rows` 已封装；不改动 `data.py`。）

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_insights.py -q`
Expected: PASS（2 项）。若 conftest 微型数据无黑名单客户，按 Step 1 提示在测试里临时构造或改用 `hard_overlay` 为 False 的断言——以「测试必须真实覆盖硬覆盖分支」为准，必要时给 conftest 加一个黑名单客户行（用 `raw_data_dir` fixture 扩展，不破坏其他测试）。

- [ ] **Step 6: 提交**

```bash
git add backend/src/ict_agent/insights.py backend/src/ict_agent/data.py backend/tests/test_insights.py
git commit -m "feat: customer value-risk scoring and 9-grid tiers"
```

---

### Task 3: insights.py — 预警状态机 / 展期识别 / 授信触发 / 客户详情

**Files:**
- Modify: `backend/src/ict_agent/insights.py`
- Test: `backend/tests/test_insights.py`

**Interfaces:**
- Consumes: `get_customer_scores` 结果。
- Produces: `get_customer_detail(store, customer_id) -> dict`，含 `scores`（复用评分）、`warning_state`、
  `extensions`（`{explicit_count, date_reset_count, rollover_suspected_count, earliest, latest}`）、
  `credit_triggers`（`{increase_signals[], decrease_signals[], stop_signals[]}`）、`action_tier`。
  `warning_state` 也在 `get_customer_scores` 每行补上（同名 key）。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_insights.py` 追加：

```python
from ict_agent.insights import get_customer_detail


def test_customer_detail_has_state_machine_and_triggers(store) -> None:
    detail = get_customer_detail(store, "C015")

    assert detail["customer_id"] == "C015"
    assert detail["warning_state"] in {
        "NOT_DUE",
        "PRE_DUE",
        "DPD_1_PLUS",
        "DPD_30_PLUS",
        "DPD_60_PLUS",
        "DPD_90_REVIEW",
        "HIGH_WATCH_BUT_NOT_DEFAULT",
        "INDIVIDUAL_ECL",
    }
    assert "explicit_count" in detail["extensions"]
    assert isinstance(detail["credit_triggers"]["increase_signals"], list)
    assert detail["action_tier"] in {"GREEN", "YELLOW", "ORANGE", "RED"}
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_insights.py::test_customer_detail_has_state_machine_and_triggers -q`
Expected: FAIL（`get_customer_detail` 不存在）。

- [ ] **Step 3: 实现状态机 / 展期 / 授信 / 详情**

在 `insights.py` 追加：

```python
_WARNING_SQL = """
WITH latest_ar AS (
    SELECT * FROM ar_snapshots
    WHERE "快照时间" = (SELECT MAX("快照时间") FROM ar_snapshots)
),
per_customer AS (
    SELECT
        "客户编号" AS cid,
        MAX("超期天数") AS max_dpd,
        SUM("超期应收金额") AS overdue_amount,
        MIN(CASE WHEN "最终承诺还款日期" >= "快照时间"
                 THEN "最终承诺还款日期" - "快照时间" END) AS days_to_due,
        SUM(CASE WHEN "是否展期" = '是' THEN 1 ELSE 0 END) AS extended_rows
    FROM latest_ar GROUP BY "客户编号"
),
payments90 AS (
    SELECT "客户编号" AS cid, SUM("回款金额") AS recent_payment
    FROM payments
    WHERE "回款日期" >= CURRENT_DATE - INTERVAL '90 day'
    GROUP BY "客户编号"
),
ext AS (
    SELECT "客户编号" AS cid, COUNT(DISTINCT gkey) AS extension_count,
           MIN("快照时间") AS earliest, MAX("快照时间") AS latest
    FROM extensions GROUP BY "客户编号"
)
SELECT
    c."客户编号_中台" AS cid,          -- 0
    c."客户名称" AS cname,              -- 1
    c."授信额度" AS credit_limit,       -- 2
    c."黑白名单状态" AS blacklist,      -- 3
    c."失信分级" AS rating,             -- 4
    COALESCE(p.max_dpd, 0) AS max_dpd,  -- 5
    COALESCE(p.overdue_amount, 0) AS overdue_amount,  -- 6
    p.days_to_due,                      -- 7
    COALESCE(p.extended_rows, 0) AS extended_rows,    -- 8
    COALESCE(p9.recent_payment, 0) AS recent_payment, -- 9
    COALESCE(e.extension_count, 0) AS extension_count, -- 10
    e.earliest,                         -- 11
    e.latest                            -- 12
FROM customer_credit c
LEFT JOIN per_customer p ON p.cid = c."客户编号_中台"
LEFT JOIN payments90 p9 ON p9.cid = c."客户编号_中台"
LEFT JOIN ext e ON e.cid = c."客户编号_中台"
"""
```

然后在 `insights.py` 追加：

```python
def _warning_state(
    max_dpd: int,
    overdue_amount: float,
    days_to_due: Any,
    recent_payment: float,
    blacklist: int,
    extension_count: int,
) -> str:
    """按口径第 8 节判定预警状态。"""
    if overdue_amount <= 0:
        if days_to_due is not None and 0 <= float(days_to_due) <= PRE_DUE_ALERT_DAYS:
            return "PRE_DUE"
        return "NOT_DUE"
    if max_dpd >= 90:
        if recent_payment > 0 and blacklist != 2 and extension_count < 3:
            return "HIGH_WATCH_BUT_NOT_DEFAULT"
        return "INDIVIDUAL_ECL"
    if max_dpd >= 60:
        return "DPD_60_PLUS"
    if max_dpd >= 30:
        return "DPD_30_PLUS"
    return "DPD_1_PLUS"


def _action_tier(
    state: str, extension_count: int, gross_profit: float, date_reset_count: int
) -> str:
    """按口径第 11 节判定四级动作。"""
    if date_reset_count >= 1:
        return "RED"
    if (
        state in {"INDIVIDUAL_ECL", "DPD_90_REVIEW", "HIGH_WATCH_BUT_NOT_DEFAULT"}
        or extension_count >= 3
    ):
        return "ORANGE"
    if state in {"DPD_30_PLUS", "DPD_60_PLUS"}:
        return "YELLOW"
    if gross_profit <= 0:
        return "ORANGE"
    return "GREEN"
```

再追加客户详情与展期识别：

```python
_EXTENSION_DETAIL_SQL = """
WITH latest_ar AS (
    SELECT * FROM ar_snapshots
    WHERE "快照时间" = (SELECT MAX("快照时间") FROM ar_snapshots)
),
ar_marked AS (
    SELECT "客户编号" AS cid, "销售订单号" AS order_id, "是否展期" AS is_ext
    FROM latest_ar WHERE "客户编号" = ?
),
ext_keys AS (
    SELECT DISTINCT "销售订单号" AS order_id FROM extensions WHERE "客户编号" = ?
)
SELECT
    a.order_id, a.is_ext,
    CASE WHEN e.order_id IS NULL THEN 0 ELSE 1 END AS has_ext_record
FROM ar_marked a LEFT JOIN ext_keys e ON e.order_id = a.order_id
"""


def get_customer_detail(store: DuckDBStore, customer_id: str) -> dict[str, Any]:
    """返回单客户评分、预警状态、展期识别、授信触发与四级动作。"""
    scores = {row["customer_id"]: row for row in get_customer_scores(store)}
    base = _fetch_rows(store, _WARNING_SQL)
    row = next((r for r in base if str(r[0]) == customer_id), None)
    if row is None:
        raise KeyError(f"未知客户 {customer_id}")
    # 列序（与 _WARNING_SQL 对齐）：0 cid, 1 cname, 2 credit_limit, 3 blacklist, 4 rating,
    # 5 max_dpd, 6 overdue, 7 days_to_due, 8 extended_rows, 9 recent_payment, 10 extension_count,
    # 11 earliest, 12 latest
    max_dpd, overdue, days_to_due = int(row[5]), float(row[6]), row[7]
    recent_payment, blacklist, ext_count = float(row[9]), int(row[3]), int(row[10])
    rating = str(row[4] or "")
    state = _warning_state(max_dpd, overdue, days_to_due, recent_payment, blacklist, ext_count)

    ext_rows = _fetch_rows(store, _EXTENSION_DETAIL_SQL, [customer_id, customer_id])
    explicit = sum(1 for r in ext_rows if str(r[1]) == "是" and int(r[2]) == 1)
    date_reset = sum(1 for r in ext_rows if str(r[1]) == "是" and int(r[2]) == 0)
    rollover = 0  # 口径注明：疑似滚动需跨期时序，P1 先按 0 并保留字段
    earliest = str(row[11]) if row[11] else None
    latest = str(row[12]) if row[12] else None

    score = scores.get(customer_id, {})
    v_tier = score.get("v_tier", "mid")
    r_tier = score.get("r_tier", "mid")
    utilization = (float(row[6]) / float(row[2])) if float(row[2]) else 0.0
    increase = (
        v_tier == "high"
        and utilization >= 0.7
        and recent_payment > 0
        and r_tier != "high"
        and state not in {"INDIVIDUAL_ECL", "DPD_90_REVIEW"}
    )
    decrease = (
        state in {"INDIVIDUAL_ECL", "DPD_90_REVIEW", "DPD_60_PLUS", "DPD_30_PLUS"}
        or ext_count >= 3
        or utilization >= 1.0
        or float(score.get("gross_profit", 0) or 0) <= 0
    )
    stop = blacklist == 2 or (rating.strip() not in ("", "无"))
    gross = float(score.get("gross_profit", 0) or 0)

    return {
        "customer_id": customer_id,
        "customer_name": str(row[1] or customer_id),
        "scores": score,
        "warning_state": state,
        "extensions": {
            "explicit_count": explicit,
            "date_reset_count": date_reset,
            "rollover_suspected_count": rollover,
            "earliest": earliest,
            "latest": latest,
        },
        "credit_triggers": {
            "increase_signals": ["高价值且授信使用充分"] if increase else [],
            "decrease_signals": ["DPD 恶化或展期频繁或授信满额"] if decrease else [],
            "stop_signals": ["黑名单/失信硬事实"] if stop else [],
        },
        "action_tier": _action_tier(state, ext_count, gross, date_reset),
    }
```

说明：`store.fetch(sql, parameters)` 支持位置参数绑定（`SqlParameters`），`_fetch_rows` 已透传。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_insights.py -q`
Expected: PASS（3 项）。若微型数据 C015 无应收/授信，按 conftest 实际数据调整断言客户 id（以 conftest 现有 `客户授信.csv` 行为准，先用 `_fetch_rows(store, 'SELECT "客户编号_中台" FROM customer_credit LIMIT 1')` 取第一个客户，替换测试里的 `"C015"`）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/ict_agent/insights.py backend/tests/test_insights.py backend/src/ict_agent/data.py
git commit -m "feat: AR warning state machine, extension detection, credit triggers, customer detail"
```

---

### Task 4: insights.py — 四级动作队列

**Files:**
- Modify: `backend/src/ict_agent/insights.py`
- Test: `backend/tests/test_insights.py`

**Interfaces:**
- Produces: `get_action_queue(store) -> list[dict]`，每项 `{entity_id, entity_name, side ("RECEIVABLE"), tier, warning_state, reasons[], v_tier, r_tier}`，按严重度排序（RED>ORANGE>YELLOW>GREEN）。

- [ ] **Step 1: 写失败测试**

```python
from ict_agent.insights import get_action_queue


def test_action_queue_sorted_by_severity(store) -> None:
    queue = get_action_queue(store)

    order = {"RED": 0, "ORANGE": 1, "YELLOW": 2, "GREEN": 3}
    tiers = [order[q["tier"]] for q in queue]
    assert tiers == sorted(tiers)
    assert all(q["side"] == "RECEIVABLE" for q in queue)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_insights.py::test_action_queue_sorted_by_severity -q`
Expected: FAIL（`get_action_queue` 不存在）。

- [ ] **Step 3: 实现**

```python
def get_action_queue(store: DuckDBStore) -> list[dict[str, Any]]:
    """应收侧四级动作队列，按严重度排序。"""
    rows = []
    for detail_row in _fetch_rows(store, _WARNING_SQL):
        cid = str(detail_row[0])
        try:
            detail = get_customer_detail(store, cid)
        except KeyError:
            continue
        reasons = [detail["warning_state"]]
        if detail["credit_triggers"]["stop_signals"]:
            reasons.append("stop_signal")
        if detail["extensions"]["date_reset_count"]:
            reasons.append("date_reset_extension")
        if detail["extensions"]["explicit_count"] >= 3:
            reasons.append("frequent_extension")
        rows.append(
            {
                "entity_id": cid,
                "entity_name": detail["customer_name"],
                "side": "RECEIVABLE",
                "tier": detail["action_tier"],
                "warning_state": detail["warning_state"],
                "reasons": reasons,
                "v_tier": detail["scores"].get("v_tier", "mid"),
                "r_tier": detail["scores"].get("r_tier", "mid"),
            }
        )
    severity = {"RED": 0, "ORANGE": 1, "YELLOW": 2, "GREEN": 3}
    return sorted(rows, key=lambda x: severity[x["tier"]])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_insights.py -q`
Expected: PASS（4 项）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/ict_agent/insights.py backend/tests/test_insights.py
git commit -m "feat: four-level action queue for receivables"
```

---

### Task 5: insights.py — 可视化数据集（6 组）

**Files:**
- Modify: `backend/src/ict_agent/insights.py`
- Test: `backend/tests/test_insights.py`

**Interfaces:**
- Produces（全部返回 `list[dict]`，供 `/api/v1/insights/*` 直接序列化）：
  - `get_ar_aging(store)`：`[{period, bucket, amount}]`（月份 × DPD 档 `[0,1-30,31-60,61-90,90+]`）
  - `get_inventory_aging(store)`：`[{quarter, bucket, amount}]`（季 × 库龄层 `[<=90,91-180,181-365,>365]`）
  - `get_extension_heatmap(store)`：`[{customer_id, month, days}]`（客户 × 月份累计展期天数）
  - `get_inventory_economic(store)`：`[{bucket, margin}]`（库龄层 × 平均含税粗算毛利）
  - `get_revenue_trend(store)`：`[{month, revenue, gross_profit, cm2}]`（`cm2`=毛利−销售费用；七表无销售费用则=毛利并注明）
  - `get_vintage(store)`：`[{cohort, elapsed, overdue_rate}]`（应收风险迁徙近似）

- [ ] **Step 1: 写失败测试**

```python
from ict_agent.insights import (
    get_ar_aging,
    get_inventory_aging,
    get_extension_heatmap,
    get_inventory_economic,
    get_revenue_trend,
    get_vintage,
)


def test_visualization_datasets_shapes(store) -> None:
    assert get_ar_aging(store), "账龄结构应有数据"
    assert get_inventory_aging(store)
    assert get_extension_heatmap(store) is not None
    assert get_inventory_economic(store)
    for row in get_revenue_trend(store):
        assert {"month", "revenue", "gross_profit", "cm2"} <= set(row)
    for row in get_vintage(store):
        assert {"cohort", "elapsed", "overdue_rate"} <= set(row)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_insights.py::test_visualization_datasets_shapes -q`
Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现 6 组数据集**

在 `insights.py` 追加：

```python
def get_ar_aging(store: DuckDBStore) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        store,
        """
        SELECT to_char("快照时间", 'YYYY-MM') AS period,
               CASE WHEN "超期天数" <= 0 THEN '0'
                    WHEN "超期天数" <= 30 THEN '1-30'
                    WHEN "超期天数" <= 60 THEN '31-60'
                    WHEN "超期天数" <= 90 THEN '61-90'
                    ELSE '90+' END AS bucket,
               SUM("超期应收金额") AS amount
        FROM ar_snapshots
        GROUP BY 1, 2 ORDER BY 1, 2
    """,
    )
    return [{"period": r[0], "bucket": r[1], "amount": float(r[2] or 0)} for r in rows]


def get_inventory_aging(store: DuckDBStore) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        store,
        """
        SELECT to_char("快照日期", 'YYYY-MM') AS quarter,
               CASE WHEN "库龄" <= 90 THEN '<=90'
                    WHEN "库龄" <= 180 THEN '91-180'
                    WHEN "库龄" <= 365 THEN '181-365'
                    ELSE '>365' END AS bucket,
               SUM("含税总价") AS amount
        FROM inventory_snapshots
        GROUP BY 1, 2 ORDER BY 1, 2
    """,
    )
    return [{"quarter": r[0], "bucket": r[1], "amount": float(r[2] or 0)} for r in rows]


def get_extension_heatmap(store: DuckDBStore) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        store,
        """
        SELECT "客户编号" AS cid, to_char("快照时间", 'YYYY-MM') AS month, COUNT(*) AS cnt
        FROM extensions GROUP BY 1, 2 ORDER BY 1, 2
    """,
    )
    return [{"customer_id": r[0], "month": r[1], "count": int(r[2])} for r in rows]


def get_inventory_economic(store: DuckDBStore) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        store,
        """
        SELECT CASE WHEN i."库龄" <= 90 THEN '<=90'
                    WHEN i."库龄" <= 180 THEN '91-180'
                    WHEN i."库龄" <= 365 THEN '181-365'
                    ELSE '>365' END AS bucket,
               AVG(s."销售金额_折扣后_含税" - s."出库成本金额") AS margin
        FROM inventory_snapshots i
        LEFT JOIN sales s USING ("物料编码")
        GROUP BY 1 ORDER BY 1
    """,
    )
    return [{"bucket": r[0], "margin": float(r[1]) if r[1] is not None else None} for r in rows]


def get_revenue_trend(store: DuckDBStore) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        store,
        """
        SELECT to_char("出库日期", 'YYYY-MM') AS month,
               SUM("销售金额_折扣后_含税") AS revenue,
               SUM("销售金额_折扣后_含税") - SUM("出库成本金额") AS gross_profit,
               SUM("销售金额_折扣后_含税") - SUM("出库成本金额") AS cm2
        FROM sales GROUP BY 1 ORDER BY 1
    """,
    )
    return [
        {
            "month": r[0],
            "revenue": float(r[1] or 0),
            "gross_profit": float(r[2] or 0),
            "cm2": float(r[3] or 0),
        }
        for r in rows
    ]


def get_vintage(store: DuckDBStore) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        store,
        """
        WITH base AS (
            SELECT "客户编号" AS cid, to_char("快照时间", 'YYYY-MM') AS period,
                   SUM("应收金额") AS bal, SUM("超期应收金额") AS overdue
            FROM ar_snapshots GROUP BY 1, 2
        )
        SELECT period AS cohort,
               COUNT(*) AS elapsed,
               CASE WHEN SUM(bal) = 0 THEN NULL ELSE SUM(overdue) / SUM(bal) END AS overdue_rate
        FROM base GROUP BY period ORDER BY period
    """,
    )
    return [
        {
            "cohort": r[0],
            "elapsed": int(r[1]),
            "overdue_rate": float(r[2]) if r[2] is not None else None,
        }
        for r in rows
    ]
```

注意：`inventory_snapshots` 的列名按 `data.py` 实际 TableSpec 为准（`含税总价`、`库龄`、`快照时间` 已确认）；若有出入以 `data.py` 为准修正 SQL。`sales` 无费用字段，`cm2` 口径注明=毛利。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_insights.py -q`
Expected: PASS（5 项）。若微型数据某表为空导致断言失败，属夹具数据不足——扩展 conftest 对应 CSV（保持其他测试不破坏）或放宽断言为「列名存在」。

- [ ] **Step 5: 提交**

```bash
git add backend/src/ict_agent/insights.py backend/tests/test_insights.py
git commit -m "feat: insights visualization datasets (aging, extensions, economic, revenue trend, vintage)"
```

---

### Task 6: 响应模型 + API 路由 + 服务接线

**Files:**
- Modify: `backend/src/ict_agent/models.py`
- Modify: `backend/src/ict_agent/api.py`
- Modify: `backend/src/ict_agent/service.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces：`/api/v1/insights/customers`、`/api/v1/insights/customers/{id}`、`/api/v1/insights/ar-aging`、
  `/api/v1/insights/inventory-aging`、`/api/v1/insights/extension-heatmap`、`/api/v1/insights/inventory-economic`、
  `/api/v1/insights/revenue-trend`、`/api/v1/insights/vintage`、`/api/v1/insights/actions`。
  全部 `GET`，返回 `{items: [...]}` 或单对象；错误 404 返回 JSON。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_api.py` 追加（该文件模块级已有 `client = TestClient(api.app)`，直接引用，不加 fixture 参数）：

```python
def test_insights_endpoints_return_json() -> None:
    for path in (
        "/api/v1/insights/customers",
        "/api/v1/insights/ar-aging",
        "/api/v1/insights/inventory-aging",
        "/api/v1/insights/revenue-trend",
        "/api/v1/insights/vintage",
        "/api/v1/insights/actions",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("application/json")


def test_insights_customer_detail_and_404() -> None:
    first = client.get("/api/v1/insights/customers").json()["items"][0]
    detail = client.get(f"/api/v1/insights/customers/{first['customer_id']}")
    assert detail.status_code == 200
    assert "warning_state" in detail.json()
    assert client.get("/api/v1/insights/customers/NO_SUCH_CUSTOMER").status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -k insights -q`
Expected: FAIL（路由不存在 → 404 或 405）。

- [ ] **Step 3: 加响应模型（models.py）**

在 `models.py` 追加：

```python
class InsightCustomerItem(BaseModel):
    customer_id: str
    customer_name: str
    v_score: float
    r_score: float
    v_tier: str
    r_tier: str
    grid: str
    hard_overlay: bool


class CustomerDetailResponse(BaseModel):
    customer_id: str
    customer_name: str
    scores: dict[str, Any]
    warning_state: str
    extensions: dict[str, Any]
    credit_triggers: dict[str, list[str]]
    action_tier: str


class ItemsResponse(BaseModel):
    items: list[dict[str, Any]]
```

（`Any` 需从 `typing` 导入；`models.py` 现有导入按需补 `Any`。）

- [ ] **Step 4: 服务函数（service.py）**

在 `service.py` 追加（顶部 import insights；`Settings`/`load_settings`/`DuckDBStore` 均已导入；`Any` 从 `typing` 导入，若未导入则补）：

```python
from ict_agent.insights import (
    get_action_queue,
    get_ar_aging,
    get_customer_detail,
    get_customer_scores,
    get_extension_heatmap,
    get_inventory_aging,
    get_inventory_economic,
    get_revenue_trend,
    get_vintage,
)


def _open_store(settings: Settings | None = None) -> DuckDBStore:
    runtime_settings = settings or load_settings(require_api_key=False)
    store = DuckDBStore(runtime_settings.database_path)
    store.ensure_ready()
    return store


def get_insights_customers(*, settings: Settings | None = None) -> list[dict[str, Any]]:
    return get_customer_scores(_open_store(settings))


def get_insights_customer(customer_id: str, *, settings: Settings | None = None) -> dict[str, Any]:
    return get_customer_detail(_open_store(settings), customer_id)
```

（按此模式补齐其余 8 个服务函数：`get_insights_ar_aging` / `get_insights_inventory_aging` /
`get_insights_extension_heatmap` / `get_insights_inventory_economic` / `get_insights_revenue_trend` /
`get_insights_vintage` / `get_insights_actions` 各返回 `list[dict[str, Any]]`，内部 `_open_store` + 对应
insights 函数；`get_insights_customer` 把 `KeyError` 向上抛，由 api 层转 404。）

- [ ] **Step 5: API 路由（api.py）**

在 `api.py` 追加（沿用现有模式：路由不注入 Settings，直接调用 service 函数；`HTTPException` 已导入；把 `get_insights_*` 服务函数加入顶部 import）：

```python
@app.get("/api/v1/insights/customers", response_model=ItemsResponse, tags=["insights"])
async def insights_customers() -> ItemsResponse:
    return ItemsResponse(items=get_insights_customers())


@app.get(
    "/api/v1/insights/customers/{customer_id}",
    response_model=CustomerDetailResponse,
    tags=["insights"],
)
async def insights_customer_detail(customer_id: str) -> CustomerDetailResponse:
    try:
        return CustomerDetailResponse(**get_insights_customer(customer_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

（其余 8 个端点同理，都返回 `ItemsResponse`：`ar-aging`、`inventory-aging`、`extension-heatmap`、
`inventory-economic`、`revenue-trend`、`vintage`、`actions` 各调用对应 `get_insights_*` 服务函数，
`items=` 包一层；`extension-heatmap`/`inventory-economic` 返回空列表时仍是 200。）

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -k insights -q`
Expected: PASS（2 项）。若 `_get_settings` 不存在，改用 api.py 现有注入名。

- [ ] **Step 7: 提交**

```bash
git add backend/src/ict_agent/models.py backend/src/ict_agent/api.py backend/src/ict_agent/service.py backend/tests/test_api.py
git commit -m "feat: insights API endpoints and response models"
```

---

### Task 7: 全量验收（后端）

**Files:**
- None（只读验证，问题才改）。

**Interfaces:**
- 无新接口；验证 P0+P1 全部交付。

- [ ] **Step 1: 全量测试与静态检查**

Run:
```bash
cd "D:\作业\aaachagent\ict-agent-fresh"
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format . --check
.venv/Scripts/python.exe -m mypy backend/src
```
Expected: pytest 全绿（含新增 insights 测试）、ruff 与 mypy 全过。

- [ ] **Step 2: 真实数据抽查**

启动后端并抽查端点（真实 DuckDB 已在 `data/processed`）：
```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && .venv/Scripts/python.exe -m uvicorn ict_agent.api:app --app-dir backend/src --host 127.0.0.1 --port 8000
```
用 curl 抽查：
- `GET /api/v1/insights/customers` → 返回 ~66 家客户、V/R 分与九宫格字段
- `GET /api/v1/insights/customers/{任一id}` → 含 `warning_state` / `extensions` / `credit_triggers` / `action_tier`
- `GET /api/v1/insights/ar-aging` / `inventory-aging` / `revenue-trend` → 有数据
- `GET /api/v1/insights/actions` → 按严重度排序
确认无 500；`黑名单` 客户 `r_tier=high`。抽查后停止后端。

- [ ] **Step 3: 修复 + 复核 + 提交**

对发现问题修复后重跑 Step 1；全绿后提交剩余改动（若有）：
```bash
git add backend/ docs/
git commit -m "fix: insights acceptance fixes"
```

- [ ] **Step 4: 收尾报告**

汇报：新增端点清单、测试结果、真实数据抽查结论、遗留问题（如有）。

---

## Self-Review

- **Spec 覆盖**：客户评分/九宫格（Task 2）✓；预警状态机/展期/授信/详情（Task 3）✓；四级动作（Task 4）✓；
  6 组可视化数据集（Task 5）✓；模型/路由/服务（Task 6）✓；P0 口径（Task 1）✓；验收（Task 7）✓。override
  审计的后端字段（口径第 12 节）标注 P3 实现前端，后端只在口径冻结，未在 P1 加字段——与 spec 分期一致（P3 再做）。
- **占位符**：无 TBD/TODO；代码步骤均给完整代码。标注「以 data.py 实际列名修正」处是有意为之的兼容提示，非占位。
- **类型一致性**：`get_customer_scores`/`get_customer_detail`/`get_action_queue`/6 组数据集签名在 Task 2–5
  定义、Task 6 调用一致；模型字段与 insights 返回 dict key 一致。
