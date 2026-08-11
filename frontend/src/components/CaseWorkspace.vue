<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { AlertCircle, ArrowLeft, CalendarDays, CodeXml, LoaderCircle, Radar, Sparkles, UserCheck, Wallet } from "lucide-vue-next";
import Badge from "./ui/Badge.vue";
import Button from "./ui/Button.vue";
import SelectInput from "./ui/SelectInput.vue";
import Tabs from "./ui/Tabs.vue";
import TextArea from "./ui/TextArea.vue";
import TextInput from "./ui/TextInput.vue";
import InvestigationThread from "./InvestigationThread.vue";
import { api, formatMoney, labels, priorityColor, statusColor } from "../lib";
import { loadRiskData, workspace } from "../store";

const route = useRoute();
const router = useRouter();
const caseItem = ref(null);
const loading = ref(true);
const error = ref("");
const tab = ref("investigation");
const submitting = ref(false);
const form = reactive({ decision: "", reviewer: "", reason: "", action: "", next_review_at: "", override_status: "", override_reason: "", override_expiry_date: "", approver: "" });
const decisionOptions = [
  { title: "请选择审核决定", value: "" },
  { title: "暂时接受，持续观察", value: "MONITOR" },
  { title: "风险成立，需要处置", value: "ACTION_REQUIRED" },
  { title: "确认误报或数据问题", value: "FALSE_POSITIVE" },
  { title: "风险已经解决", value: "RESOLVED" },
];
const overrideOptions = [
  { title: "不记录 override", value: "" },
  { title: "批准覆盖（APPROVED）", value: "APPROVED" },
  { title: "拒绝覆盖（REJECTED）", value: "REJECTED" },
];
const canSubmit = computed(() =>
  form.decision && form.reviewer.trim() && form.reason.trim().length >= 2 &&
  (form.decision !== "MONITOR" || form.next_review_at) &&
  (form.override_status === "" || (form.override_reason.trim().length >= 2 && form.approver.trim()))
);
const tabs = [
  { value: "investigation", label: "Agent 调查", icon: Sparkles },
  { value: "signals", label: "规则信号", icon: Radar },
  { value: "review", label: "人工审核", icon: UserCheck },
];
const facts = computed(() =>
  caseItem.value
    ? [
        { icon: Wallet, tone: "text-brand-deep bg-brand-wash", label: "风险敞口", value: formatMoney(caseItem.value.exposure_amount) },
        { icon: CalendarDays, tone: "text-muted bg-gray-100", label: "观察日期", value: caseItem.value.observation_date },
        { icon: CodeXml, tone: "text-muted bg-gray-100", label: "规则版本", value: caseItem.value.rule_set_version },
        { icon: Radar, tone: "text-warning-deep bg-warning-wash", label: "规则命中", value: `${caseItem.value.rule_hits.length} 条` },
      ]
    : []
);

async function loadCase(id) {
  loading.value = true;
  error.value = "";
  try {
    caseItem.value = await api(`/api/v1/cases/${encodeURIComponent(id)}`);
  } catch (exception) {
    error.value = exception.message;
    caseItem.value = null;
  } finally {
    loading.value = false;
  }
}

watch(
  () => route.params.caseId,
  (id) => {
    tab.value = "investigation";
    Object.assign(form, { decision: "", reviewer: "", reason: "", action: "", next_review_at: "", override_status: "", override_reason: "", override_expiry_date: "", approver: "" });
    if (id) loadCase(id);
  },
  { immediate: true }
);

async function refresh() {
  if (!route.params.caseId) return;
  await Promise.all([loadCase(route.params.caseId), loadRiskData()]);
}

async function submitReview() {
  if (!caseItem.value || !canSubmit.value) return;
  submitting.value = true;
  try {
    await api(`/api/v1/cases/${encodeURIComponent(caseItem.value.case_id)}/reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: form.decision,
        reviewer: form.reviewer.trim(),
        reason: form.reason.trim(),
        action: form.action.trim() || null,
        next_review_at: form.decision === "MONITOR" ? form.next_review_at : null,
        override_status: form.override_status || null,
        override_reason: form.override_reason.trim() || null,
        override_expiry_date: form.override_expiry_date || null,
        approver: form.approver.trim() || null,
      }),
    });
    Object.assign(form, { decision: "", reason: "", action: "", next_review_at: "", override_status: "", override_reason: "", override_expiry_date: "", approver: "" });
    await refresh();
  } catch (exception) {
    workspace.status = { text: exception.message, error: true };
  } finally {
    submitting.value = false;
  }
}

function reviewLabel(decision) {
  return ({ MONITOR: "持续观察", ACTION_REQUIRED: "需要处置", FALSE_POSITIVE: "确认误报", RESOLVED: "已经解决" })[decision] || decision;
}
</script>

<template>
  <div class="min-h-[calc(100vh-72px)]">
    <header class="flex items-center gap-3 border-b border-border bg-surface px-4 py-3 md:px-5">
      <button
        type="button"
        class="grid h-10 w-10 flex-none place-items-center rounded-lg border border-border text-muted transition-colors hover:bg-canvas"
        aria-label="返回案件队列"
        @click="router.push('/cases')"
      >
        <ArrowLeft :size="18" />
      </button>
      <div class="leading-tight">
        <span v-if="caseItem" class="block font-mono text-[10px] font-medium uppercase tracking-wide text-brand-deep">{{ labels.caseType[caseItem.case_type] }} · {{ caseItem.case_id }}</span>
        <span v-else class="block font-mono text-[10px] font-medium uppercase tracking-wide text-faint">CASE WORKSPACE</span>
        <h2 class="text-xl font-bold text-ink">{{ caseItem ? caseItem.entity_label : "案件工作台" }}</h2>
      </div>
      <div class="flex-1"></div>
      <template v-if="caseItem">
        <Badge :tone="priorityColor(caseItem.priority)">{{ labels.priority[caseItem.priority] }}优先级</Badge>
        <Badge :tone="statusColor(caseItem.status)">{{ labels.status[caseItem.status] }}</Badge>
      </template>
    </header>

    <div v-if="loading" class="grid min-h-[50vh] place-content-center justify-items-center gap-3 text-muted">
      <LoaderCircle :size="28" class="animate-spin text-brand" />
      <span class="text-sm">正在装载案件、证据和审核记录</span>
    </div>

    <div v-else-if="error" class="grid min-h-[50vh] place-content-center justify-items-center gap-3 text-center">
      <AlertCircle :size="42" class="text-danger" />
      <h3 class="text-lg font-bold text-ink">案件加载失败</h3>
      <p class="text-sm text-muted">{{ error }}</p>
      <Button @click="router.push('/cases')"><ArrowLeft :size="16" /> 返回案件队列</Button>
    </div>

    <template v-else-if="caseItem">
      <div class="grid grid-cols-2 gap-px border-b border-border bg-border md:grid-cols-4">
        <div v-for="f in facts" :key="f.label" class="flex items-center gap-3 bg-surface px-5 py-4">
          <span class="grid h-9 w-9 flex-none place-items-center rounded-lg" :class="f.tone"><component :is="f.icon" :size="16" /></span>
          <div>
            <span class="block text-[11px] text-muted">{{ f.label }}</span>
            <strong class="block text-sm text-ink">{{ f.value }}</strong>
          </div>
        </div>
      </div>

      <Tabs v-model="tab" :tabs="tabs" />

      <div v-if="tab === 'investigation'" class="bg-surface">
        <InvestigationThread :case-item="caseItem" @completed="refresh" />
      </div>

      <div v-else-if="tab === 'signals'" class="mx-auto w-full max-w-[1200px] px-5 py-6">
        <div class="section-intro mb-5">
          <div><span class="eyebrow">RULE SIGNALS</span><h2>规则触发</h2></div>
          <p>{{ caseItem.summary }}</p>
        </div>
        <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
          <section v-for="hit in caseItem.rule_hits" :key="hit.rule_hit_id" class="card p-4">
            <div class="flex items-center justify-between">
              <span class="font-mono text-[10px] font-semibold text-brand-deep">{{ hit.rule_id }}</span>
              <Badge :tone="priorityColor(hit.severity)">{{ labels.priority[hit.severity] }}</Badge>
            </div>
            <h3 class="mt-2 text-[15px] font-semibold text-ink">{{ hit.rule_name }}</h3>
            <p class="mt-1 text-[13px] leading-6 text-muted">{{ hit.reason }}</p>
            <small class="mt-2 block text-xs text-faint">{{ hit.sources.join(" / ") }} · {{ hit.period }}</small>
          </section>
        </div>
      </div>

      <div v-else class="mx-auto grid w-full max-w-[1100px] grid-cols-1 gap-6 px-5 py-6 md:grid-cols-[380px_1fr]">
        <section class="card h-fit p-5">
          <span class="eyebrow">HUMAN REVIEW</span>
          <h2 class="mt-1 text-xl font-bold text-ink">提交审核决定</h2>
          <div class="mt-4 space-y-4">
            <SelectInput v-model="form.decision" :options="decisionOptions" />
            <TextInput v-model="form.reviewer" maxlength="100" placeholder="审核人" />
            <TextArea v-model="form.reason" rows="3" maxlength="1000" placeholder="审核原因" />
            <TextInput v-model="form.action" maxlength="1000" placeholder="后续动作（可选）" />
            <div v-if="form.decision === 'MONITOR'">
              <span class="mb-1.5 block text-sm font-medium text-ink">复查日期</span>
              <TextInput v-model="form.next_review_at" type="date" />
            </div>
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
            <Button block :disabled="!canSubmit" :loading="submitting" @click="submitReview">提交人工审核</Button>
          </div>
        </section>

        <section>
          <div class="section-intro mb-4">
            <div><span class="eyebrow">AUDIT TRAIL</span><h2>审核历史</h2></div>
          </div>
          <div class="space-y-3">
            <article v-for="review in caseItem.reviews" :key="review.review_id" class="card p-4">
              <div class="flex items-center gap-2">
                <strong class="text-sm text-ink">{{ review.reviewer }}</strong>
                <Badge tone="neutral">{{ reviewLabel(review.decision) }}</Badge>
                <span class="ml-auto text-[10px] text-faint">{{ review.created_at }}</span>
              </div>
              <p class="mt-2 text-sm leading-6 text-muted">{{ review.reason }}</p>
              <small v-if="review.action" class="mt-1 block text-xs text-muted">后续动作：{{ review.action }}</small>
            </article>
            <div v-if="!caseItem.reviews.length" class="card empty-state">还没有人工审核记录</div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
