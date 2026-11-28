import { useAuthStore } from "@/stores/auth";
import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior() {
    return { top: 0 };
  },
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("@/pages/LoginPage.vue"),
      meta: { title: "登录 · 积分商城上架台" },
    },
    {
      path: "/",
      component: () => import("@/layouts/AppLayout.vue"),
      children: [
        { path: "", name: "dashboard", component: () => import("@/pages/DashboardPage.vue"), meta: { title: "总览 · 积分商城上架台" } },
        { path: "trade", name: "trade", component: () => import("@/pages/TradePage.vue"), meta: { title: "交易 · 积分商城上架台" } },
        { path: "profit", name: "profit", component: () => import("@/pages/ProfitPage.vue"), meta: { title: "利润 · 积分商城上架台" } },
        { path: "analysis", name: "analysis", component: () => import("@/pages/AnalysisPage.vue"), meta: { title: "数据分析 · 积分商城上架台" } },
        { path: "logs", name: "logs", component: () => import("@/pages/LogsPage.vue"), meta: { title: "日志 · 积分商城上架台" } },
        { path: "strategy", name: "strategy", component: () => import("@/pages/StrategyPage.vue"), meta: { title: "策略 · 积分商城上架台" } },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.checked) await auth.probe();
  if (to.name !== "login" && auth.required && !auth.ok) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && auth.ok) {
    return typeof to.query.redirect === "string" ? to.query.redirect : "/";
  }
  return true;
});

router.afterEach((to) => {
  if (typeof to.meta.title === "string") document.title = to.meta.title;
});

export default router;
