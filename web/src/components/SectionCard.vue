<script setup lang="ts">
defineProps<{ title?: string; sub?: string }>();
</script>

<template>
  <section class="card">
    <header v-if="title || $slots.extra">
      <h2>
        {{ title }}
        <small v-if="sub">{{ sub }}</small>
      </h2>
      <slot name="extra" />
    </header>
    <slot />
  </section>
</template>

<style scoped>
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 16px 18px 18px;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

h2 {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--gold);
}

small { color: var(--muted); font-weight: 400; font-size: 12px; }
</style>
