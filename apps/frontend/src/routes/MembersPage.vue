<script setup lang="ts">
import { ref, onMounted } from "vue";
import { Plus, UserFilled, Delete, User } from "@element-plus/icons-vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api } from "../lib/request";

const items = ref<any[]>([]);
const email = ref("");
const password = ref("");
const role = ref("viewer");
const error = ref("");
const loading = ref(false);

async function load() {
  try {
    items.value = (await api<any>("/api/v1/users")).items || [];
  } catch (e: any) {
    error.value = e.message;
  }
}

async function add() {
  if (!email.value.trim() || !password.value) return;
  loading.value = true;
  error.value = "";
  try {
    await api("/api/v1/users", {
      method: "POST",
      body: JSON.stringify({
        email: email.value,
        initial_password: password.value,
        role: role.value,
      }),
    });
    email.value = "";
    password.value = "";
    ElMessage.success("成员成功添加！");
    await load();
  } catch (e: any) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function confirmRemove(item: any) {
  try {
    await ElMessageBox.confirm(
      `确定要停用用户 "${item.email}" 吗？`,
      "停用用户确认",
      {
        confirmButtonText: "确认移除",
        cancelButtonText: "取消",
        type: "warning",
      },
    );
    await api(`/api/v1/users/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status: "disabled" }),
    });
    ElMessage.success("用户已停用");
    await load();
  } catch {
    // User cancelled
  }
}

function getRoleTagType(r: string) {
  if (r === "admin") return "danger";
  if (r === "editor") return "warning";
  return "info";
}

function getRoleLabel(r: string) {
  if (r === "admin") return "管理员";
  if (r === "editor") return "编辑者";
  return "只读成员";
}

onMounted(load);
</script>

<template>
  <section class="page">
    <!-- Page Header -->
    <div class="page-heading">
      <div>
        <p class="eyebrow">ACCESS CONTROL</p>
        <h2>用户管理</h2>
        <p class="page-description">
          管理工作区用户，并通过全局角色控制知识库访问与管理权限。
        </p>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon class="notice" />

    <!-- Add Member Form Panel -->
    <article class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">添加新成员</h3>
          <p class="panel-subtitle">首次初始化的账号须在 24 小时内登录并修改密码</p>
        </div>
      </div>

      <div class="panel-body">
        <el-form class="member-form" @submit.prevent="add">
          <div class="form-item">
            <label class="form-label">成员 Email 邮箱</label>
            <el-input v-model="email" placeholder="member@company.com" />
          </div>

          <div class="form-item">
            <label class="form-label">初始临时密码</label>
            <el-input
              v-model="password"
              type="password"
              show-password
              placeholder="设置临时登录密码"
            />
          </div>

          <div class="form-item role-item">
            <label class="form-label">权限角色</label>
            <el-select v-model="role">
              <el-option value="admin" label="Administrator (管理员)" />
              <el-option value="editor" label="Editor (编辑者)" />
              <el-option value="viewer" label="Viewer (只读成员)" />
            </el-select>
          </div>

          <el-button
            type="primary"
            native-type="submit"
            :loading="loading"
            :disabled="!email.trim() || !password"
            class="submit-btn"
          >
            <el-icon class="mr-1"><Plus /></el-icon>添加成员
          </el-button>
        </el-form>
      </div>
    </article>

    <!-- Member List Panel -->
    <article class="panel member-list">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">成员列表 ({{ items.length }})</h3>
          <p class="panel-subtitle">拥有当前工作区访问权限的所有团队成员</p>
        </div>
      </div>

      <div class="panel-body flush table-wrap">
        <el-table :data="items" empty-text="暂无成员">
          <el-table-column prop="email" label="成员 Email" min-width="260">
            <template #default="s">
              <div class="member-email-cell">
                <span class="avatar-chip">
                  {{ s.row.email.slice(0, 1).toUpperCase() }}
                </span>
                <span>{{ s.row.email }}</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column prop="role" label="分配角色" min-width="160">
            <template #default="s">
              <el-tag
                :type="getRoleTagType(s.row.role)"
                effect="light"
                size="default"
              >
                {{ getRoleLabel(s.row.role) }} ({{ s.row.role }})
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column prop="status" label="状态" width="140">
            <template #default="s">
              <span class="status" :class="s.row.status">{{ s.row.status }}</span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="110" align="right">
            <template #default="s">
              <el-button
                link
                type="danger"
                size="small"
                @click="confirmRemove(s.row)"
              >
                <el-icon class="mr-1"><Delete /></el-icon>移除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </article>
  </section>
</template>

<style scoped>
.member-form {
  display: grid;
  grid-template-columns: 1.2fr 1fr 180px auto;
  align-items: flex-end;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
}

.submit-btn {
  height: 40px;
  padding: 0 24px;
}

.member-list {
  margin-top: 24px;
}

.member-email-cell {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  color: var(--ink, #111827);
}

.avatar-chip {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--brand-soft, #eff6ff);
  color: var(--brand, #3b82f6);
  font-size: 12px;
  font-weight: 800;
}

.mr-1 {
  margin-right: 4px;
}

@media (max-width: 900px) {
  .member-form {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 540px) {
  .member-form {
    grid-template-columns: 1fr;
  }
}
</style>
