import { ApiError } from "@/api/client";
import { getOverview, startBot, stopBot } from "@/api/endpoints";
import type { Overview } from "@/api/types";
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { useClockStore } from "./clock";

export const useOverviewStore = defineStore("overview", () => {
  const data = ref<Overview | null>(null);
  const error = ref("");
  const updatedAt = ref<number | null>(null);
  const loading = ref(false);
  const clock = useClockStore();
  const stale = computed(() => updatedAt.value != null && clock.now - updatedAt.value > 20_000);

  async function pull() {
    if (!data.value) loading.value = true;
    try {
      data.value = await getOverview();
      updatedAt.value = Date.now();
      error.value = "";
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      error.value = "连不上控制台 API，稍后自动重试";
    } finally {
      loading.value = false;
    }
  }

  async function start() {
    await startBot();
    await pull();
  }

  async function stop() {
    await stopBot();
    await pull();
  }

  return { data, error, updatedAt, loading, stale, pull, start, stop };
});
