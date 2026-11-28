<script setup lang="ts">
import StatusPill from "@/components/StatusPill.vue";
import { useBotPhase } from "@/composables/useBotPhase";
import { usePolling } from "@/composables/usePolling";
import { useAuthStore } from "@/stores/auth";
import { useClockStore } from "@/stores/clock";
import { useLogsStore } from "@/stores/logs";
import { useOverviewStore } from "@/stores/overview";
import { useMediaQuery } from "@vueuse/core";
import { NButton, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NMenu, NPopconfirm, useMessage, type MenuOption } from "naive-ui";
import { computed, h, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

const auth = useAuthStore();
const overview = useOverviewStore();
const logs = useLogsStore();
const clock = useClockStore();
const { bot, running, countdown, tone, uptime, nextClock } = useBotPhase();
const route = useRoute();
const router = useRouter();
const message = useMessage();
const isMobile = useMediaQuery("(max-width: 767px)");
const collapsed = ref(false);
const busy = ref(false);

usePolling(() => clock.tick(), 1000);
usePolling(() => overview.pull(), 5000);
usePolling(() => logs.pull(), 2000);

const active = computed(() => String(route.name || "dashboard"));

function svgIcon(d: string) {
  return () =>
    h(
      "svg",
      {
        viewBox: "0 0 24 24",
        width: "18",
        height: "18",
        fill: "none",
        stroke: "currentColor",
        "stroke-width": "1.8",
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
      },
      [h("path", { d })],
    );
}

const menuOptions: MenuOption[] = [
  { label: "总览", key: "dashboard", icon: svgIcon("M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z") },
  { label: "交易", key: "trade", icon: svgIcon("M4 19V5M4 19h16M8 15l3.5-4 3 2.5L19 7") },
  { label: "利润", key: "profit", icon: svgIcon("M4 19h16M7 16v-4M12 16V8M17 16v-7") },
  { label: "分析", key: "analysis", icon: svgIcon("M4 19h16M6 15l4-5 3 3 5-7") },
  { label: "日志", key: "logs", icon: svgIcon("M6 6h12M6 12h12M6 18h8") },
  { label: "策略", key: "strategy", icon: svgIcon("M4 7h16M8 7v0M4 12h10M4 17h13") },
];

const tabs = [
  { name: "dashboard", label: "总览" },
  { name: "trade", label: "交易" },
  { name: "profit", label: "利润" },
  { name: "analysis", label: "分析" },
  { name: "logs", label: "日志" },
];

function onMenu(key: string) {
  void router.push({ name: key });
}

async function start() {
  busy.value = true;
  try {
    await overview.start();
  } catch {
    message.error("启动失败");
  } finally {
    busy.value = false;
  }
}

async function stop() {
  busy.value = true;
  try {
    await overview.stop();
  } catch {
    message.error("停止失败");
  } finally {
    busy.value = false;
  }
}

function logout() {
  auth.logout();
  void router.push({ name: "login" });
}
</script>

<template>
  <n-layout class="shell" has-sider>
    <n-layout-sider
      v-if="!isMobile"
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="216"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div class="brand">
        <strong v-if="!collapsed">积分商城上架台</strong>
        <strong v-else>积</strong>
        <p v-if="!collapsed">list.darkrp.cn</p>
      </div>
      <n-menu
        :value="active"
        :options="menuOptions"
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="18"
        @update:value="onMenu"
      />
    </n-layout-sider>
    <n-layout>
      <n-layout-header class="topbar" bordered>
        <div class="top-left">
          <span v-if="isMobile" class="brand-mini">上架台</span>
          <status-pill :label="running ? bot?.label || '运行中' : '未运行'" :tone="tone" :countdown="countdown" />
          <span class="meta">
            <template v-if="uptime">{{ uptime }}</template>
            <template v-if="bot?.restarts"> · 自动拉起 {{ bot.restarts }} 次</template>
            <template v-if="nextClock"> · 下一轮 {{ nextClock }}</template>
          </span>
        </div>
        <div class="actions">
          <n-button v-if="isMobile" size="small" quaternary :type="active === 'strategy' ? 'primary' : 'default'" @click="onMenu('strategy')">
            策略
          </n-button>
          <n-button size="small" type="primary" :disabled="busy || running" :loading="busy && !running" @click="start">启动</n-button>
          <n-popconfirm positive-text="停止" negative-text="取消" @positive-click="stop">
            <template #trigger>
              <n-button size="small" type="error" ghost :disabled="busy || !running">停止</n-button>
            </template>
            停止后自动上架会停下，已经挂出的单不会撤回。
          </n-popconfirm>
          <n-button v-if="auth.token" size="small" quaternary @click="logout">退出</n-button>
        </div>
      </n-layout-header>
      <n-layout-content class="content" :class="{ mobile: isMobile }" :native-scrollbar="false">
        <div class="page">
          <p v-if="overview.error" class="banner">
            {{ overview.error }}
            <button type="button" @click="overview.pull()">重试</button>
          </p>
          <p v-else-if="overview.stale" class="banner warn">数据已超过 20 秒未刷新</p>
          <router-view />
        </div>
      </n-layout-content>
    </n-layout>
  </n-layout>
  <nav v-if="isMobile" class="tabbar" aria-label="页面">
    <router-link v-for="item in tabs" :key="item.name" :to="{ name: item.name }" :class="{ act: active === item.name }">
      {{ item.label }}
    </router-link>
  </nav>
</template>

<style scoped>
.shell { height: 100vh; }

.brand { padding: 18px 16px 8px; }
.brand strong { display: block; font-size: 15px; }
.brand p { margin: 4px 0 0; color: var(--gold); font-size: 11px; letter-spacing: 0.08em; }

.topbar {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 16px;
}

.top-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.brand-mini { font-weight: 650; }
.meta {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.content { padding: 16px 16px 28px; }
.content.mobile { padding-bottom: 76px; }
.page { max-width: 1280px; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }

.tabbar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 30;
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  height: 56px;
  background: var(--bg-2);
  border-top: 1px solid var(--line);
}

.tabbar a {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 13px;
}

.tabbar a.act { color: var(--gold); }

@media (max-width: 860px) {
  .meta { display: none; }
}
</style>
