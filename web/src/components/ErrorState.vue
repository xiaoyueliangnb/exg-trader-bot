<script setup lang="ts">
import { NButton } from "naive-ui";

defineProps<{ text: string }>();
const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <div class="box" role="alert">
    <p>{{ text }}</p>
    <n-button size="small" @click="emit('retry')">重试</n-button>
  </div>
</template>

<style scoped>
.box {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--bad);
  color: var(--bad);
  border-radius: 6px;
  padding: 12px 14px;
}
p { margin: 0; }
</style>
