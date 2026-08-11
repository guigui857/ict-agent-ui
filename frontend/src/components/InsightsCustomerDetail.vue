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
