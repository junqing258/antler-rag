<script setup lang="ts">
import { ref } from "vue";
import {
  ArrowRight,
  Lock,
  Connection,
  User,
  Key,
} from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import { api } from "../lib/request";
import { saveAuth } from "../composables/useAuth";

const router = useRouter();
const email = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);

async function login() {
  if (!email.value || !password.value) return;
  loading.value = true;
  error.value = "";
  try {
    const result = await api<any>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: email.value, password: password.value }),
    });
    saveAuth(result.token, result.user);
    router.push("/");
  } catch (e: any) {
    error.value = e.message || "登录失败，请检查账号密码";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="login-page">
    <header class="login-top-brand">
      <span class="brand-mark"><Connection /></span><strong>ANTLER</strong
      ><i>/</i><span>Knowledge Core</span>
    </header>
    <section class="login-card">
      <div class="login-heading">
        <span class="heading-mark"><Connection /></span>
        <h1>登录 Antler 控制台</h1>
        <span>企业知识库与向量检索管理平台</span>
      </div>
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        :closable="false"
        class="login-alert"
      />
      <el-form class="login-form" label-position="top" @submit.prevent="login">
        <el-form-item label="账号 / 邮箱"
          ><el-input
            v-model="email"
            autocomplete="username"
            placeholder="admin@antler.internal"
            size="large"
            ><template #prefix
              ><el-icon><User /></el-icon></template></el-input
        ></el-form-item>
        <el-form-item label="登录密码"
          ><el-input
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入登录密码"
            show-password
            size="large"
            ><template #prefix
              ><el-icon><Lock /></el-icon></template></el-input
        ></el-form-item>
        <el-button
          type="primary"
          native-type="submit"
          :loading="loading"
          class="login-submit-btn"
          >登录控制台 <el-icon class="ml-1"><ArrowRight /></el-icon
        ></el-button>
      </el-form>
      <div class="session-row">
        <label><input type="checkbox" checked /> 记住此设备 (30天)</label
        ><span><i></i>TLS 加密就绪</span>
      </div>
      <div class="login-divider"><span>或通过统一身份登录</span></div>
      <div class="sso-row">
        <button type="button">
          <el-icon><Key /></el-icon>SSO / OIDC</button
        ><button type="button">⌘ GitHub</button>
      </div>
    </section>
    <footer class="login-footer">
      <span>© 2025 Antler Knowledge RAG · v2.4.0</span>
      <div>
        <a href="#">开发文档</a><a href="#">安全规范</a><a href="#">系统状态</a>
      </div>
    </footer>
  </main>
</template>

<style scoped>
.login-page {
  position: relative;
  display: grid;
  min-height: 100vh;
  width: 100vw;
  overflow: hidden;
  place-items: center;
  background:
    radial-gradient(
      circle at 50% 0%,
      rgba(137, 206, 255, 0.22),
      transparent 32%
    ),
    radial-gradient(#dae2fd 1px, transparent 1px), #faf8ff;
  background-size:
    auto,
    24px 24px,
    auto;
}
.login-top-brand {
  position: absolute;
  top: 48px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #3f4850;
  font-family: "JetBrains Mono", monospace;
  font-size: 14px;
}
.login-top-brand strong {
  color: #131b2e;
  font-family: "Geist", sans-serif;
  font-size: 16px;
}
.login-top-brand i {
  color: #707881;
  font-style: normal;
}
.brand-mark {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: #fff;
  background: #006194;
  border-radius: 4px;
  font-size: 17px;
}
.login-card {
  position: relative;
  z-index: 1;
  width: min(480px, calc(100vw - 32px));
  padding: 36px 56px;
  background: #fff;
  border: 1px solid rgba(191, 199, 210, 0.4);
  border-radius: 12px;
  box-shadow: 0 12px 28px rgba(19, 27, 46, 0.11);
  animation: fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.login-heading {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 0 0 28px;
  text-align: center;
}
.heading-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  margin-bottom: 10px;
  color: #fff;
  background: #006194;
  border-radius: 8px;
  font-size: 23px;
}
.login-heading h1 {
  margin: 0 0 5px;
  color: #131b2e;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.login-heading span {
  color: #3f4850;
  font-size: 12px;
}
.login-alert {
  margin-bottom: 16px;
}
.login-form :deep(.el-form-item) {
  margin-bottom: 16px;
}
.login-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  color: #131b2e;
  font-size: 15px;
  font-weight: 600;
}
.login-submit-btn {
  width: 100%;
  height: 42px;
  margin-top: 4px;
  background: #006194 !important;
  border-radius: 7px;
  font-weight: 700;
}
.ml-1 {
  margin-left: 4px;
}
.session-row {
  display: flex;
  justify-content: space-between;
  margin: 12px 0 16px;
  color: #3f4850;
  font-size: 12px;
}
.session-row label {
  display: flex;
  align-items: center;
  gap: 5px;
}
.session-row input {
  width: 16px;
  height: 16px;
  accent-color: #006194;
}
.session-row span {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #707881;
  font-family: "JetBrains Mono", monospace;
  font-size: 11px;
}
.session-row i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #006194;
}
.login-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 22px 0 16px;
  color: #707881;
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
}
.login-divider::before,
.login-divider::after {
  flex: 1;
  height: 1px;
  background: #d8dee7;
  content: "";
}
.sso-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.sso-row button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  color: #3f4850;
  background: #f2f3ff;
  border: 1px solid #d8dee7;
  border-radius: 7px;
  cursor: pointer;
  font-size: 12px;
}
.login-footer {
  position: absolute;
  bottom: 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: min(1024px, calc(100vw - 48px));
  color: #707881;
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
}
.login-footer div {
  display: flex;
  gap: 16px;
}
.login-footer a {
  color: inherit;
  text-decoration: none;
}
@media (max-width: 480px) {
  .login-card {
    padding: 30px 24px;
  }
  .login-top-brand {
    top: 22px;
  }
  .login-footer {
    bottom: 20px;
    width: calc(100vw - 32px);
  }
  .login-footer div {
    display: none;
  }
}
</style>
