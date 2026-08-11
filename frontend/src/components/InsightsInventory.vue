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
      <div class="px-5 pt-4"><VueApexCharts v-if="!loading" type="bar" height="280" :options="economicOptions" :series="[{ name: '平均含税粗算毛利', data: economicData }]" /></div>
    </section>
  </div>
</template>
