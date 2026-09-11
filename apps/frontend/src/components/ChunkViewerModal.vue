<script setup lang="ts">
import { ref } from "vue";
import { CopyDocument, Document, Search, Files } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

const props = defineProps<{
  visible: boolean;
  document: any;
  chunks?: any[];
  loading?: boolean;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
}>();

const filterText = ref("");

function handleClose() {
  emit("update:visible", false);
}

function copyChunkText(content: string) {
  navigator.clipboard.writeText(content);
  ElMessage.success("已复制 Chunk 文本内容到剪贴板");
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="文档 Chunk 切块明细"
    width="720px"
    class="chunk-modal"
    destroy-on-close
    @close="handleClose"
  >
    <template #header>
      <div class="modal-header">
        <span class="header-icon"><Files /></span>
        <div>
          <h3 class="modal-title">{{ document?.filename || "文档细节" }}</h3>
          <p class="modal-subtitle">
            切块 ID: <code class="mono-id">{{ document?.id }}</code>
          </p>
        </div>
      </div>
    </template>

    <div class="modal-body-content" v-loading="loading">
      <div class="meta-strip">
        <div class="meta-item">
          <span>切块总数</span>
          <strong>{{ document?.chunk_count ?? chunks?.length ?? 0 }} Chunks</strong>
        </div>
        <div class="meta-item">
          <span>文档状态</span>
          <span class="status" :class="document?.status">{{ document?.status }}</span>
        </div>
      </div>

      <div v-if="chunks && chunks.length > 0" class="chunks-section">
        <div class="search-bar">
          <el-input
            v-model="filterText"
            placeholder="搜索切块内容关键词..."
            clearable
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>

        <div class="chunks-list">
          <div
            v-for="(chunk, idx) in chunks.filter((c) => !filterText || c.content.includes(filterText))"
            :key="chunk.id || idx"
            class="chunk-card"
          >
            <div class="chunk-card-head">
              <span class="chunk-badge">Chunk #{{ idx + 1 }}</span>
              <el-button
                link
                type="primary"
                size="small"
                @click="copyChunkText(chunk.content)"
              >
                <el-icon class="mr-1"><CopyDocument /></el-icon> 复制内容
              </el-button>
            </div>
            <pre class="chunk-text">{{ chunk.content }}</pre>
          </div>
        </div>
      </div>
      <div v-else class="empty-chunks">
        <el-icon class="empty-icon"><Document /></el-icon>
        <p>暂无切块数据或文档正在解析处理中</p>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.modal-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--brand-soft, #eef2ff);
  color: var(--brand, #315efb);
  font-size: 20px;
}

.modal-title {
  margin: 0;
  font-size: 17px;
  font-weight: 800;
  color: var(--ink, #172235);
}

.modal-subtitle {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--muted, #687386);
}

.mono-id {
  font-family: "DM Mono", monospace;
  font-size: 11px;
  background: #f0f3f8;
  padding: 1px 5px;
  border-radius: 4px;
}

.modal-body-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.meta-strip {
  display: flex;
  gap: 24px;
  padding: 14px 18px;
  background: #f8fafc;
  border: 1px solid #e9eef5;
  border-radius: 10px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.meta-item span {
  font-size: 11px;
  color: #8391a7;
  font-weight: 600;
}

.meta-item strong {
  font-size: 14px;
  color: var(--ink, #172235);
}

.search-bar {
  margin-bottom: 12px;
}

.chunks-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 420px;
  overflow-y: auto;
  padding-right: 4px;
}

.chunk-card {
  padding: 14px;
  background: #ffffff;
  border: 1px solid var(--line, #e7ebf1);
  border-radius: 10px;
  transition: border-color 0.2s;
}

.chunk-card:hover {
  border-color: #cbd6ff;
}

.chunk-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.chunk-badge {
  font-family: "DM Mono", monospace;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  background: #eef2ff;
  color: var(--brand, #315efb);
  border-radius: 6px;
}

.chunk-text {
  margin: 0;
  font-family: "DM Mono", ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #435269;
  white-space: pre-wrap;
  background: #fafdff;
  padding: 10px;
  border-radius: 6px;
  border: 1px solid #edf2f8;
}

.empty-chunks {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: #94a3b8;
  text-align: center;
}

.empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.mr-1 {
  margin-right: 4px;
}
</style>
