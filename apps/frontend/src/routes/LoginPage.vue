<script setup lang="ts">
import { ref } from "vue"; import { useRouter } from "vue-router"; import { api } from "../lib/request"; import { saveAuth } from "../composables/useAuth";
const router = useRouter(); const email = ref(""); const password = ref(""); const error = ref(""); const loading = ref(false);
async function login() { loading.value=true; error.value=""; try { const result = await api<any>("/api/v1/auth/login", {method:"POST",body:JSON.stringify({email:email.value,password:password.value})}); saveAuth(result.token,result.user); router.push("/"); } catch (e:any) { error.value=e.message; } finally { loading.value=false; } }
</script>
<template><main class="login"><el-card><h1>Antler RAG</h1><el-alert v-if="error" :title="error" type="error" :closable="false" /><el-form @submit.prevent="login"><el-form-item label="Email"><el-input v-model="email" autocomplete="username" /></el-form-item><el-form-item label="密码"><el-input v-model="password" type="password" autocomplete="current-password" show-password /></el-form-item><el-button type="primary" native-type="submit" :loading="loading">登录</el-button></el-form></el-card></main></template>
<style scoped>.login{display:grid;min-height:100vh;place-items:center}.el-card{width:min(400px,90vw)}</style>
