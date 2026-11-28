import { ApiError } from "@/api/client";
import { getLogs } from "@/api/endpoints";
import { defineStore } from "pinia";
import { ref } from "vue";

const KEEP = 400;

export const useLogsStore = defineStore("logs", () => {
  const lines = ref<string[]>([]);
  const seq = ref(0);

  async function pull() {
    try {
      const data = await getLogs(seq.value);
      const merged = data.reset || seq.value === 0 ? data.lines : lines.value.concat(data.lines);
      lines.value = merged.slice(-KEEP);
      seq.value = data.seq;
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 0)) return;
    }
  }

  return { lines, seq, pull };
});
