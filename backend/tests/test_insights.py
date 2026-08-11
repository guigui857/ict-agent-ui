"""insights 评分与状态机的微型夹具测试。"""

from __future__ import annotations

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
        assert row["warning_state"] in {"NOT_DUE", "DPD_1_PLUS", "DPD_30_PLUS", "DPD_60_PLUS", "DPD_90_REVIEW"}


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
        "NOT_DUE", "PRE_DUE", "DPD_1_PLUS", "DPD_30_PLUS", "DPD_60_PLUS",
        "DPD_90_REVIEW", "HIGH_WATCH_BUT_NOT_DEFAULT", "INDIVIDUAL_ECL",
    }
    assert "explicit_count" in detail["extensions"]
    assert isinstance(detail["credit_triggers"]["increase_signals"], list)
    assert detail["action_tier"] in {"GREEN", "YELLOW", "ORANGE", "RED"}


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
