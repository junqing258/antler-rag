<script setup lang="ts">
import { ref } from "vue";
import { UploadFilled, Document, Close, Check } from "@element-plus/icons-vue";

const emit = defineEmits<{
  (e: "upload", files: File[]): void;
}>();

const props = defineProps<{
  loading?: boolean;
  maxFiles?: number;
}>();

const isDragging = ref(false);
const selectedFiles = ref<File[]>([]);
const fileInput = ref<HTMLInputElement | null>(null);

function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files) {
    addFiles(Array.from(input.files));
  }
}

function handleDrop(event: DragEvent) {
  isDragging.value = false;
  if (event.dataTransfer?.files) {
    addFiles(Array.from(event.dataTransfer.files));
  }
}

function addFiles(files: File[]) {
  const validFiles = files.filter((f) => {
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    return [".txt", ".md", ".pdf", ".docx"].includes(ext);
  });
  
  selectedFiles.value = [...selectedFiles.value, ...validFiles];
  if (props.maxFiles && selectedFiles.value.length > props.maxFiles) {
    selectedFiles.value = selectedFiles.value.slice(0, props.maxFiles);
  }
}

function removeFile(index: number) {
  selectedFiles.value.splice(index, 1);
}

function triggerBrowse() {
  fileInput.value?.click();
}

function submitUpload() {
  if (selectedFiles.value.length > 0) {
    emit("upload", selectedFiles.value);
  }
}

function clearFiles() {
  selectedFiles.value = [];
  if (fileInput.value) fileInput.value.value = "";
}

defineExpose({ clearFiles });

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function getExt(filename: string): string {
  const parts = filename.split(".");
  return parts.length > 1 ? parts.pop()!.toUpperCase() : "DOC";
}
</script>

<template>
  <div class="dropzone-container">
    <div
      class="dropzone"
      :class="{ 'is-dragging': isDragging, 'has-files': selectedFiles.length > 0 }"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleDrop"
      @click="triggerBrowse"
    >
      <input
        ref="fileInput"
        type="file"
        multiple
        accept=".txt,.md,.pdf,.docx"
        class="hidden-input"
        @change="handleFileSelect"
      />
      
      <div class="dropzone-icon">
        <el-icon><UploadFilled /></el-icon>
      </div>

      <div class="dropzone-text">
        <h4>点击或拖拽文档到此处上传</h4>
        <p>支持 <code>TXT</code>, <code>Markdown (.md)</code>, <code>PDF</code>, <code>DOCX</code> 格式（单文件最大 25MiB）</p>
      </div>
    </div>

    <!-- Selected Files List -->
    <div v-if="selectedFiles.length > 0" class="file-preview-list">
      <div class="list-header">
        <span>已选择文件 ({{ selectedFiles.length }})</span>
        <el-button link type="primary" size="small" @click.stop="clearFiles">清空</el-button>
      </div>

      <div class="files-grid">
        <div
          v-for="(file, idx) in selectedFiles"
          :key="file.name + idx"
          class="file-item-card"
        >
          <span class="file-ext-badge" :data-ext="getExt(file.name)">
            {{ getExt(file.name) }}
          </span>

          <div class="file-info">
            <span class="file-name" :title="file.name">{{ file.name }}</span>
            <span class="file-size">{{ formatSize(file.size) }}</span>
          </div>

          <button class="remove-btn" title="移除" @click.stop="removeFile(idx)">
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>

      <div class="action-row">
        <el-button
          type="primary"
          size="default"
          :loading="loading"
          class="upload-submit-btn"
          @click="submitUpload"
        >
          <el-icon class="mr-1"><Check /></el-icon>
          开始解析并建立向量索引
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dropzone-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
  background: #fafcff;
  border: 2px dashed #d1dbed;
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  text-align: center;
}

.dropzone:hover,
.dropzone.is-dragging {
  background: #f0f5ff;
  border-color: var(--brand, #315efb);
  transform: translateY(-1px);
}

.dropzone.is-dragging {
  box-shadow: 0 0 0 4px rgba(49, 94, 251, 0.12);
}

.hidden-input {
  display: none;
}

.dropzone-icon {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: #eef3ff;
  color: var(--brand, #315efb);
  font-size: 26px;
  margin-bottom: 12px;
  transition: transform 0.2s;
}

.dropzone:hover .dropzone-icon {
  transform: scale(1.1);
}

.dropzone-text h4 {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 700;
  color: var(--ink, #172235);
}

.dropzone-text p {
  margin: 0;
  font-size: 12px;
  color: var(--muted, #687386);
}

.dropzone-text code {
  padding: 2px 5px;
  background: #eef2f7;
  border-radius: 4px;
  font-family: "DM Mono", monospace;
  font-size: 11px;
  color: #3b485e;
}

.file-preview-list {
  background: #ffffff;
  border: 1px solid var(--line, #e7ebf1);
  border-radius: 12px;
  padding: 16px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink, #172235);
}

.files-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.file-item-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e9eef5;
  border-radius: 10px;
}

.file-ext-badge {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 8px;
  font-family: "DM Mono", monospace;
  font-size: 10px;
  font-weight: 800;
  color: #ffffff;
  background: #64748b;
  flex-shrink: 0;
}

.file-ext-badge[data-ext="PDF"] { background: #ef4444; }
.file-ext-badge[data-ext="MD"] { background: #8b5cf6; }
.file-ext-badge[data-ext="TXT"] { background: #3b82f6; }
.file-ext-badge[data-ext="DOCX"] { background: #0284c7; }

.file-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.file-name {
  font-size: 12px;
  font-weight: 700;
  color: var(--ink, #172235);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-size {
  font-size: 11px;
  color: #8fa0b8;
}

.remove-btn {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: #a0aec0;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}

.remove-btn:hover {
  background: #fee2e2;
  color: #ef4444;
}

.action-row {
  display: flex;
  justify-content: flex-end;
}

.upload-submit-btn {
  height: 40px;
  padding: 0 20px;
  font-weight: 700;
}

.mr-1 {
  margin-right: 4px;
}
</style>
