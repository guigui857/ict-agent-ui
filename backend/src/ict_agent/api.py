"""ICT Agent 的 FastAPI HTTP 入口。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ict_agent.models import (
    CaseStatus,
    CaseType,
    CustomerDetailResponse,
    DashboardResponse,
    DataSnapshotResponse,
    ErrorResponse,
    HealthResponse,
    ItemsResponse,
    ReviewRecord,
    ReviewRequest,
    RiskCaseDetail,
    RiskCaseSummary,
    RiskOverviewResponse,
    RuleRunResponse,
)
from ict_agent.service import (
    ServiceError,
    get_case_detail,
    get_dashboard,
    get_data_snapshot,
    get_insights_actions,
    get_insights_ar_aging,
    get_insights_customer,
    get_insights_customers,
    get_insights_extension_heatmap,
    get_insights_inventory_aging,
    get_insights_inventory_economic,
    get_insights_revenue_trend,
    get_insights_vintage,
    get_risk_overview,
    list_cases,
    prepare_investigation,
    review_case,
    run_rule_scan,
    stream_prepared_investigation,
)

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"

app = FastAPI(
    title="佳华智审风险调查 Agent API",
    version="0.4.0",
    description="基于可追溯七表快照、统一证据网关的可观察 Agent 调查与人工审核闭环。",
)


@app.exception_handler(ServiceError)
async def handle_service_error(_request: Request, exc: ServiceError) -> JSONResponse:
    """把应用错误映射为不泄漏内部细节的稳定响应。"""

    logger.warning(
        "request_id=%s service_error=%s status=%s",
        exc.request_id,
        type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
        exc.status_code,
    )
    payload = ErrorResponse(error=str(exc), request_id=exc.request_id)
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


@app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """确认 HTTP 服务已经启动。"""

    return HealthResponse(status="ok", service="ict-agent")


@app.get(
    "/api/v1/data-snapshot",
    response_model=DataSnapshotResponse,
    responses={503: {"model": ErrorResponse}},
    tags=["system"],
)
async def data_snapshot() -> DataSnapshotResponse:
    """返回当前七表导入的可复核内容身份。"""

    return get_data_snapshot()


@app.get(
    "/api/v1/overview",
    response_model=DashboardResponse,
    responses={503: {"model": ErrorResponse}},
    tags=["analysis"],
)
async def overview() -> DashboardResponse:
    """返回首页经营、应收、库存和趋势数据。"""

    return get_dashboard()


@app.post(
    "/api/v1/rule-runs",
    response_model=RuleRunResponse,
    responses={500: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    tags=["risk-cases"],
)
async def create_rule_run() -> RuleRunResponse:
    """对当前最新快照执行一次幂等风险规则扫描。"""

    return run_rule_scan()


@app.get(
    "/api/v1/risk/overview",
    response_model=RiskOverviewResponse,
    responses={503: {"model": ErrorResponse}},
    tags=["risk-cases"],
)
async def risk_overview() -> RiskOverviewResponse:
    """返回案件数量、状态、敞口和最近扫描摘要。"""

    return get_risk_overview()


@app.get(
    "/api/v1/cases",
    response_model=list[RiskCaseSummary],
    responses={503: {"model": ErrorResponse}},
    tags=["risk-cases"],
)
async def cases(
    status: CaseStatus | None = None,
    case_type: CaseType | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
) -> list[RiskCaseSummary]:
    """查询风险案件队列。"""

    return list_cases(status=status, case_type=case_type, limit=limit)


@app.get(
    "/api/v1/cases/{case_id}",
    response_model=RiskCaseDetail,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    tags=["risk-cases"],
)
async def case_detail(case_id: str) -> RiskCaseDetail:
    """返回一个案件的规则、调查和人工审核详情。"""

    return get_case_detail(case_id)


@app.post(
    "/api/v1/cases/{case_id}/investigations",
    responses={
        200: {
            "description": "按行返回 InvestigationStreamEvent 的 NDJSON 事件流。",
            "content": {"application/x-ndjson": {}},
        },
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    tags=["agent"],
)
async def create_case_investigation(case_id: str) -> StreamingResponse:
    """流式返回 DeepSeek 的工具取证、校验和最终报告事件。"""

    prepared = prepare_investigation(case_id)

    async def ndjson_events() -> AsyncIterator[str]:
        async for event in stream_prepared_investigation(prepared):
            yield event.model_dump_json() + "\n"

    return StreamingResponse(ndjson_events(), media_type="application/x-ndjson")


@app.post(
    "/api/v1/cases/{case_id}/reviews",
    response_model=ReviewRecord,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    tags=["risk-cases"],
)
async def submit_case_review(case_id: str, request: ReviewRequest) -> ReviewRecord:
    """提交人工审核、处置或持续观察决定。"""

    return review_case(case_id, request)


@app.get("/api/v1/insights/customers", response_model=ItemsResponse, tags=["insights"])
async def insights_customers() -> ItemsResponse:
    """返回全部授信客户的价值/风险评分、档位与九宫格。"""

    return ItemsResponse(items=get_insights_customers())


@app.get(
    "/api/v1/insights/customers/{customer_id}",
    response_model=CustomerDetailResponse,
    tags=["insights"],
)
async def insights_customer_detail(customer_id: str) -> CustomerDetailResponse:
    """返回单客户评分、预警状态、展期识别、授信触发与四级动作。"""

    try:
        return CustomerDetailResponse(**get_insights_customer(customer_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/insights/ar-aging", response_model=ItemsResponse, tags=["insights"])
async def insights_ar_aging() -> ItemsResponse:
    """返回应收账龄结构（期、账龄桶、金额）。"""

    return ItemsResponse(items=get_insights_ar_aging())


@app.get("/api/v1/insights/inventory-aging", response_model=ItemsResponse, tags=["insights"])
async def insights_inventory_aging() -> ItemsResponse:
    """返回库存库龄结构（季度、库龄桶、金额）。"""

    return ItemsResponse(items=get_insights_inventory_aging())


@app.get("/api/v1/insights/extension-heatmap", response_model=ItemsResponse, tags=["insights"])
async def insights_extension_heatmap() -> ItemsResponse:
    """返回展期月度热度（客户、月份、count）。"""

    return ItemsResponse(items=get_insights_extension_heatmap())


@app.get("/api/v1/insights/inventory-economic", response_model=ItemsResponse, tags=["insights"])
async def insights_inventory_economic() -> ItemsResponse:
    """返回库存经济性（库龄桶、边际毛利）。"""

    return ItemsResponse(items=get_insights_inventory_economic())


@app.get("/api/v1/insights/revenue-trend", response_model=ItemsResponse, tags=["insights"])
async def insights_revenue_trend() -> ItemsResponse:
    """返回月度销售与毛利趋势。"""

    return ItemsResponse(items=get_insights_revenue_trend())


@app.get("/api/v1/insights/vintage", response_model=ItemsResponse, tags=["insights"])
async def insights_vintage() -> ItemsResponse:
    """返回应收账龄队列的 Vintage 逾期率。"""

    return ItemsResponse(items=get_insights_vintage())


@app.get("/api/v1/insights/actions", response_model=ItemsResponse, tags=["insights"])
async def insights_actions() -> ItemsResponse:
    """返回应收侧四级动作队列。"""

    return ItemsResponse(items=get_insights_actions())


@app.get("/", include_in_schema=False)
async def frontend_index() -> FileResponse:
    """提供同源的风险调查演示页面。"""

    return FileResponse(FRONTEND_DIST_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIST_DIR), name="static")


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def spa_fallback(full_path: str) -> FileResponse:
    """history 路由模式的 SPA 兜底：未知前端路径返回 index.html，交给客户端路由处理。"""

    if full_path.startswith(("api/", "static/")):
        raise HTTPException(status_code=404)
    return FileResponse(FRONTEND_DIST_DIR / "index.html")
