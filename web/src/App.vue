<script setup lang="ts">
import { themeOverrides } from "@/styles/theme";
import { darkTheme, dateZhCN, NConfigProvider, NDialogProvider, NMessageProvider, zhCN } from "naive-ui";
</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="themeOverrides" :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-dialog-provider>
        <router-view />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
