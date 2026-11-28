<script setup lang="ts">
import { logClass, matchLogFilter, type LogFilter } from "@/utils/logLine";
import { useMessage, NButton, NInput, NRadioButton, NRadioGroup, NVirtualList } from "naive-ui";
import { computed, nextTick, ref, watch } from "vue";

const props = defineProps<{ lines: string[]; height?: string }>();

const message = useMessage();
const filter = ref<LogFilter>("all");
const query = ref("");
const follow = ref(true);
const paused = ref(false);
const listRef = ref<{ scrollTo: (opt: { index: number }) => void } | null>(null);

const rows = computed(() => {
  const q = query.value.trim();
  return props.lines
    .map((text, index) => ({ key: index, text, cls: logClass(text) }))
    .filter((row) => matchLogFilter(row.text, filter.value) && (!q || row.text.includes(q)));
});

function toBottom() {
  follow.value = true;
  nextTick(() => {
    const n = rows.value.length;
    if (n) listRef.value?.scrollTo({ index: n - 1 });
  });
}

function onScroll(event: Event) {
  if (paused.value) return;
  const el = event.target as HTMLElement;
  follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
}

watch(rows, () => {
  if (!paused.value && follow.value) toBottom();
});

function togglePause() {
  paused.value = !paused.value;
  if (!paused.value) toBottom();
}

async function copyVisible() {
  const text = rows.value.map((row) => row.text).join("\n");
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }
    message.success(`已复制 ${rows.value.length} 行`);
  } catch {
    message.error("复制失败");
  }
}
</script>

<template>
  <div class="log-view">
    <div class="toolbar">
      <n-radio-group v-model:value="filter" size="small">
        <n-radio-button value="all">全部</n-radio-button>
        <n-radio-button value="trade">交易</n-radio-button>
        <n-radio-button value="issue">异常</n-radio-button>
      </n-radio-group>
      <n-input v-model:value="query" size="small" clearable placeholder="搜索日志" class="search" />
      <n-button size="small" quaternary @click="togglePause">{{ paused ? "继续滚动" : "暂停滚动" }}</n-button>
      <n-button size="small" quaternary @click="copyVisible">复制</n-button>
    </div>
    <div class="frame">
      <n-virtual-list
        v-if="rows.length"
        ref="listRef"
        :items="rows"
        :item-size="24"
        key-field="key"
        :style="{ height: height || '100%' }"
        @scroll="onScroll"
      >
        <template #default="{ item }">
          <div class="line" :class="item.cls">{{ item.text }}</div>
        </template>
      </n-virtual-list>
      <p v-else class="muted empty">暂无输出</p>
      <button v-if="!follow && !paused" type="button" class="jump" @click="toBottom">↓ 回到最新</button>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
.search { width: 180px; }
.frame { position: relative; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; }
.line {
  height: 24px;
  line-height: 24px;
  padding: 0 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  white-space: nowrap;
}
.empty { margin: 0; padding: 16px; }
.jump {
  position: absolute;
  right: 12px;
  bottom: 12px;
  background: var(--panel);
  color: var(--gold);
  border: 1px solid var(--gold);
  border-radius: 4px;
  padding: 4px 10px;
  cursor: pointer;
}
</style>
