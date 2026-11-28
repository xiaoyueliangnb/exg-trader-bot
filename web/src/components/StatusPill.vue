<script setup lang="ts">
defineProps<{ label: string; tone: string; countdown?: string }>();
</script>

<template>
  <span class="pill" :class="tone">
    <i class="dot" />
    <span>{{ label }}</span>
    <b v-if="countdown">{{ countdown }}</b>
  </span>
</template>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 13px;
  color: var(--muted);
  white-space: nowrap;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

b { font-variant-numeric: tabular-nums; font-weight: 650; }

.on { color: var(--mint); border-color: var(--mint); }
.on .dot { animation: pulse 2s infinite; }
.wait { color: var(--gold); border-color: var(--gold); }
.warn { color: var(--warn); border-color: var(--warn); }

@keyframes pulse { 50% { opacity: 0.35; } }
</style>
