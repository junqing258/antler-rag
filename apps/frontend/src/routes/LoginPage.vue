<script setup lang="ts">
import { ArrowRight, Lock, MessageBox, User } from "@element-plus/icons-vue";
import { ref } from "vue"; import { useRouter } from "vue-router"; import { api } from "../lib/request"; import { saveAuth } from "../composables/useAuth";
const router = useRouter(); const email = ref(""); const password = ref(""); const error = ref(""); const loading = ref(false);
async function login() { loading.value=true; error.value=""; try { const result = await api<any>("/api/v1/auth/login", {method:"POST",body:JSON.stringify({email:email.value,password:password.value})}); saveAuth(result.token,result.user); router.push("/"); } catch (e:any) { error.value=e.message; } finally { loading.value=false; } }
</script>
<template>
  <main class="login">
    <div class="backdrop backdrop-one"></div><div class="backdrop backdrop-two"></div>
    <section class="login-card">
      <div class="login-brand"><span class="brand-mark"><MessageBox /></span><span>Antler<span>RAG</span></span></div>
      <div class="login-heading"><p>ADMIN CONSOLE</p><h1>欢迎回来</h1><span>登录以管理您的智能知识库</span></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" class="login-alert" />
      <el-form class="login-form" @submit.prevent="login">
        <el-form-item label="Email"><el-input v-model="email" autocomplete="username" placeholder="name@company.com"><template #prefix><el-icon><User /></el-icon></template></el-input></el-form-item>
        <el-form-item label="密码"><el-input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码" show-password><template #prefix><el-icon><Lock /></el-icon></template></el-input></el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" class="login-button">登录控制台 <el-icon><ArrowRight /></el-icon></el-button>
      </el-form>
      <p class="login-note"><span></span>安全的企业知识管理平台<span></span></p>
    </section>
  </main>
</template>
<style scoped>
.login { position: relative; display: grid; min-height: 100vh; overflow: hidden; place-items: center; background: #f6f8fe; }.backdrop { position: absolute; border-radius: 50%; filter: blur(2px); }.backdrop-one { width: 550px; height: 550px; top: -270px; left: -180px; background: #dfe7ff; }.backdrop-two { width: 480px; height: 480px; right: -160px; bottom: -250px; background: #e4f5ef; }.login-card { position: relative; width: min(426px, calc(100vw - 38px)); padding: 42px; background: rgba(255,255,255,.93); border: 1px solid rgba(226,231,241,.92); border-radius: 20px; box-shadow: 0 24px 70px rgba(40,56,91,.12); }.login-brand { display: flex; align-items: center; gap: 10px; color: var(--ink); font-size: 20px; font-weight: 800; letter-spacing: -.8px; }.login-brand > span:last-child span { color: var(--brand); }.brand-mark { display: grid; width: 32px; height: 32px; place-items: center; color: white; background: linear-gradient(145deg,#4d74ff,#2448c5); border-radius: 9px; }.login-heading { margin: 36px 0 28px; }.login-heading p { margin: 0 0 10px; color: var(--brand); font-size: 11px; font-weight: 800; letter-spacing: .14em; }.login-heading h1 { margin: 0 0 8px; color: var(--ink); font-size: 28px; letter-spacing: -.8px; }.login-heading span { color: var(--muted); font-size: 13px; }.login-alert { margin-bottom: 18px; }.login-form :deep(.el-form-item) { margin-bottom: 20px; }.login-form :deep(.el-form-item__label) { padding-bottom: 7px; color: #526076; font-size: 12px; font-weight: 700; line-height: 1.2; }.login-form :deep(.el-input__wrapper) { min-height: 43px; }.login-form :deep(.el-input__prefix) { color: #8792a5; }.login-button { display: flex; width: 100%; height: 44px; gap: 8px; margin-top: 4px; font-weight: 700; }.login-note { display: flex; align-items: center; gap: 10px; margin: 31px 0 0; color: #a1aabb; font-size: 11px; white-space: nowrap; }.login-note span { width: 100%; height: 1px; background: #edf0f5; } @media (max-width: 460px) { .login-card { padding: 30px 25px; } }
</style>
