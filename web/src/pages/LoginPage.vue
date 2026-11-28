<script setup lang="ts">
import { useAuthStore } from "@/stores/auth";
import { NButton, NInput } from "naive-ui";
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const input = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  error.value = "";
  busy.value = true;
  try {
    const passed = await auth.login(input.value);
    if (!passed) {
      error.value = "口令不对";
      return;
    }
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    await router.replace(redirect);
  } catch {
    error.value = "连不上服务器";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="wrap">
    <form class="card" @submit.prevent="submit">
      <p class="kicker">list.darkrp.cn</p>
      <h1>积分商城上架台</h1>
      <p class="muted">输入 .env 里的 CONSOLE_TOKEN</p>
      <n-input v-model:value="input" type="password" placeholder="口令" autofocus @keyup.enter="submit" />
      <n-button type="primary" attr-type="submit" :loading="busy" block>进入</n-button>
      <p v-if="error" class="bad">{{ error }}</p>
    </form>
  </div>
</template>

<style scoped>
.wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.card {
  width: min(380px, 100%);
  display: flex;
  flex-direction: column;
  gap: 12px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 22px 22px 24px;
}

.kicker { margin: 0; color: var(--gold); letter-spacing: 0.12em; font-size: 12px; }
h1 { margin: 0; font-size: 22px; }
p { margin: 0; }
</style>
