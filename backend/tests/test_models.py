"""Pydantic 数据契约测试。"""

from datetime import date

import pytest
from ict_agent.models import ReviewRequest, ToolResult
from pydantic import ValidationError


def test_tool_result_requires_matching_row_width() -> None:
    with pytest.raises(ValidationError, match="columns"):
        ToolResult(
            summary="结果",
            columns=["a", "b"],
            rows=[[1]],
            sources=["sales"],
            period="2026-07-31",
        )


def test_review_request_accepts_override_fields() -> None:
    request = ReviewRequest(
        decision="FALSE_POSITIVE",
        reviewer="审计员A",
        reason="经核实为误报",
        override_status="APPROVED",
        override_reason="客户已还款并出具承诺",
        approver="风控主管",
    )
    assert request.override_status == "APPROVED"
    assert request.override_reason == "客户已还款并出具承诺"


def test_override_status_only_approved_or_rejected() -> None:
    with pytest.raises(ValidationError):
        ReviewRequest(decision="MONITOR", reviewer="x", reason="xx", next_review_at=date(2026, 9, 1), override_status="MAYBE")
