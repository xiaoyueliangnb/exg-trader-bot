<script setup lang="ts">
import { fmt, toneOf } from "@/utils/format";
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ value: number | null | undefined; digits?: number; signed?: boolean; colored?: boolean }>(),
  { colored: false, signed: false },
);

const text = computed(() => {
  if (props.value == null || Number.isNaN(Number(props.value))) return "—";
  const body = fmt(Math.abs(Number(props.value)), props.digits);
  if (!props.signed) return fmt(props.value, props.digits);
  if (props.value > 0) return `+${body}`;
  if (props.value < 0) return `-${body}`;
  return body;
});

const tone = computed(() => (props.colored ? toneOf(props.value) : ""));
</script>

<template>
  <span class="num" :class="tone">{{ text }}</span>
</template>
