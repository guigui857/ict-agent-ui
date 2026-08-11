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
  </div>
</template>
