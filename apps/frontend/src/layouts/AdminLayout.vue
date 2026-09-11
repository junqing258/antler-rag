<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import {
  Connection,
  DataBoard,
  Document,
  Key,
  Search,
  Setting,
  User,
  SwitchButton,
  OfficeBuilding,
  Expand,
  Fold,
  ArrowRight,
  Code,
} from "@element-plus/icons-vue";
import { api } from "../lib/request";
import { authState, setTenant } from "../composables/useAuth";
import ApiCodeSnippetModal from "../components/ApiCodeSnippetModal.vue";

const router = useRouter();
const route = useRoute();
const tenants = ref<any[]>([]);
const isCollapsed = ref(false);
const showCodeModal = ref(false);

const isAdmin = computed(() => authState.user?.is_platform_admin);

const activeTenantName = computed(() => {
  const t = tenants.value.find((item) => item.id === authState.tenantId);
  return t ? t.name : "选择租户";
});

const currentBreadcrumb = computed(() => {
  const pathMap: Record<string, string> = {
    "/": "工作区概览",
    "/knowledge-bases": "知识库管理",
    "/retrieve": "检索调试实验室",
    "/members": "成员管理",
    "/api-keys": "API Key 密钥",
    "/tenants": "平台租户管理",
  };
  return pathMap[route.path] || "控制台";
});

onMounted(async () => {
  try {
    tenants.value = (await api<any>("/api/v1/auth/me/tenants")).items || [];
    if (!authState.tenantId && tenants.value[0]) setTenant(tenants.value[0].id);
  } catch {
    authState.clear();
    router.push("/login");
  }
});

async function logout() {
  try {
    await api("/api/v1/auth/logout", { method: "POST" });
  } finally {
    authState.clear();
    router.push("/login");
  }
}

function switchTenant(id: string) {
  setTenant(id);
  router.push("/");
}

function toggleSidebar() {
  isCollapsed.value = !isCollapsed.value;
}
</script>

<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="app-sidebar" :class="{ collapsed: isCollapsed }">
      <div class="sidebar-header">
        <router-link to="/" class="sidebar-brand">
          <span class="brand-logo"><Connection /></span>
          <div v-if="!isCollapsed" class="brand-info">
            <span class="brand-title">Antler <span>RAG</span></span>
            <span class="brand-badge">v0.1.0</span>
          </div>
        </router-link>

        <button
          v-if="!isCollapsed"
          class="icon-btn collapse-btn"
          title="折叠侧边栏"
          @click="toggleSidebar"
        >
          <el-icon><Fold /></el-icon>
        </button>
      </div>

      <!-- Navigation Links -->
      <nav class="sidebar-nav">
        <div v-if="!isCollapsed" class="nav-section-title">核心工作区</div>
        
        <router-link to="/" class="nav-item" :class="{ active: route.path === '/' }">
          <el-icon class="nav-icon"><DataBoard /></el-icon>
          <span v-if="!isCollapsed" class="nav-label">工作区概览</span>
        </router-link>

        <router-link
          to="/knowledge-bases"
          class="nav-item"
          :class="{ active: route.path === '/knowledge-bases' }"
        >
          <el-icon class="nav-icon"><Document /></el-icon>
          <span v-if="!isCollapsed" class="nav-label">知识库管理</span>
        </router-link>

        <router-link
          to="/retrieve"
          class="nav-item"
          :class="{ active: route.path === '/retrieve' }"
        >
          <el-icon class="nav-icon"><Search /></el-icon>
          <span v-if="!isCollapsed" class="nav-label">检索调试实验室</span>
        </router-link>

        <div v-if="authState.user && !isCollapsed" class="nav-section-title">
          系统管理
        </div>

        <router-link
          v-if="authState.user"
          to="/members"
          class="nav-item"
          :class="{ active: route.path === '/members' }"
        >
          <el-icon class="nav-icon"><User /></el-icon>
          <span v-if="!isCollapsed" class="nav-label">成员管理</span>
        </router-link>

        <router-link
          v-if="authState.user"
          to="/api-keys"
          class="nav-item"
          :class="{ active: route.path === '/api-keys' }"
        >
          <el-icon class="nav-icon"><Key /></el-icon>
          <span v-if="!isCollapsed" class="nav-label">API Key 密钥</span>
        </router-link>

        <router-link
          v-if="isAdmin"
          to="/tenants"
          class="nav-item"
          :class="{ active: route.path === '/tenants' }"
        >
          <el-icon class="nav-icon"><Setting /></el-icon>
          <span v-if="!isCollapsed" class="nav-label">租户管理</span>
        </router-link>
      </nav>

      <!-- Sidebar Footer -->
      <div class="sidebar-footer">
        <div class="status-indicator">
          <span class="status-dot"></span>
          <span v-if="!isCollapsed" class="status-text">SQLite & Chroma 运行中</span>
        </div>
      </div>
    </aside>

    <!-- Main Container -->
    <div class="app-main-wrapper">
      <!-- Topbar Header -->
      <header class="app-topbar">
        <div class="topbar-left">
          <button
            v-if="isCollapsed"
            class="icon-btn expand-btn"
            title="展开侧边栏"
            @click="toggleSidebar"
          >
            <el-icon><Expand /></el-icon>
          </button>

          <div class="breadcrumb-bar">
            <span class="crumb-root">Antler</span>
            <el-icon class="crumb-sep"><ArrowRight /></el-icon>
            <span class="crumb-current">{{ currentBreadcrumb }}</span>
          </div>
        </div>

        <div class="topbar-right">
          <!-- Quick Code Modal Toggle -->
          <el-button
            size="small"
            class="quick-code-btn"
            @click="showCodeModal = true"
          >
            <el-icon class="mr-1"><Code /></el-icon>API 代码
          </el-button>

          <!-- Tenant Switcher Dropdown -->
          <div class="tenant-selector-wrapper">
            <el-icon class="tenant-icon"><OfficeBuilding /></el-icon>
            <el-select
              v-model="authState.tenantId"
              placeholder="选择租户"
              size="default"
              class="tenant-select"
              @change="switchTenant"
            >
              <el-option
                v-for="tenant in tenants"
                :key="tenant.id"
                :label="tenant.name"
                :value="tenant.id"
              />
            </el-select>
          </div>

          <!-- User Profile & Logout -->
          <div class="user-profile">
            <div class="avatar-box">
              {{ authState.user?.email?.slice(0, 1).toUpperCase() }}
            </div>

            <div class="user-meta">
              <span class="user-email">{{ authState.user?.email }}</span>
              <span class="user-role">
                {{ isAdmin ? "Platform Admin" : "Tenant Member" }}
              </span>
            </div>

            <button class="logout-btn" title="退出登录" @click="logout">
              <el-icon><SwitchButton /></el-icon>
            </button>
          </div>
        </div>
      </header>

      <!-- Main Body View -->
      <main class="app-content">
        <div class="content-container">
          <router-view />
        </div>
      </main>
    </div>

    <!-- API Snippet Modal -->
    <ApiCodeSnippetModal v-model:visible="showCodeModal" />
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  width: 100vw;
  background: #f8fafc;
  color: #0f172a;
}

/* Sidebar Styling (Modern Dark Slate theme) */
.app-sidebar {
  display: flex;
  flex-direction: column;
  width: 250px;
  background: #0f172a;
  color: #f8fafc;
  flex-shrink: 0;
  transition: width 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  z-index: 20;
}

.app-sidebar.collapsed {
  width: 72px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: #ffffff;
}

.brand-logo {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  color: #ffffff;
  font-size: 20px;
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.4);
}

.brand-info {
  display: flex;
  flex-direction: column;
}

.brand-title {
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #ffffff;
}

.brand-title span {
  color: #60a5fa;
}

.brand-badge {
  font-family: "DM Mono", monospace;
  font-size: 10px;
  color: #94a3b8;
}

.icon-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s;
}

.icon-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 18px 12px;
  flex: 1;
}

.nav-section-title {
  margin: 16px 10px 6px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.12em;
  color: #64748b;
  text-transform: uppercase;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 42px;
  padding: 0 12px;
  border-radius: 10px;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  transition: all 0.2s ease;
}

.nav-icon {
  font-size: 18px;
  color: #64748b;
  transition: color 0.2s;
}

.nav-item:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.07);
}

.nav-item:hover .nav-icon {
  color: #60a5fa;
}

.nav-item.active {
  color: #ffffff;
  background: var(--brand, #3b82f6);
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.35);
}

.nav-item.active .nav-icon {
  color: #ffffff;
}

.app-sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 0;
}

.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
  animation: pulseGlow 2s infinite;
}

/* Main Layout Wrapper */
.app-main-wrapper {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

/* Topbar Header */
.app-topbar {
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 28px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid #e2e8f0;
  z-index: 10;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.breadcrumb-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
}

.crumb-root {
  color: #64748b;
}

.crumb-sep {
  font-size: 12px;
  color: #cbd5e1;
}

.crumb-current {
  color: #0f172a;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 18px;
}

.quick-code-btn {
  font-weight: 700;
  border-radius: 8px;
}

.tenant-selector-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 10px;
  background: #f1f5f9;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
}

.tenant-icon {
  font-size: 16px;
  color: #3b82f6;
}

.tenant-select {
  width: 180px;
}

.tenant-select :deep(.el-select__wrapper) {
  background: transparent !important;
  box-shadow: none !important;
  min-height: 32px !important;
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-left: 12px;
  border-left: 1px solid #e2e8f0;
}

.avatar-box {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #3b82f6;
  color: #ffffff;
  font-size: 13px;
  font-weight: 800;
}

.user-meta {
  display: flex;
  flex-direction: column;
}

.user-email {
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}

.user-role {
  font-size: 10px;
  color: #64748b;
  font-weight: 600;
}

.logout-btn {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  color: #94a3b8;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.logout-btn:hover {
  background: #fee2e2;
  color: #ef4444;
}

/* Main Content Area */
.app-content {
  flex: 1;
  padding: 28px 36px;
  overflow-y: auto;
}

.content-container {
  max-width: 1320px;
  margin: 0 auto;
}

.mr-1 {
  margin-right: 4px;
}

@media (max-width: 850px) {
  .user-meta,
  .crumb-root,
  .crumb-sep {
    display: none;
  }
  .app-content {
    padding: 20px 16px;
  }
  .app-topbar {
    padding: 0 16px;
  }
}
</style>
