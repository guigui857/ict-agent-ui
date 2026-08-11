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


def _feature_scores(rows: list[tuple[Any, ...]], value_index: int) -> dict[str, float]:
    """按经验分布把某列转成 0-100 分（升序分位）：数值越大 → 分位越高。"""
    n = len(rows)
    if n == 0:
        return {}
    ordered = sorted(rows, key=lambda r: float(r[value_index] or 0))
    return {str(row[0]): round((position - 1) / max(n - 1, 1) * 100.0, 2)
            for position, row in enumerate(ordered, start=1)}


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
        result.append({
            "customer_id": cid,
            "customer_name": str(row[1] or cid),
            "gross_profit": float(row[3] or 0),
            "v_score": round(v, 2),
            "r_score": round(r, 2),
            "v_tier": "",
            "r_tier": "high" if hard else "",
            "hard_overlay": hard,
            "grid": "",
        })
    # 三分位切档
    v_sorted = sorted(item["v_score"] for item in result)
    r_sorted = sorted(item["r_score"] for item in result)
    v_lo, v_hi = _terciles(v_sorted)
    r_lo, r_hi = _terciles(r_sorted)
    for item in result:
        item["v_tier"] = "high" if item["v_score"] >= v_hi else "low" if item["v_score"] < v_lo else "mid"
        item["r_tier"] = item["r_tier"] or ("high" if item["r_score"] >= r_hi else "low" if item["r_score"] < r_lo else "mid")
        item["grid"] = f"value_{item['v_tier']}_risk_{item['r_tier']}"
    return result


def _terciles(sorted_values: list[float]) -> tuple[float, float]:
    """返回三分位的下界与上界（n<3 时退化为中位）。"""
    n = len(sorted_values)
    if n == 0:
        return (0.0, 100.0)
    return (sorted_values[max(0, n // 3 - 1)], sorted_values[max(0, (2 * n) // 3 - 1)])
