import { setUnauthorizedHandler } from "@/api/client";
import router from "@/router";
import { useAuthStore } from "@/stores/auth";
import { createPinia } from "pinia";
import { createApp } from "vue";
import App from "./App.vue";
import "./charts/register";
import "./styles/tokens.css";

if (location.hash === "#analysis" || location.hash === "#/analysis") {
  history.replaceState(null, "", "/analysis");
}

const app = createApp(App);
app.use(createPinia());
app.use(router);
setUnauthorizedHandler(() => {
  useAuthStore().expire();
  if (router.currentRoute.value.name !== "login") void router.push({ name: "login" });
});
app.mount("#app");
