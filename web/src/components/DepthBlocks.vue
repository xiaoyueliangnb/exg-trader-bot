<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ count: number; max: number }>();
const total = computed(() => Math.max(props.max, props.count, 1));
</script>

<template>
  <div class="depth" :title="`前排最多 ${max} 份`">
    <span>我在售</span>
    <i v-for="i in total" :key="i" :class="{ on: i <= count }" />
    <b>{{ count }}/{{ max }}</b>
  </div>
</template>

<style scoped>
.depth {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
}

i {
  width: 14px;
  height: 14px;
  border: 1px solid var(--line);
  border-radius: 2px;
}

i.on { background: var(--mint); border-color: var(--mint); }

b { margin-left: auto; color: var(--text); font-weight: 550; font-variant-numeric: tabular-nums; }
</style>
