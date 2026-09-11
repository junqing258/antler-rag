<script setup lang="ts">
import { ref, onMounted } from "vue";
import {
  Key,
  Plus,
  WarningFilled,
  CopyDocument,
  Delete,
  Operation,
} from "@element-plus/icons-vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api } from "../lib/request";
import ApiCodeSnippetModal from "../components/ApiCodeSnippetModal.vue";

const items = ref<any[]>([]);
const name = ref("");
const scopes = ref(["retrieve", "chat"]);
const secret = ref("");
const error = ref("");
const loading = ref(false);
const showCodeModal = ref(false);

async function load() {
  try {
    items.value = (await api<any>("/api/v1/api-keys")).items || [];
  } catch (e: any) {
    error.value = e.message;
  }
}

async function create() {
  if (!name.value.trim()) return;
  loading.value = true;
  error.value = "";
  try {
    const result = await api<any>("/api/v1/api-keys", {
      method: "POST",
      body: JSON.stringify({
        name: name.value,
        scopes: scopes.value,
        expires_in_days: 90,
      }),
    });
    secret.value = result.api_key;
    name.value = "";
    ElMessage.success("API Key 创建成功！");
    await load();
  } catch (e: any) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}

async function confirmRevoke(item: any) {
  try {
    await ElMessageBox.confirm(
      `确定要吊销 API Key "${item.name}" (${item.key_prefix}...) 吗？吊销后使用此 Key 的服务将无法访问数据 API。`,
      "吊销凭证确认",
      {
        confirmButtonText: "确认吊销",
        cancelButtonText: "取消",
        type: "warning",
      },
    );
    await api(`/api/v1/api-keys/${item.id}`, { method: "DELETE" });
    ElMessage.success("API Key 已吊销");
    await load();
  } catch {
    // User cancelled
  }
}

function copySecret() {
  navigator.clipboard.writeText(secret.value);
  ElMessage.success("API Key 已成功复制到剪贴板！");
}

onMounted(load);
</script>

<template>
  <section class="page">
    <!-- Page Header -->
    <div class="page-heading">
      <div>
        <p class="eyebrow">DEVELOPER ACCESS</p>
        <h2>API Key 管理</h2>
        <p class="page-description">
          为您的应用、Agent 或服务端程序创建独立的 API 访问密钥，精准控制可调用权限范畴。
        </p>
      </div>

      <el-button type="primary" plain size="default" @click="showCodeModal = true">
        <el-icon class="mr-1"><Operation /></el-icon>查看 SDK / API 示例
      </el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon class="notice" />

    <!-- Newly Created Secret Alert Banner -->
    <div v-if="secret" class="secret-box">
      <div class="secret-icon"><WarningFilled /></div>
      <div class="secret-content">
        <strong>请立即复制并妥善保管您的 API Key</strong>
        <p>出于安全原因，此明文密钥只会在此展示一次，刷新或离开页面后将无法再次查看。</p>
        <div class="secret-code-bar">
          <code class="secret-code">{{ secret }}</code>
          <el-button type="primary" size="small" @click="copySecret">
            <el-icon class="mr-1"><CopyDocument /></el-icon>一键复制 Key
          </el-button>
        </div>
      </div>
    </div>

    <!-- Create Key Panel -->
    <article class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">创建新访问凭证</h3>
          <p class="panel-subtitle">默认有效期为 90 天，勾选该密钥允许执行的操作权限 (Scope)</p>
        </div>
      </div>

      <div class="panel-body">
        <el-form class="key-form" @submit.prevent="create">
          <div class="form-group name-group">
            <label class="form-label">凭证名称 / 应用标识</label>
            <el-input v-model="name" placeholder="例如：Customer Support Agent" />
          </div>

          <div class="form-group scope-group">
            <label class="form-label">授予定位权限 (Scopes)</label>
            <el-checkbox-group v-model="scopes" class="scope-checkboxes">
              <el-checkbox label="retrieve">
                <el-tag type="primary" size="small" effect="plain">retrieve</el-tag> 检索向量
              </el-checkbox>
              <el-checkbox label="chat">
                <el-tag type="success" size="small" effect="plain">chat</el-tag> 问答对话
              </el-checkbox>
              <el-checkbox label="documents:read">
                <el-tag type="info" size="small" effect="plain">documents:read</el-tag> 读取文档
              </el-checkbox>
              <el-checkbox label="documents:write">
                <el-tag type="warning" size="small" effect="plain">documents:write</el-tag> 写入文档
              </el-checkbox>
              <el-checkbox label="documents:delete">
                <el-tag type="danger" size="small" effect="plain">documents:delete</el-tag> 删除文档
              </el-checkbox>
            </el-checkbox-group>
          </div>

          <el-button
            type="primary"
            native-type="submit"
            :loading="loading"
            :disabled="!name.trim() || !scopes.length"
            class="submit-key-btn"
          >
            <el-icon class="mr-1"><Plus /></el-icon>生成 API Key
          </el-button>
        </el-form>
      </div>
    </article>

    <!-- Keys List Panel -->
    <article class="panel key-list">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">已创建的 Keys ({{ items.length }})</h3>
          <p class="panel-subtitle">建议定期轮换凭证，及时吊销长期未使用的访问密钥</p>
        </div>
      </div>

      <div class="panel-body flush table-wrap">
        <el-table :data="items" empty-text="当前租户尚未创建 API Key">
          <el-table-column prop="name" label="凭证名称" min-width="200">
            <template #default="s">
              <span class="key-name-cell">
                <el-icon class="key-icon"><Key /></el-icon>
                {{ s.row.name }}
              </span>
            </template>
          </el-table-column>

          <el-table-column prop="key_prefix" label="Key 前缀" width="160">
            <template #default="s">
              <span class="mono-prefix">{{ s.row.key_prefix }}...</span>
            </template>
          </el-table-column>

          <el-table-column label="权限 Scopes" min-width="240">
            <template #default="s">
              <div class="scope-tags">
                <el-tag
                  v-for="sc in s.row.scopes"
                  :key="sc"
                  size="small"
                  effect="light"
                  class="scope-tag"
                >
                  {{ sc }}
                </el-tag>
              </div>
            </template>
          </el-table-column>

          <el-table-column prop="expires_at" label="到期时间" width="180" />

          <el-table-column label="操作" width="110" align="right">
            <template #default="s">
              <el-button
                link
                type="danger"
                size="small"
                @click="confirmRevoke(s.row)"
              >
                <el-icon class="mr-1"><Delete /></el-icon>吊销
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </article>

    <!-- Code Modal -->
    <ApiCodeSnippetModal v-model:visible="showCodeModal" />
  </section>
</template>

<style scoped>
.secret-box {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  padding: 20px 24px;
  background: #fefce8;
  border: 1px solid #fef08a;
  border-radius: 14px;
  box-shadow: var(--shadow-sm);
}

.secret-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: #fef08a;
  color: #ca8a04;
  font-size: 20px;
  flex-shrink: 0;
}

.secret-content strong {
  display: block;
  font-size: 15px;
  color: #854d0e;
}

.secret-content p {
  margin: 4px 0 12px;
  font-size: 13px;
  color: #a16207;
}

.secret-code-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.secret-code {
  padding: 8px 14px;
  background: #ffffff;
  border: 1px solid #fde047;
  border-radius: 8px;
  font-family: "DM Mono", monospace;
  font-size: 13px;
  font-weight: 700;
  color: #713f12;
}

.key-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-group {
  display: flex;
  flex-direction: column;
}

.name-group {
  max-width: 420px;
}

.scope-checkboxes {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.submit-key-btn {
  width: fit-content;
  height: 40px;
  padding: 0 24px;
}

.key-list {
  margin-top: 24px;
}

.key-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: var(--ink, #111827);
}

.key-icon {
  color: var(--brand, #3b82f6);
  font-size: 16px;
}

.mono-prefix {
  font-family: "DM Mono", monospace;
  font-size: 12px;
  color: #475569;
}

.scope-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.scope-tag {
  font-family: "DM Mono", monospace;
}

.mr-1 {
  margin-right: 4px;
}
</style>
