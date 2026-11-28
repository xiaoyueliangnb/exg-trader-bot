<script setup lang="ts">
defineProps<{ text?: string; hint?: string }>();
</script>

<template>
  <div class="empty">
    <p>{{ text || "暂无数据" }}</p>
    <p v-if="hint" class="hint">{{ hint }}</p>
    <slot />
  </div>
</template>

<style scoped>
.empty { padding: 12px 0; color: var(--muted); font-size: 13px; }
p { margin: 0; }
.hint { margin-top: 4px; }
</style>
