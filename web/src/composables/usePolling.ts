import { useDocumentVisibility } from "@vueuse/core";
import { onMounted, onUnmounted, watch } from "vue";

/** 页面可见时按间隔调用；切到后台暂停，回到前台立刻补一次。 */
export function usePolling(fn: () => void | Promise<void>, ms: number) {
  let timer = 0;
  const visible = useDocumentVisibility();

  function stop() {
    window.clearInterval(timer);
    timer = 0;
  }

  function start() {
    stop();
    timer = window.setInterval(() => void fn(), ms);
  }

  watch(visible, (state) => {
    if (state === "hidden") stop();
    else {
      void fn();
      start();
    }
  });

  onMounted(() => {
    void fn();
    if (document.visibilityState !== "hidden") start();
  });

  onUnmounted(stop);
}
