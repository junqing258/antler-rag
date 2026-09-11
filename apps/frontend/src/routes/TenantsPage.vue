<script setup lang="ts">
import { ref, onMounted } from "vue";
import { OfficeBuilding, Plus, Switch, Check, Close } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";
import { api } from "../lib/request";
import { setTenant } from "../composables/useAuth";

const router = useRouter();
const items = ref<any[]>([]);
const name = ref("");
const error = ref("");
const loading = ref(false);

async function load() {
  try {
    items.value = (await api<any>("/api/v1/tenants")).items || [];
  } catch (e: any) {
    error.value = e.message;
  }
}

async function create() {
  if (!name.value.trim()) return;
  loading.value = true;
  error.value = "";
  try {
    const tenant = await api<any>("/api/v1/tenants", {
      method: "POST",
      body: JSON.stringify({ name: name.value }),
    });
    name.value = "";
    ElMessage.success("租户开通成功！以自动切换至新租户");
    setTenant(tenant.id);
    await router.push("/");
  } catch (e: any) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function toggleStatus(item: any) {
  const nextStatus = item.status === "active" ? "disabled" : "active";
  try {
    await api(`/api/v1/tenants/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: nextStatus }),
    });
    ElMessage.success(`租户状态已更新为：${nextStatus === "active" ? "启用" : "停用"}`);
    await load();
  } catch (e: any) {
    ElMessage.error(e.message || "更新状态失败");
  }
}

onMounted(load);
</script>

<template>
  <section class="page">
    <!-- Page Header -->
    <div class="page-heading">
      <div>
        <p class="eyebrow">PLATFORM ADMIN</p>
        <h2>租户管理 (Platform Level)</h2>
        <p class="page-description">
          创建独立租户工作区，管理多租户生命周期。新开通租户将自动完成向量基座初始化。
        </p>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon class="notice" />

    <!-- Create Tenant Panel -->
    <article class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">开通新租户</h3>
          <p class="panel-subtitle">为新团队或客户开启隔离的知识库与检索环境</p>
        </div>
      </div>

      <div class="panel-body">
        <el-form class="tenant-form" @submit.prevent="create">
          <div class="form-item">
            <label class="form-label">租户 / 团队名称</label>
            <el-input v-model="name" placeholder="例如：北极星 AI 实验室" />
          </div>

          <el-button
            type="primary"
            native-type="submit"
            :loading="loading"
            :disabled="!name.trim()"
            class="submit-btn"
          >
            <el-icon class="mr-1"><Plus /></el-icon>创建并进入租户
          </el-button>
        </el-form>
      </div>
    </article>

    <!-- Tenants List Panel -->
    <article class="panel tenant-list">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">平台租户列表 ({{ items.length }})</h3>
          <p class="panel-subtitle">系统当前运行的所有独立租户</p>
        </div>
      </div>

      <div class="panel-body flush table-wrap">
        <el-table :data="items" empty-text="暂无租户">
          <el-table-column prop="name" label="租户名称" min-width="280">
            <template #default="s">
              <span class="tenant-name-cell">
                <span class="tenant-icon"><OfficeBuilding /></span>
                {{ s.row.name }}
              </span>
            </template>
          </el-table-column>

          <el-table-column prop="id" label="租户 ID" min-width="220">
            <template #default="s">
              <span class="mono-id">{{ s.row.id }}</span>
            </template>
          </el-table-column>

          <el-table-column prop="status" label="运行状态" width="160">
            <template #default="s">
              <span class="status" :class="s.row.status">
                {{ s.row.status === "active" ? "正常运行中" : "已暂停" }}
              </span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="130" align="right">
            <template #default="s">
              <el-button
                link
                :type="s.row.status === 'active' ? 'danger' : 'primary'"
                size="small"
                @click="toggleStatus(s.row)"
              >
                <el-icon class="mr-1">
                  <Close v-if="s.row.status === 'active'" />
                  <Check v-else />
                </el-icon>
                {{ s.row.status === "active" ? "停用租户" : "启用租户" }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </article>
  </section>
</template>

<style scoped>
.tenant-form {
  display: flex;
  align-items: flex-end;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
  width: 320px;
}

.submit-btn {
  height: 40px;
  padding: 0 24px;
}

.tenant-list {
  margin-top: 24px;
}

.tenant-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  color: var(--ink, #111827);
}

.tenant-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--brand-soft, #eff6ff);
  color: var(--brand, #3b82f6);
  font-size: 16px;
}

.mono-id {
  font-family: "DM Mono", monospace;
  font-size: 12px;
  color: #64748b;
}

.mr-1 {
  margin-right: 4px;
}

@media (max-width: 540px) {
  .tenant-form {
    flex-direction: column;
    align-items: stretch;
  }
  .form-item {
    width: 100%;
  }
}
</style>
