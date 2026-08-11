"""insights 评分与状态机的微型夹具测试。"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

import pytest
from ict_agent.data import DuckDBStore, rebuild_database
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


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def dedicated_store(tmp_path: Path) -> Iterator[DuckDBStore]:
    """I1/I2 回归专用微型库。

    与共享 conftest 的 store 隔离：不向共享七表加行，避免 test_tools/test_rules 对
    固定数值（如 C015 最新应收=1000、规则案件数）的硬编码断言失效。

    - C100：最新快照应收 1500 / 授信 1000 → 授信使用率 1.5≥1.0；超期金额为 0，
      旧口径分子为 0，仅应收余额口径能触发降额（I1 回归）。
    - C200：超期 35 天（DPD_30_PLUS）+ 含税粗算毛利 50-80=-30≤0 → 四级动作必须 ORANGE
      而非 YELLOW（I2 回归）。
    """

    data_dir = tmp_path / "dedicated_raw"
    data_dir.mkdir()
    _write_csv(
        data_dir / "销售流水.csv",
        [
            {
                "出库日期": "2026-07-10",
                "客户编号": "C100",
                "客户名称": "高应收余额测试客户",
                "合同号": "",
                "销售订单号": "S100",
                "库存组织名称": "W1",
                "物料编码": "M1",
                "数量": 1,
                "出库类型": "销售出库",
                "事务处理类型名称": "正常销售",
                "销售金额_折扣后_含税": 100,
                "出库成本金额": 60,
            },
            {
                "出库日期": "2026-07-20",
                "客户编号": "C200",
                "客户名称": "毛利为负测试客户",
                "合同号": "",
                "销售订单号": "S200",
                "库存组织名称": "W1",
                "物料编码": "M3",
                "数量": 1,
                "出库类型": "销售出库",
                "事务处理类型名称": "正常销售",
                "销售金额_折扣后_含税": 50,
                "出库成本金额": 80,
            },
        ],
    )
    _write_csv(
        data_dir / "业务回款明细.csv",
        [
            {
                "回款日期": "2026-07-10",
                "客户编号": "C200",
                "合同号": "",
                "销售订单号": "S200",
                "回款金额": 10,
                "超期利息金额": 0,
                "最终承诺还款日期": "2026-07-31",
                "是否超期": "N",
                "超期天数": 0,
                "回款账龄": 5,
                "物料编码": "M3",
            },
        ],
    )
    _write_csv(
        data_dir / "增值合同签约明细.csv",
        [
            {
                "申请日期": "2026-05-01",
                "合同编号": "CT100",
                "合同状态": "流程结束",
                "客户名称": "高应收余额测试客户",
                "销售金额": 100,
                "实估毛利率_不含税": 0.2,
                "实际净毛利率_不含税": 0.1,
                "合同文本账期": 30,
                "实际账期": 30,
                "开票金额1": 100,
            }
        ],
    )
    _write_csv(
        data_dir / "应收快照_月末24期.csv",
        [
            {
                "快照时间": "2026-07-31",
                "合同号": "",
                "客户编号": "C100",
                "客户名称": "高应收余额测试客户",
                "销售订单号": "A100",
                "应收金额": 1500,
                "超期应收金额": 0,
                "超期30天以上金额": 0,
                "超期60天以上金额": 0,
                "最终承诺还款日期": "2026-08-31",
                "是否展期": "N",
                "超期天数": 0,
                "物料编码": "M1",
            },
            {
                "快照时间": "2026-07-31",
                "合同号": "",
                "客户编号": "C200",
                "客户名称": "毛利为负测试客户",
                "销售订单号": "A200",
                "应收金额": 500,
                "超期应收金额": 100,
                "超期30天以上金额": 50,
                "超期60天以上金额": 0,
                "最终承诺还款日期": "2026-07-15",
                "是否展期": "N",
                "超期天数": 35,
                "物料编码": "M3",
            },
        ],
    )
    _write_csv(
        data_dir / "库龄快照_季末8期.csv",
        [
            {
                "快照日期": "2026-06-30",
                "物料编码": "M1",
                "库存组织名称": "W1",
                "数量": 1,
                "库龄": 10,
                "含税总价": 100,
                "是否超期": "N",
                "超期天数": 0,
            },
        ],
    )
    _write_csv(
        data_dir / "展期记录.csv",
        [
            {
                "快照时间": "2026-06-01",
                "合同号": "",
                "客户编号": "C200",
                "销售订单号": "A200",
                "物料编码": "M3",
                "最终承诺还款日期": "2026-07-31",
                "是否展期": "N",
                "超期天数": 0,
                "gkey": "g0",
            },
        ],
    )
    _write_csv(
        data_dir / "客户授信.csv",
        [
            {
                "客户编号_中台": "C100",
                "客户名称": "高应收余额测试客户",
                "授信额度": 1000,
                "黑白名单状态": 0,
                "黑白名单原因": "",
                "黑白名单创建时间": "2025-01-01",
                "失信分级": "",
                "净资产": 3000,
                "净利润": 100,
                "信用保险": "N",
            },
            {
                "客户编号_中台": "C200",
                "客户名称": "毛利为负测试客户",
                "授信额度": 1000,
                "黑白名单状态": 0,
                "黑白名单原因": "",
                "黑白名单创建时间": "2025-01-01",
                "失信分级": "",
                "净资产": 500,
                "净利润": 10,
                "信用保险": "N",
            },
        ],
    )
    db_path = tmp_path / "processed" / "dedicated.duckdb"
    rebuild_database(data_dir, db_path)
    yield DuckDBStore(db_path)


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
        assert row["warning_state"] in {
            "NOT_DUE",
            "DPD_1_PLUS",
            "DPD_30_PLUS",
            "DPD_60_PLUS",
            "DPD_90_REVIEW",
        }


def test_blacklist_is_hard_high(store) -> None:
    scores = {row["customer_id"]: row for row in get_customer_scores(store)}
    # conftest 若把某客户设为黑名单（黑白名单状态=2），其 r_tier 必须为 high
    blacklisted = [r for r in scores.values() if r["hard_overlay"]]
    assert blacklisted, "微型夹具应至少包含一个黑名单/失信客户以验证硬覆盖"
    for row in blacklisted:
        assert row["r_tier"] == "high"


def test_value_score_direction(store) -> None:
    scores = get_customer_scores(store)
    top = max(scores, key=lambda s: s["gross_profit"])
    assert top["v_tier"] == "high"
    assert top["v_score"] >= 50


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


def test_credit_utilization_uses_ar_balance(dedicated_store) -> None:
    # 口径 §7/§10：授信使用率 = SUM(应收金额)/授信额度（最新月末截面）。
    # 专用夹具 C100：应收 1500 / 授信 1000 → util = 1.5 ≥1.0；
    # 若错误地用超期金额当分子只有 0/1000 = 0，达不到 1.0 阈值，无法触发降额。
    ar = dedicated_store.fetch(
        """
        SELECT SUM("应收金额"), SUM("超期应收金额")
        FROM ar_snapshots
        WHERE "客户编号" = ?
          AND "快照时间" = (SELECT MAX("快照时间") FROM ar_snapshots)
        """,
        ("C100",),
    ).rows[0]
    credit = dedicated_store.fetch(
        'SELECT "授信额度" FROM customer_credit WHERE "客户编号_中台" = ?',
        ("C100",),
    ).rows[0][0]
    expected_util = float(ar[0]) / float(credit)
    overdue_util = float(ar[1]) / float(credit)
    assert expected_util >= 1.0, "夹具设计：应收余额口径使用率应 ≥1.0"
    assert overdue_util < 1.0, "夹具设计：超期口径使用率应 <1.0，确保能区分分子来源"

    detail = get_customer_detail(dedicated_store, "C100")
    assert detail["credit_triggers"]["decrease_signals"], (
        f"授信使用率 {expected_util:.2f} ≥1.0 应触发降额信号"
        f"（错误地用超期金额当分子只有 {overdue_util:.2f}）"
    )


def test_negative_margin_dpd30_maps_to_orange(dedicated_store) -> None:
    # 口径 §11：毛利≤0 → ORANGE，须优先于 DPD_30_PLUS 的 YELLOW。
    # 专用夹具 C200：超期 35 天 → DPD_30_PLUS；含税粗算毛利 50 - 80 = -30 ≤ 0。
    detail = get_customer_detail(dedicated_store, "C200")
    assert detail["warning_state"] == "DPD_30_PLUS"
    assert detail["scores"]["gross_profit"] <= 0
    assert detail["action_tier"] == "ORANGE"


def test_blacklist_customer_is_red_tier(store) -> None:
    queue = get_action_queue(store)
    blacklisted = [q for q in queue if q["entity_id"] == "C002"]
    assert blacklisted, "fixture 应包含黑名单客户 C002"
    assert blacklisted[0]["tier"] == "RED"


def test_action_queue_sorted_by_severity(store) -> None:
    queue = get_action_queue(store)

    order = {"RED": 0, "ORANGE": 1, "YELLOW": 2, "GREEN": 3}
    tiers = [order[q["tier"]] for q in queue]
    assert tiers == sorted(tiers)
    assert all(q["side"] == "RECEIVABLE" for q in queue)


def test_visualization_datasets_shapes(store) -> None:
    assert get_ar_aging(store), "账龄结构应有数据"
    assert get_inventory_aging(store)
    assert get_extension_heatmap(store) is not None
    assert get_inventory_economic(store)
    for row in get_revenue_trend(store):
        assert {"month", "revenue", "gross_profit", "cm2"} <= set(row)
    for row in get_vintage(store):
        assert {"cohort", "elapsed", "overdue_rate"} <= set(row)
