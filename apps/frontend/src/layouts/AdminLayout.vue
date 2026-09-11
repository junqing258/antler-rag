<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "../lib/request";
import { authState, setTenant } from "../composables/useAuth";
const router = useRouter(); const tenants = ref<any[]>([]);
const isAdmin = computed(() => authState.user?.is_platform_admin);
onMounted(async () => { try { tenants.value = (await api<any>("/api/v1/auth/me/tenants")).items; if (!authState.tenantId && tenants.value[0]) setTenant(tenants.value[0].id); } catch { authState.clear(); router.push("/login"); } });
async function logout() { try { await api("/api/v1/auth/logout", { method: "POST" }); } finally { authState.clear(); router.push("/login"); } }
function switchTenant(id: string) { setTenant(id); router.push("/"); }
</script>
<template>
  <el-container class="shell"><el-aside width="220px"><h1>Antler RAG</h1><el-menu router :default-active="$route.path"><el-menu-item index="/">概览</el-menu-item><el-menu-item index="/knowledge-bases">知识库</el-menu-item><el-menu-item index="/retrieve">检索调试</el-menu-item><el-menu-item v-if="authState.user" index="/members">成员</el-menu-item><el-menu-item v-if="authState.user" index="/api-keys">API Key</el-menu-item><el-menu-item v-if="isAdmin" index="/tenants">租户管理</el-menu-item></el-menu></el-aside>
  <el-container><el-header><el-select v-model="authState.tenantId" placeholder="选择租户" @change="switchTenant"><el-option v-for="tenant in tenants" :key="tenant.id" :label="tenant.name" :value="tenant.id" /></el-select><span class="email">{{ authState.user?.email }}</span><el-button link @click="logout">退出</el-button></el-header><el-main><router-view /></el-main></el-container></el-container>
</template>
<style scoped>.shell{min-height:100vh}.el-aside{border-right:1px solid #e5e7eb;padding:16px}.el-header{display:flex;align-items:center;gap:12px;border-bottom:1px solid #e5e7eb}.email{margin-left:auto;color:#6b7280}h1{font-size:20px}</style>
