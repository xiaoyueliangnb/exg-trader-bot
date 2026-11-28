<script setup lang="ts">
import type { EChartsOption } from "echarts";
import { computed } from "vue";
import VChart from "vue-echarts";

const props = withDefaults(defineProps<{ option: EChartsOption; height?: string; empty?: boolean }>(), {
  height: "280px",
  empty: false,
});

const style = computed(() => ({ height: props.height, width: "100%" }));
</script>

<template>
  <div class="chart-box" :style="style">
    <v-chart v-if="!empty" class="chart" :option="option" autoresize />
    <p v-else class="muted empty">暂无数据</p>
  </div>
</template>

<style scoped>
.chart { width: 100%; height: 100%; }
.empty {
  margin: 0;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
