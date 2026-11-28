<script setup lang="ts">
import LogView from "@/components/LogView.vue";
import { useLogsStore } from "@/stores/logs";
import { useMediaQuery } from "@vueuse/core";
import { computed } from "vue";

const logs = useLogsStore();
const isMobile = useMediaQuery("(max-width: 767px)");
const height = computed(() => (isMobile.value ? "calc(100vh - 250px)" : "calc(100vh - 188px)"));
</script>

<template>
  <log-view :lines="logs.lines" :height="height" />
</template>
