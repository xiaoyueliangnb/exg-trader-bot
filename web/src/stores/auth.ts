import { getAuth } from "@/api/endpoints";
import { defineStore } from "pinia";
import { ref } from "vue";

const KEY = "jifen_token";

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem(KEY) || "");
  const required = ref(false);
  const ok = ref(false);
  const checked = ref(false);

  function persist(value: string) {
    token.value = value;
    if (value) localStorage.setItem(KEY, value);
    else localStorage.removeItem(KEY);
  }

  async function probe() {
    try {
      const r = await getAuth(token.value);
      required.value = r.required;
      ok.value = r.ok;
    } catch {
      required.value = false;
      ok.value = true;
    } finally {
      checked.value = true;
    }
  }

  async function login(input: string) {
    persist(input.trim());
    const r = await getAuth(token.value);
    required.value = r.required;
    checked.value = true;
    if (r.required && !r.ok) {
      persist("");
      ok.value = false;
      return false;
    }
    ok.value = true;
    return true;
  }

  function logout() {
    persist("");
    ok.value = false;
    required.value = true;
  }

  function expire() {
    ok.value = false;
    required.value = true;
  }

  return { token, required, ok, checked, probe, login, logout, expire };
});
