# 风控洞察 P3（人工 override 审计）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地人工 override 审计：审核接口支持可选的 override 字段，保留原始规则命中并记录审计；新增只读 `/api/v1/insights/overrides` 端点；前端审核表单加 override 区，治理中心展示审计列表（替换 P3 占位）。

**Architecture:** 后端扩展 `ReviewRequest`/`ReviewWrite`/`reviews` 表（4 个 override 列，`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 幂等迁移），`review_case` 透传 override 字段，新增 `fetch_overrides` + `get_insights_overrides` + `GET /api/v1/insights/overrides`；前端 `CaseWorkspace.vue` 审核表单加 override 区，`InsightsGovernance.vue` 用真实审计列表替换占位。**override 不删除、不修改规则命中**（案件 rule_hits 原样保留）。

**Tech Stack:** Python 3.12 / DuckDB / FastAPI / Pydantic；Vue 3 / Tailwind / `ui/Badge.vue` / `lib.api`。

**工作目录约定：** 后端命令在 `D:\作业\aaachagent\ict-agent-fresh`（`.venv/Scripts/python.exe`）；前端在 `...\frontend`（`npm run build`）。后端已在 `http://127.0.0.1:8000` 运行（若没在跑，`.venv/Scripts/python.exe -m uvicorn ict_agent.api:app --app-dir backend/src --host 127.0.0.1 --port 8000`）。

## Global Constraints

- 口径见 `docs/metric-contract.md` §12：override 审计字段 = `override_status`（APPROVED/REJECTED）、`override_reason`、`override_expiry_date`、`approver`；保留原始 `rule_hit`，不删除/修改；`next_review_date`/`input_timestamp`/`evidence_json` 由系统记录。
- 项目原则「不保留向后兼容」：接口/结构变化同批同步所有调用方、测试、文档。旧 reviews 行的 override 列取 NULL，不影响读取。
- 金额/比例等口径不变；不引入模型调用；不改动案件/规则/证据契约的现有行为（只扩展审核输入）。
- 新增行为必须测试（`backend/tests/conftest.py` 微型夹具）。
- 前端无测试框架，验收 = build + grep + 截图/DOM + CDP 冒烟。
- 验收：`pytest -q`、`ruff check .`、`ruff format . --check`、`mypy backend/src`、`npm run build` 全过。

---

### Task 1: 后端模型与存储层

**Files:**
- Modify: `backend/src/ict_agent/models.py`
- Modify: `backend/src/ict_agent/data.py`
- Test: `backend/tests/test_models.py`、`backend/tests/test_data.py`

**Interfaces:**
- Produces: `ReviewRequest` 增加可选 `override_status`/`override_reason`/`override_expiry_date`/`approver`；`ReviewRecord` 增加同名字段（可选）；新增 `OverrideRecord` 响应模型；`ReviewWrite` 增加 4 字段；`reviews` 表增加 4 列（幂等迁移）；`save_review` 写入；`fetch_overrides()` 查询。Task 2 依赖这些。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_models.py` 追加：

```python
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
```

（`ReviewRequest`/`date`/`pytest`/`ValidationError` 按 test_models.py 现有 import 补齐。）

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_models.py -k override -q`
Expected: FAIL —— `override_status` 字段不存在。

- [ ] **Step 3: 扩展 ReviewRequest 与 ReviewRecord（models.py）**

`ReviewRequest` 增加字段：

```python
    override_status: Literal["APPROVED", "REJECTED"] | None = None
    override_reason: Annotated[str | None, Field(max_length=500)] = None
    override_expiry_date: date | None = None
    approver: Annotated[str | None, Field(max_length=100)] = None

    @model_validator(mode="after")
    def override_requires_reason_and_approver(self) -> ReviewRequest:
        if self.override_status is not None and (not self.override_reason or not self.approver):
            raise ValueError("记录 override 必须填写 override_reason 与 approver")
        return self
```

`ReviewRecord` 增加：

```python
    override_status: str | None = None
    override_reason: str | None = None
    override_expiry_date: str | None = None
    approver: str | None = None
```

新增（文件末尾）：

```python
class OverrideRecord(BaseModel):
    """一次人工 override 的审计记录（保留原始规则命中的前提下）。"""

    review_id: str
    case_id: str
    decision: ReviewDecision
    reviewer: str
    reason: str
    action: str | None
    override_status: str
    override_reason: str | None
    override_expiry_date: str | None
    approver: str | None
    next_review_at: str | None
    created_at: str
```

- [ ] **Step 4: 扩展存储层（data.py）**

`ReviewWrite` 增加 4 字段：

```python
    override_status: str | None = None
    override_reason: str | None = None
    override_expiry_date: str | None = None
    approver: str | None = None
```

`_create_schema` 里 `CREATE TABLE IF NOT EXISTS reviews` 增加 4 列：

```python
                override_status VARCHAR,
                override_reason VARCHAR,
                override_expiry_date DATE,
                approver VARCHAR
```

（放在 `created_at TIMESTAMP NOT NULL` 之后、`)` 之前。）

在同一 `_create_schema` 连接里，紧跟 CREATE 之后加幂等迁移（兼容已有案件库）：

```python
        connection.execute(
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS override_status VARCHAR"
        )
        connection.execute(
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS override_reason VARCHAR"
        )
        connection.execute(
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS override_expiry_date DATE"
        )
        connection.execute(
            "ALTER TABLE reviews ADD COLUMN IF NOT EXISTS approver VARCHAR"
        )
```

`save_review` 的 INSERT 改为 12 列：

```python
                connection.execute(
                    "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        record.review_id,
                        record.case_id,
                        record.decision,
                        record.reviewer,
                        record.reason,
                        record.action,
                        record.next_review_at,
                        record.created_at,
                        record.override_status,
                        record.override_reason,
                        record.override_expiry_date,
                        record.approver,
                    ],
                )
```

新增查询方法（`fetch_reviews` 附近）：

```python
    def fetch_overrides(self) -> QueryResult:
        """返回全部有 override 记录的审核（最新在前）。"""

        return self.fetch(
            """
            SELECT review_id, case_id, decision, reviewer, reason, action,
                   override_status, override_reason, override_expiry_date,
                   approver, next_review_at, created_at
            FROM reviews
            WHERE override_status IS NOT NULL
            ORDER BY created_at DESC
            """
        )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_models.py -k override backend/tests/test_data.py -q`
Expected: 通过；`pytest -q` 全绿。

- [ ] **Step 6: 提交**

```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && git add backend/src/ict_agent/models.py backend/src/ict_agent/data.py backend/tests/test_models.py backend/tests/test_data.py
git commit -m "feat: override audit fields on review request/record and storage

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: 后端服务与端点

**Files:**
- Modify: `backend/src/ict_agent/service.py`
- Modify: `backend/src/ict_agent/api.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 的 `ReviewWrite`/`ReviewRecord`/`fetch_overrides`/`OverrideRecord`。
- Produces: `POST /api/v1/cases/{id}/reviews` 接受 override 字段并写入；`GET /api/v1/insights/overrides` 返回 `{items:[OverrideRecord...]}`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_api.py` 追加：

```python
def test_review_with_override_is_recorded() -> None:
    case = client.get("/api/v1/cases").json()[0]
    payload = {
        "decision": "FALSE_POSITIVE",
        "reviewer": "审计员A",
        "reason": "经核实为误报",
        "override_status": "APPROVED",
        "override_reason": "客户已还款",
        "approver": "风控主管",
    }
    resp = client.post(f"/api/v1/cases/{case['case_id']}/reviews", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["override_status"] == "APPROVED"
    assert body["approver"] == "风控主管"

    overrides = client.get("/api/v1/insights/overrides").json()["items"]
    assert any(o["review_id"] == body["review_id"] and o["override_status"] == "APPROVED" for o in overrides)


def test_insights_overrides_empty_or_list() -> None:
    resp = client.get("/api/v1/insights/overrides")
    assert resp.status_code == 200
    assert "items" in resp.json()
```

（`case` 取首个可用案件；若 `client.get("/api/v1/cases")` 为空，改用 `test_api.py` 现有造数据方式，保持测试可独立。）

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -k override -q`
Expected: FAIL（`/insights/overrides` 404）。

- [ ] **Step 3: service.py**

`review_case` 的 `ReviewWrite(...)` 增加：

```python
            override_status=request.override_status,
            override_reason=request.override_reason,
            override_expiry_date=(
                request.override_expiry_date.isoformat()
                if request.override_expiry_date is not None
                else None
            ),
            approver=request.approver,
```

`ReviewRecord(...)` 返回增加：

```python
            override_status=record.override_status,
            override_reason=record.override_reason,
            override_expiry_date=record.override_expiry_date,
            approver=record.approver,
```

新增服务函数：

```python
def get_insights_overrides(*, settings: Settings | None = None) -> list[dict[str, Any]]:
    runtime_settings = settings or load_settings(require_api_key=False, require_data_dir=False)
    store = CaseStore(runtime_settings.case_database_path)
    rows = store.fetch_overrides().rows
    columns = [
        "review_id", "case_id", "decision", "reviewer", "reason", "action",
        "override_status", "override_reason", "override_expiry_date",
        "approver", "next_review_at", "created_at",
    ]
    return [dict(zip(columns, row)) for row in rows]
```

（`CaseStore` 已 import；`Any` 从 `typing` 导入若未导入。）

- [ ] **Step 4: api.py**

新增（复用 `_open_store` 或直接 `get_insights_overrides()`）：

```python
@app.get("/api/v1/insights/overrides", response_model=ItemsResponse, tags=["insights"])
async def insights_overrides() -> ItemsResponse:
    return ItemsResponse(items=get_insights_overrides())
```

（`ItemsResponse` 已在 P0+P1 定义于 models.py。）

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_api.py -k override -q` → 通过；`pytest -q` 全绿。

- [ ] **Step 6: 提交**

```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && git add backend/src/ict_agent/service.py backend/src/ict_agent/api.py backend/tests/test_api.py
git commit -m "feat: override audit endpoint and review override persistence

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 前端审核表单 override 区

**Files:**
- Modify: `frontend/src/components/CaseWorkspace.vue`

**Interfaces:**
- Consumes: `POST /api/v1/cases/{id}/reviews` 新字段。
- Produces: 审核表单增加「人工 override」区（override_status 下拉 / reason 文本 / expiry 日期 / approver 输入）；`canSubmit` 在 override 开启时要求 reason+approver。

- [ ] **Step 1: 修改脚本**

`CaseWorkspace.vue` 的 `<script setup>`：`form` 增加字段并补充重置：

```js
const form = reactive({ decision: "", reviewer: "", reason: "", action: "", next_review_at: "", override_status: "", override_reason: "", override_expiry_date: "", approver: "" });
const overrideOptions = [
  { title: "不记录 override", value: "" },
  { title: "批准覆盖（APPROVED）", value: "APPROVED" },
  { title: "拒绝覆盖（REJECTED）", value: "REJECTED" },
];
```

`canSubmit` 增加：

```js
const canSubmit = computed(() =>
  form.decision && form.reviewer.trim() && form.reason.trim().length >= 2 &&
  (form.decision !== "MONITOR" || form.next_review_at) &&
  (form.override_status === "" || (form.override_reason.trim().length >= 2 && form.approver.trim()))
);
```

`submitReview` 的 body 增加：

```js
      override_status: form.override_status || null,
      override_reason: form.override_reason.trim() || null,
      override_expiry_date: form.override_expiry_date || null,
      approver: form.approver.trim() || null,
```

提交成功后重置里加上 `override_status: "", override_reason: "", override_expiry_date: "", approver: ""`；`watch` 的路由切换重置也同步加。

- [ ] **Step 2: 修改模板**

在审核表单（`提交人工审核` 按钮之前）插入 override 区：

```html
            <div class="rounded-lg border border-border p-3">
              <span class="mb-2 block text-xs font-semibold text-ink">人工 override（可选）</span>
              <p class="mb-3 text-[11px] leading-5 text-muted">记录对规则命中的人工覆盖，保留原始规则命中以可审计；不要用覆盖来抹掉逾期/超限事实。</p>
              <SelectInput v-model="form.override_status" :options="overrideOptions" />
              <div v-if="form.override_status" class="mt-3 space-y-3">
                <TextArea v-model="form.override_reason" rows="2" maxlength="500" placeholder="override 原因" />
                <div class="flex flex-wrap gap-3">
                  <div class="min-w-[180px] flex-1"><span class="mb-1.5 block text-sm font-medium text-ink">覆盖到期日</span><TextInput v-model="form.override_expiry_date" type="date" /></div>
                  <div class="min-w-[180px] flex-1"><TextInput v-model="form.approver" maxlength="100" placeholder="审批人" /></div>
                </div>
              </div>
            </div>
```

- [ ] **Step 3: 验证**

Run: `cd "D:\作业\aaachagent\ict-agent-fresh\frontend" && npm run build`
Expected: 通过。

- [ ] **Step 4: 提交**

```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && git add frontend/src/components/CaseWorkspace.vue
git commit -m "feat: review form override section

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 前端治理中心 override 审计列表

**Files:**
- Modify: `frontend/src/components/InsightsGovernance.vue`

**Interfaces:**
- Consumes: `GET /api/v1/insights/overrides`。
- Produces: 治理中心下半部分替换 P3 占位为审计列表（时间 / 案件 / 决策 / 审核人 / override 状态 / 原因 / 审批人 / 到期日）。

- [ ] **Step 1: 修改脚本**

`InsightsGovernance.vue` 的 `<script setup>` 增加：

```js
const overrides = ref([]);
const overrideLoading = ref(true);
const overrideError = ref("");

const decisionText = { MONITOR: "持续观察", ACTION_REQUIRED: "需要处置", FALSE_POSITIVE: "确认误报", RESOLVED: "已经解决" };
const overrideBadge = { APPROVED: "success", REJECTED: "warning" };

async function loadOverrides() {
  overrideLoading.value = false;
  try {
    const r = await api("/api/v1/insights/overrides");
    overrides.value = r.items || [];
  } catch (e) {
    overrideError.value = e.message;
  }
}
onMounted(loadOverrides);
```

（`ref` 已在 import；`onMounted` 已 import。）

- [ ] **Step 2: 修改模板**

把原「人工 override 审计记录将在 P3 提供」占位 `<section>` 整体替换为：

```html
    <section class="card overflow-hidden">
      <div class="panel-head">
        <div class="flex items-center gap-2"><span class="section-index">O</span><h3>人工 override 审计</h3></div>
        <span class="subtle-copy">保留原始规则命中 · {{ overrides.length }} 条</span>
      </div>
      <div v-if="overrideError" class="p-4 text-sm text-danger">{{ overrideError }}</div>
      <div class="overflow-x-auto">
        <table class="table-base min-w-[900px]">
          <thead><tr><th>时间</th><th>案件</th><th>审核决定</th><th>审核人</th><th>override</th><th>原因 / 审批人</th><th>到期日</th></tr></thead>
          <tbody>
            <tr v-for="o in overrides" :key="o.review_id">
              <td class="whitespace-nowrap text-xs text-muted">{{ o.created_at }}</td>
              <td><code class="font-mono text-xs text-ink">{{ o.case_id }}</code></td>
              <td><Badge tone="neutral">{{ decisionText[o.decision] || o.decision }}</Badge></td>
              <td class="text-sm text-ink">{{ o.reviewer }}</td>
              <td><Badge :tone="overrideBadge[o.override_status] || 'neutral'">{{ o.override_status }}</Badge></td>
              <td class="text-xs text-muted">{{ o.override_reason || "—" }}<span v-if="o.approver" class="block text-faint">审批人：{{ o.approver }}</span></td>
              <td class="whitespace-nowrap text-xs text-muted">{{ o.override_expiry_date || "—" }}</td>
            </tr>
            <tr v-if="!overrideLoading && !overrides.length"><td colspan="7" class="empty-state">还没有 override 审计记录</td></tr>
          </tbody>
        </table>
      </div>
    </section>
```

- [ ] **Step 3: 验证**

Run: `npm run build`
Expected: 通过。

- [ ] **Step 4: 提交**

```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && git add frontend/src/components/InsightsGovernance.vue
git commit -m "feat: governance override audit list

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: 集成验收

**Files:**
- None（只读验证 + 问题才改）。

**Interfaces:**
- 验证 override 全链路：后端写入/读取 + 前端表单/审计列表。

- [ ] **Step 1: 全量检查**

```bash
cd "D:\作业\aaachagent\ict-agent-fresh"
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format . --check
.venv/Scripts/python.exe -m mypy backend/src
cd frontend && npm run build && cd ..
```
Expected: 全绿。

- [ ] **Step 2: 真实数据链路**

后端在 8000。用 curl 对一个真实案件提交带 override 的审核（数据会写入案件库，先与用户确认再执行；若用户不想动案件库，改用 pytest 链路验证并在报告中注明未做真实写入）：
```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/cases/{case_id}/reviews \
  -H "Content-Type: application/json" \
  -d '{"decision":"FALSE_POSITIVE","reviewer":"验收员","reason":"验收冒烟测试原因","override_status":"APPROVED","override_reason":"验收冒烟","approver":"风控主管"}'
curl -s http://127.0.0.1:8000/api/v1/insights/overrides | python -c "import json,sys; d=json.load(sys.stdin); print('overrides:', len(d['items']))"
```

- [ ] **Step 3: DOM/CDP 冒烟**

无头 Chrome `--dump-dom` `/insights/governance`：含「人工 override 审计」标题与表格（若上一步未真实写入，则显示空态「还没有 override 审计记录」也算通过）。CDP 冒烟：案件工作台审核表单勾选 override 后出现 reason/approver 字段、canSubmit 校验。

- [ ] **Step 4: 修复 + 复核 + 提交**

```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && git add frontend/src frontend/dist backend/
git commit -m "fix: override acceptance fixes
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
注意：只提交本次涉及文件（backend/src、backend/tests、frontend/src、frontend/dist），别带 `*.log`。

- [ ] **Step 5: 收尾报告**

汇报：override 全链路结果、真实写入情况、测试/冒烟结论、遗留问题。

---

## Self-Review

- **Spec 覆盖**：模型/存储（T1）✓；服务/端点（T2）✓；前端表单（T3）✓；治理列表（T4）✓；验收（T5）✓。override 不删规则命中的原则由现有案件流保证（override 只写 reviews，不碰 rule_hits）✓。
- **占位符**：无 TBD；每个代码步骤完整。治理中心 P3 占位被真实列表替换。
- **类型一致性**：`ReviewRequest`→`ReviewWrite`→`reviews` 表→`ReviewRecord`→`OverrideRecord` 字段名一致；`fetch_overrides` 列序与 `OverrideRecord` 字段一一对应；前端 `override_status` 空串表示不记录，后端 `None` 表示无 override。
- **迁移**：`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 幂等，旧数据 override 列为 NULL，读取兼容。
- **已知取舍**：`evidence_json`/`input_timestamp` 由案件库现有 investigation/created_at 记录，不在 reviews 重复冗余存储（口径 §12 字段以可用来源记录）。
