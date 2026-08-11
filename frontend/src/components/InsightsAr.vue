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
