<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import {
  DataBoard,
  Document,
  Key,
  Search,
  User,
  SwitchButton,
  Expand,
  Fold,
  Reading,
  Operation,
} from "@element-plus/icons-vue";
import { api } from "../lib/request";
import { authState } from "../composables/useAuth";
import ApiCodeSnippetModal from "../components/ApiCodeSnippetModal.vue";
import BrandLogo from "../components/BrandLogo.vue";

const router = useRouter();
const route = useRoute();
const isCollapsed = ref(false);
const showCodeModal = ref(false);
const isAdmin = computed(() => authState.user?.role === "admin");
async function logout() {
  try {
    await api("/api/v1/auth/logout", { method: "POST" });
  } finally {
    authState.clear();
    router.push("/login");
  }
}
</script>

<template>
  <div class="console-layout">
    <aside class="console-sidebar" :class="{ collapsed: isCollapsed }">
      <div class="console-brand">
        <BrandLogo class="console-logo" />
        <div v-if="!isCollapsed">
          <strong>Antler Knowledge</strong><span>V2.4.0-CLUSTER</span>
        </div>
        <button v-if="!isCollapsed" @click="isCollapsed = true">
          <el-icon><Fold /></el-icon>
        </button>
      </div>
      <nav class="console-nav">
        <p v-if="!isCollapsed">CONTROL PLANE</p>
        <router-link to="/"
          ><el-icon><DataBoard /></el-icon
          ><span v-if="!isCollapsed">概览 (Overview)</span></router-link
        ><router-link to="/knowledge-bases"
          ><el-icon><Document /></el-icon
          ><span v-if="!isCollapsed"
            >知识库 (Knowledge Bases)</span
          ></router-link
        ><router-link to="/retrieve"
          ><el-icon><Search /></el-icon
          ><span v-if="!isCollapsed"
            >检索测试 (Search Sandbox)</span
          ></router-link
        ><router-link v-if="isAdmin" to="/members"
          ><el-icon><User /></el-icon
          ><span v-if="!isCollapsed">用户管理 (Users)</span></router-link
        ><router-link v-if="isAdmin" to="/api-keys"
          ><el-icon><Key /></el-icon
          ><span v-if="!isCollapsed">API Key</span></router-link
        >
      </nav>
      <!-- <div class="engine-status" v-if="!isCollapsed">
        <div><span></span><b>RRF Engine</b><em>ONLINE</em></div>
        <section>
          <small>TELEMETRY</small><strong>99.98% uptime</strong><i>14ms p99</i>
        </section>
      </div> -->
    </aside>
    <div class="console-main">
      <header class="console-topbar">
        <div class="topbar-context">
          <button
            v-if="isCollapsed"
            class="expand"
            @click="isCollapsed = false"
          >
            <el-icon><Expand /></el-icon>
          </button>
          <div class="kb-context">
            <el-icon><Document /></el-icon
            ><span>{{
              route.path === "/retrieve"
                ? "检索调试"
                : route.path === "/knowledge-bases"
                  ? "知识库管理"
                  : "Antler Console"
            }}</span>
          </div>
          <div class="cluster-health">
            <i></i><span>Qdrant-Node-01</span><b>Healthy</b>
          </div>
        </div>
        <div class="topbar-actions">
          <a href="#"
            ><el-icon><Reading /></el-icon> Docs</a
          ><button class="api-ready" @click="showCodeModal = true">
            <b>API</b> v1 Ready
          </button>
          <div class="user-identity">
            <div>
              <strong>{{ isAdmin ? "Administrator" : authState.user?.role }}</strong
              ><span>{{ authState.user?.email }}</span>
            </div>
            <i>{{ authState.user?.email?.slice(0, 1).toUpperCase() }}</i
            ><button title="退出登录" @click="logout">
              <el-icon><SwitchButton /></el-icon>
            </button>
          </div>
        </div>
      </header>
      <main class="console-content"><router-view /></main>
    </div>
    <ApiCodeSnippetModal v-model:visible="showCodeModal" />
  </div>
</template>

<style scoped>
.console-layout {
  display: flex;
  min-height: 100vh;
  color: #0f172a;
  background: #f8fafc;
}
.console-sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  width: 304px;
  height: 100vh;
  flex: 0 0 auto;
  background: #fff;
  border-right: 1px solid #e2e8f0;
  transition: width 0.2s;
}
.console-sidebar.collapsed {
  width: 68px;
}
.console-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 76px;
  padding: 0 20px;
  border-bottom: 1px solid #f1f5f9;
}
.console-logo {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
}
.collapsed .console-brand {
  justify-content: center;
  padding: 0;
}
.console-brand div {
  display: flex;
  min-width: 0;
  flex-direction: column;
}
.console-brand strong {
  color: var(--brand);
  white-space: nowrap;
  font-size: 15px;
}
.console-brand div span,
.console-nav p {
  color: #94a3b8;
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
}
.console-brand div span {
  color: var(--brand-deep);
}
.console-brand button {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
}
.console-nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  padding: 19px 14px;
}
.console-nav p {
  margin: 2px 10px 10px;
  font-weight: 600;
}
.console-nav a {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 42px;
  padding: 0 13px;
  color: #475569;
  border: 1px solid transparent;
  border-radius: 8px;
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
}
.console-nav a .el-icon {
  color: #94a3b8;
  font-size: 18px;
}
.console-nav a:hover {
  background: #f8fafc;
}
.console-nav a.router-link-exact-active {
  color: #0369a1;
  background: #f0f9ff;
  border-color: #e0f2fe;
  font-weight: 700;
}
.console-nav a.router-link-exact-active .el-icon {
  color: #0284c7;
}
.collapsed .console-nav {
  padding: 19px 10px;
}
.collapsed .console-nav a {
  justify-content: center;
  padding: 0;
}
.engine-status {
  margin: 14px;
  padding: 13px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}
.engine-status > div {
  display: flex;
  align-items: center;
  gap: 7px;
  font:
    11px "JetBrains Mono",
    monospace;
  color: #475569;
}
.engine-status > div span,
.cluster-health i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
}
.engine-status em {
  margin-left: auto;
  color: #059669;
  font-style: normal;
}
.engine-status section {
  position: relative;
  display: flex;
  flex-direction: column;
  margin-top: 12px;
  padding: 9px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.engine-status small {
  color: #94a3b8;
  font:
    10px "JetBrains Mono",
    monospace;
}
.engine-status strong {
  color: #0284c7;
  font:
    600 12px "JetBrains Mono",
    monospace;
}
.engine-status section i {
  position: absolute;
  right: 9px;
  bottom: 10px;
  color: #64748b;
  font:
    11px "JetBrains Mono",
    monospace;
  font-style: normal;
}
.console-main {
  min-width: 0;
  flex: 1;
}
.console-topbar {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 76px;
  padding: 0 32px;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid #e2e8f0;
}
.topbar-context,
.topbar-actions,
.user-identity,
.tenant-picker,
.kb-context,
.cluster-health {
  display: flex;
  align-items: center;
}
.topbar-context {
  gap: 14px;
}
.tenant-picker,
.kb-context {
  gap: 8px;
  height: 38px;
  padding: 0 11px;
  color: #1e293b;
  background: #f8fafc;
  border: 1px solid #dbe3ed;
  border-radius: 8px;
  font-size: 13px;
}
.tenant-picker > .el-icon,
.kb-context > .el-icon {
  color: #0284c7;
}
.tenant-picker :deep(.el-select__wrapper) {
  min-height: 32px !important;
  padding: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
}
.tenant-picker :deep(.el-select) {
  width: 145px;
}
.kb-context {
  font-family: "JetBrains Mono", monospace;
  font-size: 12px;
}
.cluster-health {
  gap: 7px;
  height: 32px;
  padding: 0 12px;
  color: #047857;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 7px;
  font:
    11px "JetBrains Mono",
    monospace;
}
.cluster-health b {
  font-weight: 600;
}
.topbar-actions {
  gap: 20px;
}
.topbar-actions > a {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #475569;
  text-decoration: none;
  font-size: 13px;
}
.api-ready {
  padding: 6px 10px;
  color: #334155;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font:
    11px "JetBrains Mono",
    monospace;
  cursor: pointer;
}
.api-ready b {
  color: #0284c7;
}
.user-identity {
  gap: 10px;
  padding-left: 14px;
  border-left: 1px solid #e2e8f0;
}
.user-identity div {
  display: flex;
  flex-direction: column;
  text-align: right;
}
.user-identity strong {
  font-size: 13px;
}
.user-identity span {
  max-width: 145px;
  overflow: hidden;
  color: #94a3b8;
  font:
    11px "JetBrains Mono",
    monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-identity > i {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  color: #fff;
  background: #0284c7;
  border-radius: 50%;
  font-style: normal;
  font-weight: 700;
}
.user-identity button,
.expand {
  padding: 0;
  color: #94a3b8;
  background: transparent;
  border: 0;
  cursor: pointer;
  font-size: 18px;
}
.console-content {
  min-height: calc(100vh - 76px);
  padding: 26px 38px 54px;
}
@media (max-width: 1100px) {
  .console-sidebar {
    width: 240px;
  }
  .cluster-health {
    display: none;
  }
  .console-content {
    padding: 24px;
  }
}
@media (max-width: 780px) {
  .console-sidebar {
    width: 62px;
  }
  .console-brand {
    padding: 0 13px;
  }
  .console-brand div,
  .console-brand button,
  .console-nav span,
  .console-nav p,
  .engine-status,
  .kb-context,
  .topbar-actions > a,
  .api-ready,
  .user-identity div {
    display: none;
  }
  .console-nav {
    padding: 19px 8px;
  }
  .console-nav a {
    justify-content: center;
    padding: 0;
  }
  .console-topbar {
    height: 64px;
    padding: 0 16px;
  }
  .console-content {
    padding: 18px 14px;
  }
  .tenant-picker :deep(.el-select) {
    width: 110px;
  }
  .user-identity {
    padding-left: 0;
    border: 0;
  }
}
</style>
