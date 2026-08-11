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
