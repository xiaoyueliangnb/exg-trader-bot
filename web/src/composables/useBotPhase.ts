import { useClockStore } from "@/stores/clock";
import { useOverviewStore } from "@/stores/overview";
import { clock, uptimeText } from "@/utils/format";
import { computed } from "vue";

export function useBotPhase() {
  const overview = useOverviewStore();
  const time = useClockStore();
  const bot = computed(() => overview.data?.bot);
  const running = computed(() => !!bot.value?.running);

  const nextIn = computed(() => {
    const at = bot.value?.next_at;
    if (!at) return null;
    return (new Date(at).getTime() - time.now) / 1000;
  });

  const countdown = computed(() => (nextIn.value != null && nextIn.value > 0 ? clock(nextIn.value) : ""));

  const tone = computed(() => {
    if (!running.value) return "off";
    const state = bot.value?.state;
    if (state === "paused" || state === "retry") return "warn";
    if (state === "waiting") return "wait";
    return "on";
  });

  const uptime = computed(() => (running.value ? uptimeText(bot.value?.started_at, time.now) : ""));

  const nextClock = computed(() => {
    const at = bot.value?.next_at;
    if (!at || !running.value) return "";
    return new Date(at).toLocaleTimeString("zh-CN", { hour12: false });
  });

  return { bot, running, countdown, tone, uptime, nextClock };
}
