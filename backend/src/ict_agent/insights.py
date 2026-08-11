"""确定性风控洞察计算（口径见 docs/metric-contract.md 第 7–12 节）。"""

from __future__ import annotations

from typing import Any

from .data import DuckDBStore

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


def _feature_scores(rows: list[tuple[Any, ...]], value_index: int) -> dict[str, float]:
    """按经验分布把某列转成 0-100 分（升序分位）：数值越大 → 分位越高。"""
    n = len(rows)
    if n == 0:
        return {}
    ordered = sorted(rows, key=lambda r: float(r[value_index] or 0))
    return {
        str(row[0]): round((position - 1) / max(n - 1, 1) * 100.0, 2)
        for position, row in enumerate(ordered, start=1)
    }


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
    # 9 dpd90_ratio, 10 overdue30_ratio, 11 extension_count, 12 credit_utilization,
    # 13 blacklist, 14 rating
    value_scores = {
        "revenue": _feature_scores(rows, 2),
        "gross_profit": _feature_scores(rows, 3),
        "category_breadth": _feature_scores(rows, 4),
        "active_months": _feature_scores(rows, 5),
        "payment_stability": _feature_scores(rows, 6),
    }
    risk_scores = {
        "max_dpd": _feature_scores(rows, 7),
        "overdue_ratio": _feature_scores(rows, 8),
        "dpd90_ratio": _feature_scores(rows, 9),
        "overdue30_ratio": _feature_scores(rows, 10),
        "extension_count": _feature_scores(rows, 11),
        "credit_utilization": _feature_scores(rows, 12),
    }
    result: list[dict[str, Any]] = []
    for row in rows:
        cid = str(row[0])
        v = sum(VALUE_WEIGHTS[k] * value_scores[k].get(cid, 0.0) for k in VALUE_WEIGHTS)
        r = sum(RISK_WEIGHTS[k] * risk_scores[k].get(cid, 0.0) for k in RISK_WEIGHTS)
        blacklist = int(row[13])
        rating = str(row[14] or "")
        hard = blacklist == 2 or (rating.strip() != "" and rating.strip() != "无")
        max_dpd = int(row[7])
        warning_state = (
            "DPD_90_REVIEW"
            if max_dpd >= 90
            else "DPD_60_PLUS"
            if max_dpd >= 60
            else "DPD_30_PLUS"
            if max_dpd >= 30
            else "DPD_1_PLUS"
            if max_dpd >= 1
            else "NOT_DUE"
        )
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
                "warning_state": warning_state,
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
        SUM("应收金额") AS ar_balance,
        MIN(CASE WHEN "最终承诺还款日期" >= "快照时间"
                 THEN CAST(date_diff('day', "快照时间", "最终承诺还款日期") AS INTEGER)
                 END) AS days_to_due,
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
    COALESCE(c."授信额度", 0) AS credit_limit,       -- 2
    COALESCE(c."黑白名单状态", 0) AS blacklist,      -- 3
    c."失信分级" AS rating,             -- 4
    COALESCE(p.max_dpd, 0) AS max_dpd,  -- 5
    COALESCE(p.overdue_amount, 0) AS overdue_amount,  -- 6
    p.days_to_due,                      -- 7
    COALESCE(p.extended_rows, 0) AS extended_rows,    -- 8
    COALESCE(p9.recent_payment, 0) AS recent_payment, -- 9
    COALESCE(e.extension_count, 0) AS extension_count, -- 10
    e.earliest,                         -- 11
    e.latest,                           -- 12
    COALESCE(p.ar_balance, 0) AS ar_balance  -- 13
FROM customer_credit c
LEFT JOIN per_customer p ON p.cid = c."客户编号_中台"
LEFT JOIN payments90 p9 ON p9.cid = c."客户编号_中台"
LEFT JOIN ext e ON e.cid = c."客户编号_中台"
"""


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
    state: str, extension_count: int, gross_profit: float, date_reset_count: int, stop_signal: bool
) -> str:
    """按口径第 11 节判定四级动作。"""
    if stop_signal or date_reset_count >= 1:
        return "RED"
    if (
        state in {"INDIVIDUAL_ECL", "DPD_90_REVIEW", "HIGH_WATCH_BUT_NOT_DEFAULT"}
        or extension_count >= 3
        or gross_profit <= 0
    ):
        return "ORANGE"
    if state in {"DPD_30_PLUS", "DPD_60_PLUS"}:
        return "YELLOW"
    return "GREEN"


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


def _load_precomputed(store: DuckDBStore) -> dict[str, Any]:
    """一次载入评分与预警基表，供队列与详情共享，避免 N×M 重跑。"""
    return {
        "scores": {row["customer_id"]: row for row in get_customer_scores(store)},
        "warning_rows": _fetch_rows(store, _WARNING_SQL),
    }


def get_customer_detail(
    store: DuckDBStore, customer_id: str, _precomputed: dict[str, Any] | None = None
) -> dict[str, Any]:
    """返回单客户评分、预警状态、展期识别、授信触发与四级动作。"""
    pre = _precomputed if _precomputed is not None else _load_precomputed(store)
    scores = pre["scores"]
    base = pre["warning_rows"]
    row = next((r for r in base if str(r[0]) == customer_id), None)
    if row is None:
        raise KeyError(f"未知客户 {customer_id}")
    # 列序（与 _WARNING_SQL 对齐）：0 cid, 1 cname, 2 credit_limit, 3 blacklist, 4 rating,
    # 5 max_dpd, 6 overdue, 7 days_to_due, 8 extended_rows, 9 recent_payment, 10 extension_count,
    # 11 earliest, 12 latest, 13 ar_balance
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
    utilization = (float(row[13]) / float(row[2])) if float(row[2]) else 0.0
    increase = (
        v_tier == "high"
        and utilization >= 0.7
        and recent_payment > 0
        and r_tier != "high"
        # 90+ 逾期客户即使近期回款（HIGH_WATCH_BUT_NOT_DEFAULT）也不升额
        and state not in {"INDIVIDUAL_ECL", "DPD_90_REVIEW", "HIGH_WATCH_BUT_NOT_DEFAULT"}
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
        "action_tier": _action_tier(state, ext_count, gross, date_reset, stop),
    }


def get_action_queue(store: DuckDBStore) -> list[dict[str, Any]]:
    """应收侧四级动作队列，按严重度排序。"""
    pre = _load_precomputed(store)
    rows = []
    for detail_row in pre["warning_rows"]:
        cid = str(detail_row[0])
        try:
            detail = get_customer_detail(store, cid, _precomputed=pre)
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


def get_ar_aging(store: DuckDBStore) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        store,
        """
        SELECT strftime("快照时间", '%Y-%m') AS period,
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
        SELECT strftime("快照日期", '%Y-%m') AS quarter,
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
        SELECT "客户编号" AS cid, strftime("快照时间", '%Y-%m') AS month, COUNT(*) AS cnt
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
        SELECT strftime("出库日期", '%Y-%m') AS month,
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
            SELECT "客户编号" AS cid, strftime("快照时间", '%Y-%m') AS period,
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
