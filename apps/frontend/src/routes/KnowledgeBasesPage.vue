<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import {
  DocumentAdd,
  Files,
  FolderAdd,
  Search,
  Delete,
  View,
} from "@element-plus/icons-vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api } from "../lib/request";
import FileUploadZone from "../components/FileUploadZone.vue";
import ChunkViewerModal from "../components/ChunkViewerModal.vue";

const items = ref<any[]>([]);
const name = ref("");
const error = ref("");
const selectedKb = ref<any>(null);
const docs = ref<any[]>([]);
const docFilter = ref("");

const uploadLoading = ref(false);
const fileUploadZoneRef = ref();

// Chunk Viewer Modal State
const chunkModalVisible = ref(false);
const activeDoc = ref<any>(null);
const docChunks = ref<any[]>([]);
const chunkLoading = ref(false);

async function load() {
  try {
    items.value = (await api<any>("/api/v1/knowledge-bases")).items || [];
    if (!selectedKb.value && items.value.length > 0) {
      choose(items.value[0]);
    }
  } catch (e: any) {
    error.value = e.message;
  }
}

async function create() {
  if (!name.value.trim()) return;
  try {
    const newKb = await api<any>("/api/v1/knowledge-bases", {
      method: "POST",
      body: JSON.stringify({ name: name.value }),
    });
    name.value = "";
    ElMessage.success("知识库新建成功");
    await load();
    choose(newKb);
  } catch (e: any) {
    error.value = e.message;
  }
}

async function choose(kb: any) {
  selectedKb.value = kb;
  await fetchDocuments();
}

async function fetchDocuments() {
  if (!selectedKb.value) return;
  try {
    docs.value = (
      await api<any>(`/api/v1/knowledge-bases/${selectedKb.value.id}/documents`)
    ).items || [];
  } catch (e: any) {
    error.value = e.message;
  }
}

async function handleUpload(files: File[]) {
  if (!selectedKb.value || !files.length) return;
  uploadLoading.value = true;
  try {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    await api(`/api/v1/knowledge-bases/${selectedKb.value.id}/documents`, {
      method: "POST",
      body: form,
    });
    ElMessage.success(`成功上传并解析 ${files.length} 个文件`);
    fileUploadZoneRef.value?.clearFiles();
    await fetchDocuments();
  } catch (e: any) {
    ElMessage.error(e.message || "上传失败");
  } finally {
    uploadLoading.value = false;
  }
}

async function confirmRemove(doc: any) {
  try {
    await ElMessageBox.confirm(
      `确定要删除文档 "${doc.filename}" 及其关联的切块向量索引吗？`,
      "删除确认",
      {
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
        type: "warning",
      },
    );
    await api(
      `/api/v1/knowledge-bases/${selectedKb.value.id}/documents/${doc.id}`,
      { method: "DELETE" },
    );
    ElMessage.success("文档已成功删除");
    await fetchDocuments();
  } catch {
    // User cancelled
  }
}

async function inspectChunks(doc: any) {
  activeDoc.value = doc;
  chunkModalVisible.value = true;
  chunkLoading.value = true;
  docChunks.value = [];
  try {
    // Attempt fetching document chunks or details if backend supports
    const res = await api<any>(
      `/api/v1/knowledge-bases/${selectedKb.value.id}/documents/${doc.id}`,
    );
    docChunks.value = res.chunks || res.items || [];
  } catch {
    // Fallback if detail endpoint not returning array
    docChunks.value = [];
  } finally {
    chunkLoading.value = false;
  }
}

const filteredDocs = computed(() => {
  if (!docFilter.value) return docs.value;
  const q = docFilter.value.toLowerCase();
  return docs.value.filter((d) => d.filename.toLowerCase().includes(q));
});

onMounted(load);
</script>

<template>
  <section class="page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">KNOWLEDGE HUB</p>
        <h2>知识库管理</h2>
        <p class="page-description">
          统一组织与存储团队知识资产，为智能 Agent 问答与搜索提供强劲上下文基座。
        </p>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon class="notice" />

    <!-- Knowledge Base List Panel -->
    <article class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">全部知识库</h3>
          <p class="panel-subtitle">选中一行即可管理其底层对应文档</p>
        </div>

        <el-form class="create-form" @submit.prevent="create">
          <el-input v-model="name" placeholder="输入新知识库名称..." />
          <el-button type="primary" native-type="submit" :disabled="!name.trim()">
            <el-icon class="mr-1"><FolderAdd /></el-icon>新建知识库
          </el-button>
        </el-form>
      </div>

      <div class="panel-body flush table-wrap">
        <el-table
          :data="items"
          class="clickable-table"
          highlight-current-row
          @row-click="choose"
        >
          <el-table-column prop="name" label="知识库名称" min-width="260">
            <template #default="s">
              <div
                class="table-name-cell"
                :class="{ active: selectedKb?.id === s.row.id }"
              >
                <span class="icon-box"><Files /></span>
                <span>{{ s.row.name }}</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column prop="status" label="状态" width="140">
            <template #default="s">
              <span class="status" :class="s.row.status">{{ s.row.status }}</span>
            </template>
          </el-table-column>

          <el-table-column label="默认库" width="130">
            <template #default="s">
              <el-tag
                :type="s.row.is_default ? 'primary' : 'info'"
                effect="light"
                size="small"
              >
                {{ s.row.is_default ? "默认知识库" : "普通" }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </article>

    <!-- Documents Area Panel -->
    <article v-if="selectedKb" class="panel document-panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">「{{ selectedKb.name }}」文档集</h3>
          <p class="panel-subtitle">上传文件后，系统将自动清洗分块并注入 Chroma 向量数据库</p>
        </div>

        <div class="header-actions">
          <span class="doc-count-tag">{{ docs.length }} 个文档</span>
        </div>
      </div>

      <div class="panel-body">
        <!-- File Upload Dropzone -->
        <FileUploadZone
          ref="fileUploadZoneRef"
          :loading="uploadLoading"
          @upload="handleUpload"
        />

        <div class="docs-list-header">
          <h4 class="sub-title">包含文档列表</h4>
          <div class="filter-input">
            <el-input
              v-model="docFilter"
              placeholder="搜索文档名称..."
              clearable
              size="default"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </div>
        </div>

        <!-- Document Table -->
        <div class="table-wrap">
          <el-table :data="filteredDocs" empty-text="当前知识库暂无文档">
            <el-table-column prop="filename" label="文件名" min-width="280">
              <template #default="s">
                <span class="doc-filename-cell">
                  <el-icon class="doc-icon"><DocumentAdd /></el-icon>
                  {{ s.row.filename }}
                </span>
              </template>
            </el-table-column>

            <el-table-column prop="status" label="状态" width="140">
              <template #default="s">
                <span class="status" :class="s.row.status">{{ s.row.status }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="chunk_count" label="CHUNKS 切块数" width="150">
              <template #default="s">
                <span class="chunk-count-badge">{{ s.row.chunk_count }} Chunks</span>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="160" align="right">
              <template #default="s">
                <el-button
                  link
                  type="primary"
                  size="small"
                  @click="inspectChunks(s.row)"
                >
                  <el-icon class="mr-1"><View /></el-icon>查看切块
                </el-button>
                <el-button
                  link
                  type="danger"
                  size="small"
                  @click="confirmRemove(s.row)"
                >
                  <el-icon class="mr-1"><Delete /></el-icon>删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </article>

    <!-- Chunk Detail Viewer Modal -->
    <ChunkViewerModal
      v-model:visible="chunkModalVisible"
      :document="activeDoc"
      :chunks="docChunks"
      :loading="chunkLoading"
    />
  </section>
</template>

<style scoped>
.create-form {
  display: flex;
  gap: 10px;
}

.create-form :deep(.el-input) {
  width: 240px;
}

.table-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  color: var(--ink, #111827);
}

.table-name-cell.active {
  color: var(--brand, #3b82f6);
}

.icon-box {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--brand-soft, #eff6ff);
  color: var(--brand, #3b82f6);
  font-size: 16px;
}

.clickable-table :deep(.el-table__row) {
  cursor: pointer;
}

.document-panel {
  margin-top: 24px;
}

.doc-count-tag {
  padding: 6px 12px;
  background: #f1f5f9;
  color: #475569;
  border-radius: 99px;
  font-size: 12px;
  font-weight: 700;
}

.docs-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 24px 0 14px;
}

.sub-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: var(--ink, #111827);
}

.filter-input {
  width: 240px;
}

.doc-filename-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  color: #334155;
}

.doc-icon {
  color: var(--brand, #3b82f6);
  font-size: 16px;
}

.chunk-count-badge {
  font-family: "DM Mono", monospace;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  background: #f1f5f9;
  color: #475569;
  border-radius: 6px;
}

.mr-1 {
  margin-right: 4px;
}

@media (max-width: 720px) {
  .panel-header {
    align-items: flex-start;
    flex-direction: column;
  }
  .create-form {
    width: 100%;
  }
  .create-form :deep(.el-input) {
    width: auto;
    flex: 1;
  }
  .docs-list-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  .filter-input {
    width: 100%;
  }
}
</style>
