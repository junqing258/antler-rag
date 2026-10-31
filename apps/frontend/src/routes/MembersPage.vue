<script setup lang="ts">
import { ref, onMounted } from "vue";
import { Delete } from "@element-plus/icons-vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api } from "../lib/request";

const items = ref<any[]>([]);
const error = ref("");

async function load() {
  try {
    items.value = (await api<any>("/api/v1/users")).items || [];
  } catch (e: any) {
    error.value = e.message;
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
    // 用户取消操作
  }
}

async function updateMember(item: any, patch: Record<string, string>) {
  try {
    await api(`/api/v1/users/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    await load();
  } catch (cause: any) {
    error.value = cause.message;
  }
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

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      class="notice"
    />

    <el-alert
      title="成员首次使用 Antler 账号登录后会自动加入，默认为只读成员。"
      type="info"
      :closable="false"
    />

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
              <el-select
                :model-value="s.row.role"
                @change="(role: string) => updateMember(s.row, { role })"
              >
                <el-option value="admin" label="管理员" />
                <el-option value="editor" label="编辑者" />
                <el-option value="viewer" label="只读成员" />
              </el-select>
            </template>
          </el-table-column>

          <el-table-column prop="status" label="状态" width="140">
            <template #default="s">
              <span class="status" :class="s.row.status">{{
                s.row.status
              }}</span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="110" align="right">
            <template #default="s">
              <el-button
                v-if="s.row.status === 'active'"
                link
                type="danger"
                size="small"
                @click="confirmRemove(s.row)"
              >
                <el-icon class="mr-1"><Delete /></el-icon>移除
              </el-button>
              <el-button
                v-if="s.row.status === 'disabled'"
                link
                @click="updateMember(s.row, { status: 'active' })"
                >启用</el-button
              >
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
