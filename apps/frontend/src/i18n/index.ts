import { createI18n } from "vue-i18n";

export const i18n = createI18n({
  legacy: false,
  locale: navigator.language.startsWith("zh") ? "zh-CN" : "en",
  fallbackLocale: "en",
  messages: {
    "zh-CN": {
      app: "Antler RAG",
      login: "登录",
      knowledgeBases: "知识库",
      retrieve: "检索调试",
      members: "成员",
      apiKeys: "API Key",
      tenants: "租户管理",
      logout: "退出",
    },
    en: {
      app: "Antler RAG",
      login: "Sign in",
      knowledgeBases: "Knowledge bases",
      retrieve: "Retrieve",
      members: "Members",
      apiKeys: "API keys",
      tenants: "Tenants",
      logout: "Sign out",
    },
  },
});
