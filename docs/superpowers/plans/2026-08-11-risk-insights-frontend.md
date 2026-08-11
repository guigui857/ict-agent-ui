# 风控洞察 P2（前端视图 + 导航）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 P0+P1 已落地的 `/api/v1/insights/*` 后端端点建立前端视图：新增「风控洞察」导航（客户洞察 / 应收预警 / 库存健康 / 治理中心）+ 客户详情 + 经营分析时序增强。全部 Tailwind + ApexCharts，沿用已迁移 UI 体系。

**Architecture:** 纯前端。`router.js` 加 `/insights/*` 路由与导航项，`App.vue` 的 `isActive` 兼容 `/insights` 前缀；新增 6 个视图组件（扁平放 `components/`，与现有风格一致）；每个视图用 `lib.js` 的 `api()` 拉取对应 insights 端点，ApexCharts 渲染。不新增后端端点（override 审计是 P3）。

**Tech Stack:** Vue 3.5、vue-router 4、Tailwind CSS 4、lucide-vue-next、vue3-apexcharts、`lib.js` 的 `api`/`formatMoney`/`formatPercent`。

**工作目录约定：** 前端命令在 `D:\作业\aaachagent\ict-agent-fresh\frontend` 下运行（`npm run build`）；后端已在 `http://127.0.0.1:8000` 运行（若没在跑，用 `.venv/Scripts/python.exe -m uvicorn ict_agent.api:app --app-dir backend/src --host 127.0.0.1 --port 8000`）。

## Global Constraints

- 数据只来自 `/api/v1/insights/*` 已冻结端点，页面不得新造口径或硬编码公式。
- 端点契约（P0+P1 已冻结）：
  - `customers` → `{items:[{customer_id,customer_name,gross_profit,v_score,r_score,v_tier,r_tier,hard_overlay,warning_state,grid}]}`
  - `customers/{id}` → `{customer_id,customer_name,scores,warning_state,extensions{explicit_count,date_reset_count,rollover_suspected_count,earliest,latest},credit_triggers{increase_signals,decrease_signals,stop_signals},action_tier}`
  - `ar-aging` → `{items:[{period,bucket,amount}]}`，bucket ∈ `[0,1-30,31-60,61-90,90+]`
  - `inventory-aging` → `{items:[{quarter,bucket,amount}]}`，bucket ∈ `[<=90,91-180,181-365,>365]`，**序为字典序需前端重排**
  - `extension-heatmap` → `{items:[{customer_id,month,count}]}`（注意 key 是 `count` 不是 `days`）
  - `inventory-economic` → `{items:[{bucket,margin}]}`
  - `revenue-trend` → `{items:[{month,revenue,gross_profit,cm2}]}`（`cm2` 当前与 `gross_profit` 相同，图表只显示毛利一条，不重复叠加）
  - `vintage` → `{items:[{cohort,elapsed,overdue_rate}]}`（`elapsed` 是每批客户数，**不当作经过月数**；按批次逾期率渲染）
  - `actions` → `{items:[{entity_id,entity_name,side,tier,warning_state,reasons[],v_tier,r_tier}]}`
- 金额显示用 `formatMoney`（元/万元/亿元）；比例用 `formatPercent`。
- 客户列表的 `warning_state` 是粗 DPD 快照，详情是权威版 —— 详情页用详情的状态。
- 四级动作色：GREEN 绿 / YELLOW 黄 / ORANGE 橙 / RED 红（Tailwind 语义色 success/warning/orange-600/danger）。
- 前端无测试框架，验收 = `npm run build` + grep + 无头截图 + CDP 冒烟。
- 不引入 TypeScript / Pinia / 暗色模式；不改后端。

---

### Task 1: 路由、导航与壳集成

**Files:**
- Modify: `src/router.js`
- Modify: `src/App.vue`

**Interfaces:**
- Produces: 导航新增「风控洞察」（lucide `ShieldCheck`，路径 `/insights/customers`）；路由 `/insights/customers`、`/insights/customers/:customerId`、`/insights/ar`、`/insights/inventory`、`/insights/governance`；App.vue `isActive` 对 `/insights/customers` 前缀生效（`/insights/*` 都高亮）。后续任务只需往 `components/` 加组件文件。

- [ ] **Step 1: 改 router.js**

将 `src/router.js` 顶部改为：

```js
import { createRouter, createWebHistory } from "vue-router";
import { ChartLine, LayoutDashboard, ListTodo, ShieldCheck } from "lucide-vue-next";
import RiskOverview from "./components/RiskOverview.vue";
import CaseQueue from "./components/CaseQueue.vue";
import BusinessView from "./components/BusinessView.vue";
import CaseWorkspace from "./components/CaseWorkspace.vue";
import InsightsCustomers from "./components/InsightsCustomers.vue";
import InsightsCustomerDetail from "./components/InsightsCustomerDetail.vue";
import InsightsAr from "./components/InsightsAr.vue";
import InsightsInventory from "./components/InsightsInventory.vue";
import InsightsGovernance from "./components/InsightsGovernance.vue";

export const navItems = [
  { path: "/risk", label: "风险总览", icon: LayoutDashboard },
  { path: "/cases", label: "案件队列", icon: ListTodo },
  { path: "/insights/customers", label: "风控洞察", icon: ShieldCheck },
  { path: "/business", label: "经营分析", icon: ChartLine },
];
```

在 `routes` 数组里（`/business` 路由之前）插入：

```js
    { path: "/insights/customers", name: "insights-customers", component: InsightsCustomers, meta: { title: "客户洞察" } },
    { path: "/insights/customers/:customerId", name: "insights-customer", component: InsightsCustomerDetail, meta: { title: "客户详情" } },
    { path: "/insights/ar", name: "insights-ar", component: InsightsAr, meta: { title: "应收预警" } },
    { path: "/insights/inventory", name: "insights-inventory", component: InsightsInventory, meta: { title: "库存健康" } },
    { path: "/insights/governance", name: "insights-governance", component: InsightsGovernance, meta: { title: "治理中心" } },
```

- [ ] **Step 2: 改 App.vue 的 isActive**

`src/App.vue` 的 `isActive` 函数改为：

```js
function isActive(path) {
  if (path === "/cases") return route.path.startsWith("/cases");
  if (path === "/insights/customers") return route.path.startsWith("/insights");
  return route.path === path;
}
```

- [ ] **Step 3: 建空壳组件（占位，后续任务填充）**

为让 build 先通过，Task 2–6 会逐个实现；本步可先不建组件，等 Task 2 起逐个添加（router 引用先于组件存在会导致 build 失败）。因此本任务与 Task 2 必须同批：**先跑 Task 2–6 的组件，再统一 build**。为便于推进，本步跳过，Task 2 起逐个建文件后 build。

- [ ] **Step 4: 提交（等 Task 2–6 组件建好后，由最后一个视图任务统一提交 router+App+组件）**

提交说明：本任务代码在最后一个视图任务（Task 6）的提交里一并包含，避免中间态 build 失败。若你按顺序执行，Task 1 只改 router.js 与 App.vue 并**先不 build**，随 Task 6 一起验证。

---

### Task 2: InsightsCustomers.vue — 客户洞察（九宫格热力图 + 客户列表）

**Files:**
- Create: `src/components/InsightsCustomers.vue`

**Interfaces:**
- Consumes: `GET /api/v1/insights/customers` 与 `GET /api/v1/insights/actions`（action_tier 来自 actions 按 entity_id 映射）。
- Produces: 顶部九宫格热力图（V 档 × R 档计数值）+ 客户列表（名称 / V / R / 档位 / 预警状态 / 四级动作 / 网格）；行点击跳 `/insights/customers/:id`。

- [ ] **Step 1: 创建组件**

新建 `src/components/InsightsCustomers.vue`：

```vue
<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import VueApexCharts from "vue3-apexcharts";
import { ArrowRight, ShieldAlert } from "lucide-vue-next";
import Badge from "./ui/Badge.vue";
import { api, formatMoney } from "../lib";

const router = useRouter();
const customers = ref([]);
const actions = ref([]);
const loading = ref(true);
const error = ref("");

const tierBadge = {
  GREEN: "success", YELLOW: "warning", ORANGE: "warning", RED: "danger",
};
const stateBadge = {
  NOT_DUE: "success", PRE_DUE: "info", DPD_1_PLUS: "warning", DPD_30_PLUS: "warning",
  DPD_60_PLUS: "warning", DPD_90_REVIEW: "danger", HIGH_WATCH_BUT_NOT_DEFAULT: "danger", INDIVIDUAL_ECL: "danger",
};
const vLabel = { high: "高价值", mid: "中价值", low: "低价值" };
const rLabel = { high: "高风险", mid: "中风险", low: "低风险" };

const actionByCustomer = computed(() =>
  Object.fromEntries(actions.value.map((a) => [a.entity_id, a]))
);

const gridCounts = computed(() => {
  const counts = {};
  for (const c of customers.value) counts[c.grid] = (counts[c.grid] || 0) + 1;
  const series = [];
  for (const v of ["high", "mid", "low"]) {
    series.push({
      name: vLabel[v],
      data: ["high", "mid", "low"].map((r) => ({
        x: rLabel[r],
        y: counts[`value_${v}_risk_${r}`] || 0,
      })),
    });
  }
  return series;
});
const gridOptions = computed(() => ({
  chart: { type: "heatmap", toolbar: { show: false }, fontFamily: "DM Sans, 'Microsoft YaHei', sans-serif" },
  plotOptions: {
    heatmap: {
      colorScale: {
        ranges: [
          { from: 0, to: 2, color: "#eef4ff" },
          { from: 3, to: 8, color: "#a3afff" },
          { from: 9, to: 30, color: "#465fff" },
          { from: 31, to: 999, color: "#2e3fe0" },
        ],
      },
    },
  },
  dataLabels: { enabled: true, style: { colors: ["#101828"], fontSize: "12px", fontWeight: 600 } },
  legend: { show: false },
  xaxis: { labels: { style: { colors: "#667085", fontSize: "12px" } } },
  yaxis: { labels: { style: { colors: "#667085", fontSize: "12px" } } },
  tooltip: { y: { title: { formatter: (seriesName) => seriesName } } },
}));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [c, a] = await Promise.all([api("/api/v1/insights/customers"), api("/api/v1/insights/actions")]);
    customers.value = c.items || [];
    actions.value = a.items || [];
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function openCustomer(id) {
  router.push(`/insights/customers/${encodeURIComponent(id)}`);
}
</script>

<template>
  <div class="space-y-5">
    <div class="section-intro flex items-end justify-between gap-6">
      <div><span class="eyebrow">CUSTOMER INSIGHTS</span><h2>客户价值 — 风险九宫格</h2></div>
      <p>V 价值分 × R 风险分按客户分布三分位切档；硬覆盖（黑名单/失信）直接进高风险格。</p>
    </div>

    <div v-if="error" class="card p-4 text-sm text-danger">{{ error }}</div>

    <section class="card p-5">
      <div class="panel-head">
        <div class="flex items-center gap-2"><span class="section-index">V·R</span><h3>九宫格分布</h3></div>
        <span class="subtle-copy">{{ customers.length }} 家授信客户</span>
      </div>
      <div class="pt-4">
        <VueApexCharts v-if="!loading" type="heatmap" height="260" :options="gridOptions" :series="gridCounts" />
      </div>
    </section>

    <section class="card overflow-hidden">
      <div class="panel-head">
        <div class="flex items-center gap-2"><span class="section-index">A</span><h3>客户清单</h3></div>
        <span class="subtle-copy">点击进入客户详情</span>
      </div>
      <div class="overflow-x-auto">
        <table class="table-base min-w-[1000px]">
          <thead><tr><th>客户</th><th>价值分</th><th>风险分</th><th>九宫格</th><th>预警状态</th><th>四级动作</th></tr></thead>
          <tbody>
            <tr v-for="c in customers" :key="c.customer_id" tabindex="0" @click="openCustomer(c.customer_id)" @keydown.enter="openCustomer(c.customer_id)">
              <td><strong class="block text-[13px] text-ink">{{ c.customer_name }}</strong><small class="block text-xs text-muted">{{ c.customer_id }}</small></td>
              <td class="money-cell">{{ c.v_score.toFixed(1) }}</td>
              <td class="money-cell">{{ c.r_score.toFixed(1) }}</td>
              <td><Badge tone="neutral">{{ vLabel[c.v_tier] }} · {{ rLabel[c.r_tier] }}</Badge></td>
              <td><Badge :tone="stateBadge[c.warning_state] || 'neutral'">{{ c.warning_state }}</Badge></td>
              <td>
                <Badge :tone="tierBadge[actionByCustomer[c.customer_id]?.tier] || 'neutral'">
                  {{ actionByCustomer[c.customer_id]?.tier || "—" }}
                </Badge>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
```

- [ ] **Step 2: 验证**

Run: `cd "D:\作业\aaachagent\ict-agent-fresh\frontend" && npm run build`
Expected: build 通过（若报 `InsightsCustomerDetail/InsightsAr/...` 组件缺失，说明 Task 1 的路由引用了尚未创建的文件——按计划 Task 1 与 2–6 同批，允许此刻 build 失败，最终由 Task 6 收口；若只缺本文件则已通过）。

---

### Task 3: InsightsCustomerDetail.vue — 客户详情

**Files:**
- Create: `src/components/InsightsCustomerDetail.vue`

**Interfaces:**
- Consumes: `GET /api/v1/insights/customers/{id}`（权威 `warning_state`/`extensions`/`credit_triggers`/`action_tier`）。
- Produces: 返回按钮 + 评分卡（V/R/档位/网格）+ 预警状态徽章 + 展期识别 4 项 + 授信触发 3 组 + 四级动作。

- [ ] **Step 1: 创建组件**

```vue
<script setup>
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowLeft, CalendarDays, CodeXml, ShieldAlert, Wallet } from "lucide-vue-next";
import Badge from "./ui/Badge.vue";
import { api } from "../lib";

const route = useRoute();
const router = useRouter();
const detail = ref(null);
const loading = ref(true);
const error = ref("");

const stateBadge = {
  NOT_DUE: "success", PRE_DUE: "info", DPD_1_PLUS: "warning", DPD_30_PLUS: "warning",
  DPD_60_PLUS: "warning", DPD_90_REVIEW: "danger", HIGH_WATCH_BUT_NOT_DEFAULT: "danger", INDIVIDUAL_ECL: "danger",
};
const tierBadge = { GREEN: "success", YELLOW: "warning", ORANGE: "warning", RED: "danger" };
const tierText = { GREEN: "绿色·持续监测", YELLOW: "黄色·预警区", ORANGE: "橙色·联合审批", RED: "红色·即时升级" };

async function load(id) {
  loading.value = true;
  error.value = "";
  try {
    detail.value = await api(`/api/v1/insights/customers/${encodeURIComponent(id)}`);
  } catch (e) {
    error.value = e.message;
    detail.value = null;
  } finally {
    loading.value = false;
  }
}
watch(() => route.params.customerId, (id) => { if (id) load(id); }, { immediate: true });

const scores = computed(() => detail.value?.scores || {});
</script>

<template>
  <div class="space-y-5">
    <header class="flex items-center gap-3">
      <button type="button" class="grid h-10 w-10 place-items-center rounded-lg border border-border text-muted transition-colors hover:bg-canvas" aria-label="返回客户洞察" @click="router.push('/insights/customers')">
        <ArrowLeft :size="18" />
      </button>
      <div>
        <span class="eyebrow">CUSTOMER DETAIL</span>
        <h2 class="text-xl font-bold text-ink">{{ detail?.customer_name || "客户详情" }}</h2>
      </div>
      <div v-if="detail" class="ml-auto flex items-center gap-2">
        <Badge :tone="tierBadge[detail.action_tier] || 'neutral'">{{ tierText[detail.action_tier] || detail.action_tier }}</Badge>
        <Badge :tone="stateBadge[detail.warning_state] || 'neutral'">{{ detail.warning_state }}</Badge>
      </div>
    </header>

    <div v-if="loading" class="card p-8 text-center text-muted">加载中…</div>
    <div v-else-if="error" class="card p-8 text-center">
      <ShieldAlert :size="40" class="mx-auto mb-2 text-danger" />
      <h3 class="text-lg font-bold text-ink">客户加载失败</h3>
      <p class="mt-1 text-sm text-muted">{{ error }}</p>
      <button type="button" class="mt-4 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark" @click="router.push('/insights/customers')">返回客户洞察</button>
    </div>

    <template v-else-if="detail">
      <div class="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <section class="card min-h-[120px] p-5">
          <span class="block text-xs text-muted">价值分 V</span>
          <strong class="mt-1 block text-[26px] leading-tight text-ink">{{ scores.v_score?.toFixed?.(1) ?? scores.v_score ?? "—" }}</strong>
          <small class="mt-1 block text-[11px] text-faint">{{ scores.v_tier }} 档</small>
        </section>
        <section class="card min-h-[120px] p-5">
          <span class="block text-xs text-muted">风险分 R</span>
          <strong class="mt-1 block text-[26px] leading-tight text-ink">{{ scores.r_score?.toFixed?.(1) ?? scores.r_score ?? "—" }}</strong>
          <small class="mt-1 block text-[11px] text-faint">{{ scores.r_tier }} 档{{ scores.hard_overlay ? " · 硬覆盖" : "" }}</small>
        </section>
        <section class="card min-h-[120px] p-5">
          <span class="block text-xs text-muted">九宫格</span>
          <strong class="mt-1 block text-[22px] leading-tight text-ink">{{ scores.grid || "—" }}</strong>
          <small class="mt-1 block text-[11px] text-faint">{{ scores.customer_name }}</small>
        </section>
        <section class="card min-h-[120px] p-5">
          <span class="block text-xs text-muted">预警状态机</span>
          <strong class="mt-1 block text-[22px] leading-tight text-ink">{{ detail.warning_state }}</strong>
          <small class="mt-1 block text-[11px] text-faint">详情为权威口径</small>
        </section>
      </div>

      <div class="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <section class="card p-5">
          <div class="flex items-center gap-2"><span class="section-index">E</span><h3 class="text-[15px] font-bold text-ink">展期识别</h3></div>
          <div class="mt-3 space-y-2 text-sm">
            <div class="flex justify-between"><span class="text-muted">显性展期</span><strong class="text-ink">{{ detail.extensions.explicit_count }} 次</strong></div>
            <div class="flex justify-between"><span class="text-muted">无记录改期（内控红）</span><strong class="text-danger">{{ detail.extensions.date_reset_count }} 次</strong></div>
            <div class="flex justify-between"><span class="text-muted">疑似滚动（人工调查）</span><strong class="text-warning-deep">{{ detail.extensions.rollover_suspected_count }} 次</strong></div>
            <div class="flex justify-between"><span class="text-muted">最早 / 最新展期</span><strong class="text-ink">{{ detail.extensions.earliest || "—" }} / {{ detail.extensions.latest || "—" }}</strong></div>
          </div>
        </section>

        <section class="card p-5">
          <div class="flex items-center gap-2"><span class="section-index">C</span><h3 class="text-[15px] font-bold text-ink">授信调整触发</h3></div>
          <div class="mt-3 space-y-3 text-sm">
            <div>
              <strong class="text-xs text-success-deep">升额信号</strong>
              <ul class="mt-1 list-disc pl-5 text-muted"><li v-for="s in detail.credit_triggers.increase_signals" :key="s">{{ s }}</li><li v-if="!detail.credit_triggers.increase_signals.length">无</li></ul>
            </div>
            <div>
              <strong class="text-xs text-warning-deep">降额/缩账期信号</strong>
              <ul class="mt-1 list-disc pl-5 text-muted"><li v-for="s in detail.credit_triggers.decrease_signals" :key="s">{{ s }}</li><li v-if="!detail.credit_triggers.decrease_signals.length">无</li></ul>
            </div>
            <div>
              <strong class="text-xs text-danger">停供信号（硬事实）</strong>
              <ul class="mt-1 list-disc pl-5 text-muted"><li v-for="s in detail.credit_triggers.stop_signals" :key="s">{{ s }}</li><li v-if="!detail.credit_triggers.stop_signals.length">无</li></ul>
            </div>
          </div>
        </section>

        <section class="card p-5">
          <div class="flex items-center gap-2"><span class="section-index">A</span><h3 class="text-[15px] font-bold text-ink">四级动作</h3></div>
          <div class="mt-3">
            <Badge :tone="tierBadge[detail.action_tier] || 'neutral'">{{ tierText[detail.action_tier] || detail.action_tier }}</Badge>
            <p class="mt-3 text-[13px] leading-6 text-muted">动作档位由预警状态、展期次数、毛利与硬事实确定性计算得出，仅供人工处置参考，不自动执行任何业务动作。</p>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
```

- [ ] **Step 2: 验证**

Run: `npm run build`
Expected: 本组件编译通过（其余 insights 组件缺失属预期，最终 Task 6 收口）。

---

### Task 4: InsightsAr.vue — 应收预警

**Files:**
- Create: `src/components/InsightsAr.vue`

**Interfaces:**
- Consumes: `ar-aging`、`extension-heatmap`、`vintage`、`customers`。
- Produces: 账龄结构堆叠条形图（月×DPD档）、展期热力图（Top N 客户×月，用 `count`）、Vintage 批次逾期率、预警状态分布列表。

- [ ] **Step 1: 创建组件**

```vue
<script setup>
import { computed, onMounted, ref } from "vue";
import VueApexCharts from "vue3-apexcharts";
import { useRouter } from "vue-router";
import Badge from "./ui/Badge.vue";
import { api, formatMoney, formatPercent } from "../lib";

const router = useRouter();
const aging = ref([]);
const extHeat = ref([]);
const vintage = ref([]);
const customers = ref([]);
const loading = ref(true);
const error = ref("");

const AGING_BUCKETS = ["0", "1-30", "31-60", "61-90", "90+"];
const stateBadge = {
  NOT_DUE: "success", PRE_DUE: "info", DPD_1_PLUS: "warning", DPD_30_PLUS: "warning",
  DPD_60_PLUS: "warning", DPD_90_REVIEW: "danger", HIGH_WATCH_BUT_NOT_DEFAULT: "danger", INDIVIDUAL_ECL: "danger",
};

const agingSeries = computed(() =>
  AGING_BUCKETS.map((b) => ({
    name: `${b} 天`,
    data: aging.value.filter((r) => r.bucket === b).map((r) => ({ x: r.period, y: r.amount })),
  }))
);
const agingOptions = computed(() => ({
  chart: { type: "bar", stacked: true, toolbar: { show: false }, fontFamily: "DM Sans, 'Microsoft YaHei', sans-serif" },
  plotOptions: { bar: { columnWidth: "55%" } },
  colors: ["#eef4ff", "#a3afff", "#465fff", "#f79009", "#d92d20"],
  dataLabels: { enabled: false },
  legend: { position: "top", horizontalAlign: "right", fontSize: "12px", labels: { colors: "#667085" } },
  xaxis: { labels: { style: { colors: "#98a2b3", fontSize: "11px" } } },
  yaxis: { labels: { formatter: (v) => (Math.abs(v) >= 100000000 ? (v / 100000000).toFixed(1) + "亿" : v >= 10000 ? (v / 10000).toFixed(0) + "万" : v), style: { colors: "#98a2b3", fontSize: "11px" } } },
  grid: { borderColor: "#e4e7ec", strokeDashArray: 3 },
  tooltip: { y: { formatter: (value) => formatMoney(value) } },
}));

// 展期热力图：取展期次数最多的前 12 客户
const topExtensionCustomers = computed(() => {
  const total = {};
  for (const r of extHeat.value) total[r.customer_id] = (total[r.customer_id] || 0) + r.count;
  return Object.entries(total).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([id]) => id);
});
const extSeries = computed(() => {
  const byCustomer = {};
  for (const r of extHeat.value) {
    if (!topExtensionCustomers.value.includes(r.customer_id)) continue;
    (byCustomer[r.customer_id] ||= []).push({ x: r.month, y: r.count });
  }
  return Object.entries(byCustomer).map(([id, data]) => ({ name: id, data }));
});
const extOptions = computed(() => ({
  chart: { type: "heatmap", toolbar: { show: false }, fontFamily: "DM Sans, 'Microsoft YaHei', sans-serif" },
  plotOptions: { heatmap: { colorScale: { ranges: [{ from: 0, to: 1, color: "#eef4ff" }, { from: 2, to: 5, color: "#a3afff" }, { from: 6, to: 999, color: "#465fff" }] } } },
  dataLabels: { enabled: false },
  legend: { show: false },
  xaxis: { labels: { style: { colors: "#98a2b3", fontSize: "10px" } } },
  yaxis: { labels: { style: { colors: "#667085", fontSize: "10px" } } },
}));

const vintageSeries = computed(() => [{ name: "批次逾期率", data: vintage.value.map((r) => ({ x: r.cohort, y: r.overdue_rate == null ? null : r.overdue_rate * 100 })) }]);
const vintageOptions = computed(() => ({
  chart: { type: "bar", toolbar: { show: false }, fontFamily: "DM Sans, 'Microsoft YaHei', sans-serif" },
  plotOptions: { bar: { columnWidth: "60%" } },
  colors: ["#465fff"],
  dataLabels: { enabled: false },
  xaxis: { labels: { style: { colors: "#98a2b3", fontSize: "11px" } } },
  yaxis: { labels: { formatter: (v) => v + "%", style: { colors: "#98a2b3", fontSize: "11px" } } },
  grid: { borderColor: "#e4e7ec", strokeDashArray: 3 },
  tooltip: { y: { formatter: (v) => formatPercent(v / 100) } },
}));

const stateDist = computed(() => {
  const dist = {};
  for (const c of customers.value) dist[c.warning_state] = (dist[c.warning_state] || 0) + 1;
  return Object.entries(dist).sort((a, b) => b[1] - a[1]);
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [ag, eh, vt, cs] = await Promise.all([
      api("/api/v1/insights/ar-aging"),
      api("/api/v1/insights/extension-heatmap"),
      api("/api/v1/insights/vintage"),
      api("/api/v1/insights/customers"),
    ]);
    aging.value = ag.items || [];
    extHeat.value = eh.items || [];
    vintage.value = vt.items || [];
    customers.value = cs.items || [];
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div class="space-y-5">
    <div class="section-intro flex items-end justify-between gap-6">
      <div><span class="eyebrow">AR WARNING</span><h2>应收预警</h2></div>
      <p>账龄结构、展期热力图与批次逾期率；预警状态以客户详情为权威口径。</p>
    </div>

    <div v-if="error" class="card p-4 text-sm text-danger">{{ error }}</div>

    <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <section class="card">
        <div class="panel-head"><div class="flex items-center gap-2"><span class="section-index">A</span><h3>应收账龄结构</h3></div><span class="subtle-copy">月 × DPD 档</span></div>
        <div class="px-5 pt-4"><VueApexCharts v-if="!loading" type="bar" height="280" :options="agingOptions" :series="agingSeries" /></div>
      </section>
      <section class="card">
        <div class="panel-head"><div class="flex items-center gap-2"><span class="section-index">E</span><h3>展期热力图</h3></div><span class="subtle-copy">Top 12 客户 × 月（次数）</span></div>
        <div class="px-5 pt-4"><VueApexCharts v-if="!loading" type="heatmap" height="280" :options="extOptions" :series="extSeries" /></div>
      </section>
    </div>

    <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <section class="card">
        <div class="panel-head"><div class="flex items-center gap-2"><span class="section-index">V</span><h3>批次逾期率（Vintage 近似）</h3></div></div>
        <div class="px-5 pt-4"><VueApexCharts v-if="!loading" type="bar" height="260" :options="vintageOptions" :series="vintageSeries" /></div>
      </section>
      <section class="card">
        <div class="panel-head"><div class="flex items-center gap-2"><span class="section-index">S</span><h3>预警状态分布</h3></div></div>
        <div class="space-y-2 p-5">
          <button v-for="[state, count] in stateDist" :key="state" type="button" class="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2.5 text-left transition-colors hover:bg-canvas" @click="router.push('/insights/customers')">
            <Badge :tone="stateBadge[state] || 'neutral'">{{ state }}</Badge>
            <strong class="text-sm text-ink">{{ count }} 家</strong>
          </button>
          <div v-if="!stateDist.length" class="empty-state">暂无客户数据</div>
        </div>
      </section>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 验证**

Run: `npm run build`
Expected: 本组件编译通过。

---

### Task 5: InsightsInventory.vue — 库存健康

**Files:**
- Create: `src/components/InsightsInventory.vue`

**Interfaces:**
- Consumes: `inventory-aging`、`inventory-economic`。
- Produces: 库龄堆叠条形图（季度×库龄层，**按口径重排桶序**）+ 库龄×预计毛利条形图（margin 为 null 显示「无销售匹配」）。

- [ ] **Step 1: 创建组件**

```vue
<script setup>
import { computed, onMounted, ref } from "vue";
import VueApexCharts from "vue3-apexcharts";
import { api, formatMoney, formatPercent } from "../lib";

const aging = ref([]);
const economic = ref([]);
const loading = ref(true);
const error = ref("");

// 库龄桶按口径语义排序（不是字典序）
const BUCKET_ORDER = ["<=90", "91-180", "181-365", ">365"];
const economicBucketOrder = [...BUCKET_ORDER];

const agingSeries = computed(() =>
  BUCKET_ORDER.map((b) => ({
    name: `${b} 天`,
    data: aging.value.filter((r) => r.bucket === b).map((r) => ({ x: r.quarter, y: r.amount })),
  }))
);
const agingOptions = computed(() => ({
  chart: { type: "bar", stacked: true, toolbar: { show: false }, fontFamily: "DM Sans, 'Microsoft YaHei', sans-serif" },
  plotOptions: { bar: { columnWidth: "55%" } },
  colors: ["#eef4ff", "#a3afff", "#f79009", "#d92d20"],
  dataLabels: { enabled: false },
  legend: { position: "top", horizontalAlign: "right", fontSize: "12px", labels: { colors: "#667085" } },
  xaxis: { labels: { style: { colors: "#98a2b3", fontSize: "11px" } } },
  yaxis: { labels: { formatter: (v) => (Math.abs(v) >= 100000000 ? (v / 100000000).toFixed(1) + "亿" : v >= 10000 ? (v / 10000).toFixed(0) + "万" : v), style: { colors: "#98a2b3", fontSize: "11px" } } },
  grid: { borderColor: "#e4e7ec", strokeDashArray: 3 },
  tooltip: { y: { formatter: (value) => formatMoney(value) } },
}));

const economicData = computed(() =>
  economicBucketOrder.map((b) => ({ x: `${b} 天`, y: economic.value.find((r) => r.bucket === b)?.margin }))
);
const economicOptions = computed(() => ({
  chart: { type: "bar", toolbar: { show: false }, fontFamily: "DM Sans, 'Microsoft YaHei', sans-serif" },
  plotOptions: { bar: { columnWidth: "55%" } },
  colors: ["#465fff"],
  dataLabels: { enabled: false },
  xaxis: { labels: { style: { colors: "#667085", fontSize: "12px" } } },
  yaxis: { labels: { formatter: (v) => formatMoney(v), style: { colors: "#98a2b3", fontSize: "11px" } } },
  grid: { borderColor: "#e4e7ec", strokeDashArray: 3 },
  tooltip: { y: { formatter: (value) => (value == null ? "无销售匹配" : formatMoney(value)) } },
}));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [ag, ec] = await Promise.all([api("/api/v1/insights/inventory-aging"), api("/api/v1/insights/inventory-economic")]);
    aging.value = ag.items || [];
    economic.value = ec.items || [];
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div class="space-y-5">
    <div class="section-intro flex items-end justify-between gap-6">
      <div><span class="eyebrow">INVENTORY HEALTH</span><h2>库存健康</h2></div>
      <p>库龄结构与库龄×毛利经济性；库存无客户维度，仅按物料编码与销售有限关联。</p>
    </div>

    <div v-if="error" class="card p-4 text-sm text-danger">{{ error }}</div>

    <section class="card">
      <div class="panel-head"><div class="flex items-center gap-2"><span class="section-index">I</span><h3>库龄结构</h3></div><span class="subtle-copy">季末快照 × 库龄层</span></div>
      <div class="px-5 pt-4"><VueApexCharts v-if="!loading" type="bar" height="300" :options="agingOptions" :series="agingSeries" /></div>
    </section>

    <section class="card">
      <div class="panel-head"><div class="flex items-center gap-2"><span class="section-index">E</span><h3>库龄 × 预计毛利</h3></div><span class="subtle-copy">高龄低毛利 SKU 风险</span></div>
      <div class="px-5 pt-4"><VueApexCharts v-if="!loading" type="bar" height="280" :options="economicOptions" :series="[{ name: "平均含税粗算毛利", data: economicData }]" /></div>
    </section>
  </div>
</template>
```

- [ ] **Step 2: 验证**

Run: `npm run build`
Expected: 本组件编译通过。

---

### Task 6: InsightsGovernance.vue — 治理中心

**Files:**
- Create: `src/components/InsightsGovernance.vue`

**Interfaces:**
- Consumes: `GET /api/v1/insights/actions`（四级动作队列）。
- Produces: 按严重度排序的动作队列表格（主体/动作档/预警状态/理由/价值风险档）。override 审计记录为 P3，本页留「P3 提供」占位说明。

- [ ] **Step 1: 创建组件**

```vue
<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ShieldCheck } from "lucide-vue-next";
import Badge from "./ui/Badge.vue";
import { api } from "../lib";

const router = useRouter();
const items = ref([]);
const loading = ref(true);
const error = ref("");

const tierBadge = { GREEN: "success", YELLOW: "warning", ORANGE: "warning", RED: "danger" };
const tierText = { GREEN: "绿色·持续监测", YELLOW: "黄色·预警区", ORANGE: "橙色·联合审批", RED: "红色·即时升级" };
const stateBadge = {
  NOT_DUE: "success", PRE_DUE: "info", DPD_1_PLUS: "warning", DPD_30_PLUS: "warning",
  DPD_60_PLUS: "warning", DPD_90_REVIEW: "danger", HIGH_WATCH_BUT_NOT_DEFAULT: "danger", INDIVIDUAL_ECL: "danger",
};

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const r = await api("/api/v1/insights/actions");
    items.value = r.items || [];
  } catch (e) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <div class="space-y-5">
    <div class="section-intro flex items-end justify-between gap-6">
      <div><span class="eyebrow">GOVERNANCE</span><h2>治理中心 · 四级动作队列</h2></div>
      <p>红→橙→黄→绿 排序；四级动作只做提醒与审批分级，不自动执行任何业务处置。</p>
    </div>

    <div v-if="error" class="card p-4 text-sm text-danger">{{ error }}</div>

    <section class="card overflow-hidden">
      <div class="panel-head">
        <div class="flex items-center gap-2"><span class="section-index">Q</span><h3>动作队列</h3></div>
        <span class="subtle-copy">应收侧 · {{ items.length }} 条</span>
      </div>
      <div class="overflow-x-auto">
        <table class="table-base min-w-[900px]">
          <thead><tr><th>主体</th><th>四级动作</th><th>预警状态</th><th>触发理由</th><th>价值 / 风险</th></tr></thead>
          <tbody>
            <tr v-for="item in items" :key="item.entity_id" tabindex="0" @click="router.push(`/insights/customers/${encodeURIComponent(item.entity_id)}`)" @keydown.enter="router.push(`/insights/customers/${encodeURIComponent(item.entity_id)}`)">
              <td><strong class="block text-[13px] text-ink">{{ item.entity_name }}</strong><small class="block text-xs text-muted">{{ item.entity_id }}</small></td>
              <td><Badge :tone="tierBadge[item.tier] || 'neutral'">{{ tierText[item.tier] || item.tier }}</Badge></td>
              <td><Badge :tone="stateBadge[item.warning_state] || 'neutral'">{{ item.warning_state }}</Badge></td>
              <td class="text-xs text-muted">{{ item.reasons.join(" · ") }}</td>
              <td class="text-xs text-muted">{{ item.v_tier }} / {{ item.r_tier }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card p-4">
      <div class="flex items-start gap-3">
        <ShieldCheck :size="18" class="mt-0.5 flex-none text-muted" />
        <p class="text-xs leading-5 text-muted"><strong class="text-ink">人工 override 审计记录</strong>将在 P3 提供（保留原始规则命中 + override 状态/原因/到期日/审批人，防“反复覆盖形成永不逾期假象”）。</p>
      </div>
    </section>
  </div>
</template>
```

- [ ] **Step 2: 全量 build 收口**

Run: `cd "D:\作业\aaachagent\ict-agent-fresh\frontend" && npm run build`
Expected: **全部通过**（Task 1–6 的组件齐了）。若仍有报错，按报错修正（多为 import 或未定义变量）。

- [ ] **Step 3: 提交（本任务同时收口 Task 1–5 的路由+App+组件）**

```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && git add frontend/src/router.js frontend/src/App.vue frontend/src/components/InsightsCustomers.vue frontend/src/components/InsightsCustomerDetail.vue frontend/src/components/InsightsAr.vue frontend/src/components/InsightsInventory.vue frontend/src/components/InsightsGovernance.vue frontend/dist
git commit -m "feat: risk-insights frontend views (customer grid, AR warning, inventory health, governance) + nav

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: 经营分析时序增强

**Files:**
- Modify: `src/components/BusinessView.vue`

**Interfaces:**
- Consumes: `GET /api/v1/insights/revenue-trend`。
- Produces: 在现有指标卡与应收趋势之间插入「销售额 / 含税粗算毛利」月度时序面积图（`cm2` 与毛利当前相同，不重复叠加）。

- [ ] **Step 1: 修改 BusinessView.vue**

在 `src/components/BusinessView.vue` 的 `<script setup>` 追加（现有 import 保持）：

```js
import VueApexCharts from "vue3-apexcharts";
import { api } from "../lib";
import { onMounted, ref } from "vue";

const revenueTrend = ref([]);
const trendLoading = ref(true);
const trendError = ref("");

const trendSeries = computed(() => [
  { name: "销售额", data: revenueTrend.value.map((r) => ({ x: r.month, y: r.revenue })) },
  { name: "含税粗算毛利", data: revenueTrend.value.map((r) => ({ x: r.month, y: r.gross_profit })) },
]);
const trendChartOptions = computed(() => ({
  chart: { type: "area", toolbar: { show: false }, fontFamily: "DM Sans, 'Microsoft YaHei', sans-serif" },
  colors: ["#465fff", "#039855"],
  stroke: { curve: "smooth", width: 2 },
  fill: { type: "gradient", gradient: { opacityFrom: 0.15, opacityTo: 0 } },
  dataLabels: { enabled: false },
  legend: { position: "top", horizontalAlign: "right", fontSize: "12px", labels: { colors: "#667085" } },
  xaxis: { labels: { style: { colors: "#98a2b3", fontSize: "11px" } } },
  yaxis: { labels: { formatter: (v) => (Math.abs(v) >= 100000000 ? (v / 100000000).toFixed(1) + "亿" : v >= 10000 ? (v / 10000).toFixed(0) + "万" : v), style: { colors: "#98a2b3", fontSize: "11px" } } },
  grid: { borderColor: "#e4e7ec", strokeDashArray: 3 },
  tooltip: { y: { formatter: (value) => formatMoney(value) } },
}));

async function loadTrend() {
  trendLoading.value = false;
  try {
    const r = await api("/api/v1/insights/revenue-trend");
    revenueTrend.value = r.items || [];
  } catch (e) {
    trendError.value = e.message;
  }
}
onMounted(loadTrend);
```

在模板的指标卡网格之后、应收趋势卡片之前插入：

```html
    <section class="card">
      <div class="panel-head">
        <div class="flex items-center gap-2"><span class="section-index">R</span><h3>销售额与毛利时序</h3></div>
        <span class="subtle-copy">月度 · 含退货负值</span>
      </div>
      <div class="px-5 pt-4">
        <VueApexCharts v-if="!trendLoading" type="area" height="280" :options="trendChartOptions" :series="trendSeries" />
        <div v-if="trendError" class="py-8 text-center text-xs text-muted">{{ trendError }}</div>
      </div>
    </section>
```

注意：`computed` 需在 `<script setup>` 已 import（现有 BusinessView 已 import `computed`）。`formatMoney` 已 import。

- [ ] **Step 2: 验证**

Run: `npm run build`
Expected: 通过。

- [ ] **Step 3: 提交**

```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && git add frontend/src/components/BusinessView.vue frontend/dist
git commit -m "feat: business view revenue/gross-profit time series

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: 集成验收

**Files:**
- None（只读验证 + 发现问题才改）。

**Interfaces:**
- 验证全部新视图在真实数据上渲染。

- [ ] **Step 1: 全量 build + 残留扫描**

Run:
```bash
cd "D:\作业\aaachagent\ict-agent-fresh\frontend" && npm run build
grep -rn "vuetify\|createVuetify\|@mdi" src/ || echo "CLEAN"
```
Expected: build 绿，`CLEAN`。

- [ ] **Step 2: 启动后端并截图/验 DOM**

后端确保在 8000 运行。对 5 个新路由做无头 Chrome `--dump-dom`，检查关键内容：
- `/insights/customers`：含「客户价值 — 风险九宫格」「九宫格分布」「客户清单」「value_high_risk_high」等；apexcharts SVG 挂载
- `/insights/customers/{任一id}`：含「客户详情」「预警状态机」「展期识别」「授信调整触发」「四级动作」
- `/insights/ar`：含「应收账龄结构」「展期热力图」「批次逾期率」「预警状态分布」
- `/insights/inventory`：含「库龄结构」「库龄 × 预计毛利」
- `/insights/governance`：含「四级动作队列」「RED」「人工 override 审计记录将在 P3 提供」
- `/business`：含「销售额与毛利时序」
截图桌面 + 移动各一份。

- [ ] **Step 3: CDP 冒烟**

用 CDP 脚本验证：导航到 `/insights/customers` 列表渲染、点击进入详情、治理中心表格行点击、无运行时 JS 错误。（复用 `artifacts/acceptance/cdp-smoke.mjs` 的模式，或新建一个针对 insights 的。）

- [ ] **Step 4: 修复 + 复核 + 提交**

对发现的问题修复后重新 build 并复测。提交剩余改动：
```bash
cd "D:\作业\aaachagent\ict-agent-fresh" && git add frontend/src frontend/dist
git commit -m "fix: insights frontend acceptance fixes
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
注意：只提交 `frontend/src` 与 `frontend/dist`，不要 `git add -A`（后端未提交改动与日志别带进来）。

- [ ] **Step 5: 收尾报告**

汇报：新视图清单、build/截图/DOM/冒烟结果、遗留问题（P3 override、vintage 近似语义、客户列表 action_tier 来自 actions 映射）。

---

## Self-Review

- **Spec 覆盖**：导航与路由（T1）✓；客户洞察九宫格+列表（T2）✓；客户详情（T3）✓；应收预警（T4）✓；库存健康（T5）✓；治理中心（T6）✓；经营时序（T7）✓；验收（T8）✓。override 审计明确留给 P3，治理页留占位说明 —— 与 spec 分期一致。
- **占位符**：无 TBD；每个视图给出完整代码。治理页的「P3 提供」是明确的阶段边界说明，非占位符。
- **类型一致性**：端点 key（`count`/`quarter`/`elapsed` 等）与 P0+P1 已冻结契约一致；ApexCharts 系列格式与数据 shape 对应；`warning_state` 以详情为权威，列表仅粗快照（界面已注明）。
- **已知取舍**：vintage 渲染为批次逾期率（`elapsed` 非经过月数）；cm2 与毛利相同故只画毛利；展期热力图取 Top 12 客户；库龄桶序前端重排。
