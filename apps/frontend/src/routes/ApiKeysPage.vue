<script setup lang="ts">
import { ref, onMounted } from "vue";
import {
  Key,
  Plus,
  WarningFilled,
  CopyDocument,
  Delete,
  Operation,
  Timer,
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
          为您的应用、Agent 或服务端程序创建独立的 API
          访问密钥，精准控制可调用权限范畴。
        </p>
      </div>

      <el-button
        type="primary"
        plain
        size="default"
        @click="showCodeModal = true"
      >
        <el-icon class="mr-1"><Operation /></el-icon>查看 SDK / API 示例
      </el-button>
    </div>

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      class="notice"
    />

    <!-- Newly Created Secret Alert Banner -->
    <div v-if="secret" class="secret-box">
      <div class="secret-icon"><WarningFilled /></div>
      <div class="secret-content">
        <strong>请立即复制并妥善保管您的 API Key</strong>
        <p>
          出于安全原因，此明文密钥只会在此展示一次，刷新或离开页面后将无法再次查看。
        </p>
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
          <p class="panel-subtitle">
            默认有效期为 90 天，勾选该密钥允许执行的操作权限 (Scope)
          </p>
        </div>
      </div>

      <div class="panel-body">
        <el-form class="key-form" @submit.prevent="create">
          <div class="credential-details items-center">
            <div class="form-group name-group">
              <label class="form-label" for="api-key-name"
                >凭证名称 / 应用标识</label
              >
              <el-input
                id="api-key-name"
                v-model="name"
                placeholder="例如：Customer Support Agent"
              />
              <p class="field-hint">
                使用便于识别的名称，方便后续轮换和吊销凭证。
              </p>
            </div>

            <div class="expiry-note">
              <el-icon><Timer /></el-icon>
              <div>
                <strong>90 天有效期</strong>
                <span>创建后自动生效，到期前请及时轮换</span>
              </div>
            </div>
          </div>

          <div class="scope-group">
            <div class="scope-heading">
              <div>
                <label class="form-label">授予访问权限 (Scopes)</label>
                <p>仅勾选此应用实际需要的权限，降低凭证泄露风险。</p>
              </div>
              <span class="scope-count">已选择 {{ scopes.length }} 项</span>
            </div>
            <el-checkbox-group v-model="scopes" class="scope-checkboxes">
              <el-checkbox label="retrieve">
                <el-tag type="primary" size="small" effect="plain"
                  >retrieve</el-tag
                >
                <span>检索向量</span>
              </el-checkbox>
              <el-checkbox label="chat">
                <el-tag type="success" size="small" effect="plain">chat</el-tag>
                <span>问答对话</span>
              </el-checkbox>
              <el-checkbox label="documents:read">
                <el-tag type="info" size="small" effect="plain"
                  >documents:read</el-tag
                >
                <span>读取文档</span>
              </el-checkbox>
              <el-checkbox label="documents:write">
                <el-tag type="warning" size="small" effect="plain"
                  >documents:write</el-tag
                >
                <span>写入文档</span>
              </el-checkbox>
              <el-checkbox label="documents:delete">
                <el-tag type="danger" size="small" effect="plain"
                  >documents:delete</el-tag
                >
                <span>删除文档</span>
              </el-checkbox>
            </el-checkbox-group>
          </div>

          <div class="form-actions">
            <p class="action-hint">生成后，完整 API Key 仅展示一次。</p>
            <el-button
              type="primary"
              native-type="submit"
              :loading="loading"
              :disabled="!name.trim() || !scopes.length"
              class="submit-key-btn"
            >
              <el-icon class="mr-1"><Plus /></el-icon>生成 API Key
            </el-button>
          </div>
        </el-form>
      </div>
    </article>

    <!-- Keys List Panel -->
    <article class="panel key-list">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">已创建的 Keys ({{ items.length }})</h3>
          <p class="panel-subtitle">
            建议定期轮换凭证，及时吊销长期未使用的访问密钥
          </p>
        </div>
      </div>

      <div class="panel-body flush table-wrap">
        <el-table :data="items" empty-text="当前工作区尚未创建 API Key">
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
  display: grid;
  gap: 24px;
}

.form-group {
  display: flex;
  flex-direction: column;
}

.credential-details {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 28px;
  padding-bottom: 2px;
}

.name-group {
  max-width: 520px;
}

.field-hint,
.scope-heading p,
.action-hint {
  margin: 7px 0 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}

.expiry-note {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 220px;
  padding: 10px 12px;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
}

.expiry-note .el-icon {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: #0284c7;
  background: #e0f2fe;
  border-radius: 7px;
  font-size: 16px;
}

.expiry-note strong,
.expiry-note span {
  display: block;
}

.expiry-note strong {
  color: #334155;
  font-size: 12px;
  line-height: 1.4;
}

.expiry-note span {
  margin-top: 1px;
  color: #94a3b8;
  font-size: 11px;
}

.scope-checkboxes {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

.scope-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.scope-heading .form-label {
  margin-bottom: 0;
}

.scope-heading p {
  margin-top: 4px;
}

.scope-count {
  flex-shrink: 0;
  padding: 4px 8px;
  color: #64748b;
  background: #f1f5f9;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
}

.scope-checkboxes :deep(.el-checkbox) {
  display: flex;
  align-items: center;
  min-width: 0;
  height: 46px;
  margin-right: 0;
  padding: 0 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease;
}

.scope-checkboxes :deep(.el-checkbox.is-checked) {
  background: #f0f9ff;
  border-color: #7dd3fc;
  box-shadow: 0 1px 2px rgba(2, 132, 199, 0.08);
}

.scope-checkboxes :deep(.el-checkbox__label) {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  padding-left: 8px;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.scope-checkboxes :deep(.el-tag) {
  flex-shrink: 0;
  margin-right: 6px;
}

.form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 4px;
  border-top: 1px solid #f1f5f9;
}

.action-hint {
  margin: 0;
}

.submit-key-btn {
  width: fit-content;
  height: 42px;
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

@media (max-width: 1080px) {
  .scope-checkboxes {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .credential-details {
    grid-template-columns: 1fr;
    gap: 16px;
  }

  .name-group,
  .expiry-note {
    max-width: none;
    width: 100%;
  }

  .scope-heading,
  .form-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .scope-count {
    margin-top: -2px;
  }

  .scope-checkboxes {
    grid-template-columns: 1fr;
  }

  .submit-key-btn {
    width: 100%;
  }
}
</style>
