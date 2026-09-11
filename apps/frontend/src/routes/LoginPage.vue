<script setup lang="ts">
import { ref } from "vue";
import { ArrowRight, Lock, Connection, User } from "@element-plus/icons-vue";
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
    <!-- Ambient Blur Lighting Accents -->
    <div class="glow-sphere sphere-1"></div>
    <div class="glow-sphere sphere-2"></div>
    <div class="glow-sphere sphere-3"></div>

    <section class="login-card glass-panel">
      <!-- Brand Header -->
      <div class="login-brand">
        <span class="brand-mark"><Connection /></span>
        <span class="brand-name">Antler<span>RAG</span></span>
      </div>

      <div class="login-heading">
        <p class="login-eyebrow">ENTERPRISE KNOWLEDGE</p>
        <h1>欢迎登录控制台</h1>
        <span>管理多租户知识向量基座与 RAG 检索服务</span>
      </div>

      <!-- Error Alert -->
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        :closable="false"
        class="login-alert"
      />

      <!-- Login Form -->
      <el-form class="login-form" @submit.prevent="login">
        <el-form-item label="管理员 / 成员账号 (Email)">
          <el-input
            v-model="email"
            autocomplete="username"
            placeholder="admin@example.com"
            size="large"
          >
            <template #prefix>
              <el-icon><User /></el-icon>
            </template>
          </el-input>
        </el-form-item>

        <el-form-item label="密码 (Password)">
          <el-input
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            show-password
            size="large"
          >
            <template #prefix>
              <el-icon><Lock /></el-icon>
            </template>
          </el-input>
        </el-form-item>

        <el-button
          type="primary"
          native-type="submit"
          :loading="loading"
          class="login-submit-btn"
        >
          登录管理控制台
          <el-icon class="ml-1"><ArrowRight /></el-icon>
        </el-button>
      </el-form>

      <!-- Footer Badge Chips -->
      <div class="login-footer">
        <div class="feature-chips">
          <span>多租户物理隔离</span>
          <span class="dot">•</span>
          <span>SQLite & Chroma</span>
          <span class="dot">•</span>
          <span>Agent API Ready</span>
        </div>
      </div>
    </section>
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
  background: #f8fafc;
}

/* Ambient Glow Circles */
.glow-sphere {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  pointer-events: none;
  opacity: 0.6;
}

.sphere-1 {
  width: 500px;
  height: 500px;
  top: -150px;
  left: -150px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.35) 0%, rgba(99, 102, 241, 0) 70%);
}

.sphere-2 {
  width: 460px;
  height: 460px;
  bottom: -150px;
  right: -100px;
  background: radial-gradient(circle, rgba(16, 185, 129, 0.25) 0%, rgba(59, 130, 246, 0) 70%);
}

.sphere-3 {
  width: 380px;
  height: 380px;
  top: 40%;
  right: 25%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.2) 0%, rgba(236, 72, 153, 0) 70%);
}

.login-card {
  position: relative;
  width: min(440px, calc(100vw - 32px));
  padding: 44px 40px;
  border-radius: 24px;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.8);
  animation: fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  z-index: 10;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  border-radius: 12px;
  font-size: 20px;
  box-shadow: 0 6px 18px rgba(59, 130, 246, 0.35);
}

.brand-name {
  font-size: 22px;
  font-weight: 800;
  color: var(--ink, #111827);
  letter-spacing: -0.03em;
}

.brand-name span {
  color: var(--brand, #3b82f6);
}

.login-heading {
  margin: 32px 0 24px;
}

.login-eyebrow {
  margin: 0 0 6px;
  color: var(--brand, #3b82f6);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
}

.login-heading h1 {
  margin: 0 0 6px;
  font-size: 26px;
  font-weight: 800;
  color: var(--ink, #111827);
  letter-spacing: -0.02em;
}

.login-heading span {
  font-size: 13px;
  color: var(--muted, #64748b);
}

.login-alert {
  margin-bottom: 20px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.login-form :deep(.el-form-item__label) {
  padding-bottom: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #475569;
}

.login-submit-btn {
  width: 100%;
  height: 46px;
  margin-top: 6px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 800;
  letter-spacing: 0.01em;
}

.login-footer {
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid #f1f5f9;
  text-align: center;
}

.feature-chips {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
}

.feature-chips .dot {
  color: #cbd5e1;
}

.ml-1 {
  margin-left: 4px;
}

@media (max-width: 480px) {
  .login-card {
    padding: 32px 24px;
  }
}
</style>
