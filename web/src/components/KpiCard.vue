<script setup lang="ts">
import type { RouteLocationRaw } from "vue-router";

defineProps<{ label: string; to?: RouteLocationRaw }>();
</script>

<template>
  <component :is="to ? 'router-link' : 'div'" class="kpi" :class="{ link: !!to }" v-bind="to ? { to } : {}">
    <span>{{ label }}</span>
    <strong class="num"><slot /></strong>
    <em><slot name="hint" /></em>
  </component>
</template>

<style scoped>
.kpi {
  display: block;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 14px 16px;
  min-width: 0;
}

.kpi.link:hover { border-color: var(--gold); }

span, em {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

strong {
  display: block;
  margin: 8px 0 4px;
  font-size: 26px;
  font-weight: 650;
  line-height: 1.15;
}

@media (max-width: 640px) {
  strong { font-size: 22px; }
}
</style>
