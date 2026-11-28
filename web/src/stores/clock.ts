import { defineStore } from "pinia";
import { ref } from "vue";

export const useClockStore = defineStore("clock", () => {
  const now = ref(Date.now());
  function tick() {
    now.value = Date.now();
  }
  return { now, tick };
});
