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
