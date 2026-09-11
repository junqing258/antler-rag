<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Connection, DataBoard, Document, Key, Search, Setting, User } from "@element-plus/icons-vue";
import { api } from "../lib/request";
import { authState, setTenant } from "../composables/useAuth";
const router = useRouter(); const tenants = ref<any[]>([]);
const isAdmin = computed(() => authState.user?.is_platform_admin);
onMounted(async () => { try { tenants.value = (await api<any>("/api/v1/auth/me/tenants")).items; if (!authState.tenantId && tenants.value[0]) setTenant(tenants.value[0].id); } catch { authState.clear(); router.push("/login"); } });
async function logout() { try { await api("/api/v1/auth/logout", { method: "POST" }); } finally { authState.clear(); router.push("/login"); } }
function switchTenant(id: string) { setTenant(id); router.push("/"); }
</script>
<template>
  <el-container class="shell">
    <el-aside width="252px" class="sidebar">
      <router-link to="/" class="brand"><span class="brand-mark"><Connection /></span><span>Antler<span>RAG</span></span></router-link>
      <p class="workspace-label">WORKSPACE</p>
      <el-menu router :default-active="$route.path" class="nav-menu">
        <el-menu-item index="/"><el-icon><DataBoard /></el-icon><span>概览</span></el-menu-item>
        <el-menu-item index="/knowledge-bases"><el-icon><Document /></el-icon><span>知识库</span></el-menu-item>
        <el-menu-item index="/retrieve"><el-icon><Search /></el-icon><span>检索调试</span></el-menu-item>
        <div v-if="authState.user" class="nav-separator">管理</div>
        <el-menu-item v-if="authState.user" index="/members"><el-icon><User /></el-icon><span>成员</span></el-menu-item>
        <el-menu-item v-if="authState.user" index="/api-keys"><el-icon><Key /></el-icon><span>API Key</span></el-menu-item>
        <el-menu-item v-if="isAdmin" index="/tenants"><el-icon><Setting /></el-icon><span>租户管理</span></el-menu-item>
      </el-menu>
      <div class="sidebar-foot"><span class="pulse"></span>服务运行中</div>
    </el-aside>
    <el-container class="main-shell">
      <el-header class="topbar">
        <div class="tenant-picker"><span>当前租户</span><el-select v-model="authState.tenantId" placeholder="选择租户" @change="switchTenant"><el-option v-for="tenant in tenants" :key="tenant.id" :label="tenant.name" :value="tenant.id" /></el-select></div>
        <div class="account"><span class="avatar">{{ authState.user?.email?.slice(0, 1).toUpperCase() }}</span><span class="email">{{ authState.user?.email }}</span><el-button link class="logout" @click="logout">退出</el-button></div>
      </el-header>
      <el-main class="content"><router-view /></el-main>
    </el-container>
  </el-container>
</template>
<style scoped>
.shell { min-height: 100vh; background: var(--canvas); }.sidebar { display: flex; flex-direction: column; padding: 28px 16px 22px; background: #fff; border-right: 1px solid var(--line); }.brand { display: flex; align-items: center; gap: 10px; padding: 0 12px; color: var(--ink); font-size: 20px; font-weight: 800; letter-spacing: -0.8px; text-decoration: none; }.brand > span:last-child span { color: var(--brand); }.brand-mark { display: grid; width: 30px; height: 30px; place-items: center; color: #fff; background: linear-gradient(145deg, #4d74ff, #2448c5); border-radius: 9px; box-shadow: 0 5px 12px rgba(49, 94, 251, .25); }.workspace-label { margin: 42px 12px 9px; color: #9aa4b5; font-size: 10px; font-weight: 800; letter-spacing: .15em; }.nav-menu { border-right: 0; }.nav-menu :deep(.el-menu-item) { height: 46px; margin: 3px 0; border-radius: 9px; color: #667288; font-weight: 700; }.nav-menu :deep(.el-menu-item .el-icon) { margin-right: 11px; font-size: 18px; }.nav-menu :deep(.el-menu-item:hover) { color: var(--brand); background: #f5f7ff; }.nav-menu :deep(.el-menu-item.is-active) { color: var(--brand); background: var(--brand-soft); }.nav-separator { margin: 26px 12px 8px; color: #9aa4b5; font-size: 10px; font-weight: 800; letter-spacing: .15em; text-transform: uppercase; }.sidebar-foot { display: flex; align-items: center; gap: 7px; margin: auto 12px 0; padding-top: 22px; border-top: 1px solid var(--line); color: #8490a4; font-size: 12px; }.pulse { width: 7px; height: 7px; border-radius: 50%; background: #25ae7d; box-shadow: 0 0 0 3px #e6f7f1; }.main-shell { min-width: 0; }.topbar { display: flex; align-items: center; justify-content: space-between; height: 74px; padding: 0 36px; background: rgba(255,255,255,.82); border-bottom: 1px solid var(--line); backdrop-filter: blur(12px); }.tenant-picker { display: flex; align-items: center; gap: 10px; color: #7b8799; font-size: 12px; font-weight: 700; }.tenant-picker :deep(.el-select) { width: 188px; }.tenant-picker :deep(.el-select__wrapper) { min-height: 34px; background: #f7f8fb; }.account { display: flex; align-items: center; gap: 10px; }.avatar { display: grid; width: 30px; height: 30px; place-items: center; color: #315efb; background: #e9eeff; border-radius: 50%; font-size: 12px; font-weight: 800; }.email { color: #536075; font-size: 13px; font-weight: 600; }.logout { margin-left: 8px; color: #7e899a; }.content { padding: 38px 42px; }.content :deep(.el-main) { padding: 0; } @media (max-width: 800px) { .sidebar { width: 72px !important; padding-left: 10px; padding-right: 10px; }.brand { padding: 0; justify-content: center; }.brand > span:last-child, .workspace-label, .nav-menu :deep(.el-menu-item span), .nav-separator, .sidebar-foot, .email, .tenant-picker > span { display: none; }.nav-menu :deep(.el-menu-item) { justify-content: center; padding: 0 !important; }.nav-menu :deep(.el-menu-item .el-icon) { margin: 0; }.topbar { padding: 0 18px; }.content { padding: 26px 18px; } }
</style>
