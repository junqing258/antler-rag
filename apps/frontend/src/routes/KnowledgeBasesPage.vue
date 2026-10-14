<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  DocumentAdd,
  Files,
  Search,
  Delete,
  View,
  Plus,
  Collection,
  Coin,
  Box,
  Grid,
  Menu,
  Operation,
} from "@element-plus/icons-vue";
import { ElMessageBox, ElMessage } from "element-plus";
import { api } from "../lib/request";
import FileUploadZone from "../components/FileUploadZone.vue";
import ChunkViewerModal from "../components/ChunkViewerModal.vue";

const items = ref<any[]>([]);
const name = ref("");
const description = ref("");
const chunkStrategy = ref("recursive");
const chunkSize = ref(900);
const chunkOverlap = ref(150);
const error = ref("");
const selectedKb = ref<any>(null);
const docs = ref<any[]>([]);
const docFilter = ref("");
const uploadLoading = ref(false);
const fileUploadZoneRef = ref();
const chunkModalVisible = ref(false);
const activeDoc = ref<any>(null);
const docChunks = ref<any[]>([]);
const chunkLoading = ref(false);
const chunkPage = ref(1);
const chunkCount = ref(0);
const chunkPageSize = 20;
let chunkRequest = 0;
const showCreate = ref(false);
const cardView = ref(true);
const filter = ref("");
const router = useRouter();
const documentsRef = ref<HTMLElement | null>(null);
async function load() {
  try {
    items.value = (await api<any>("/api/v1/knowledge-bases")).items || [];
    if (!selectedKb.value && items.value.length) choose(items.value[0]);
  } catch (e: any) {
    error.value = e.message;
  }
}
async function create() {
  if (!name.value.trim()) return;
  if (chunkOverlap.value >= chunkSize.value) {
    ElMessage.error("重叠必须小于块大小");
    return;
  }
  try {
    const newKb = await api<any>("/api/v1/knowledge-bases", {
      method: "POST",
      body: JSON.stringify({
        name: name.value,
        description: description.value,
        chunk_strategy: chunkStrategy.value,
        chunk_size: chunkSize.value,
        chunk_overlap: chunkOverlap.value,
      }),
    });
    name.value = "";
    description.value = "";
    chunkStrategy.value = "recursive";
    chunkSize.value = 900;
    chunkOverlap.value = 150;
    showCreate.value = false;
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
function testRetrieval(kb: any) {
  router.push({ path: "/retrieve", query: { kb: kb.id } });
}
async function manageDocuments(kb: any) {
  await choose(kb);
  documentsRef.value?.scrollIntoView({ behavior: "smooth", block: "start" });
}
async function fetchDocuments() {
  if (!selectedKb.value) return;
  try {
    docs.value =
      (
        await api<any>(
          `/api/v1/knowledge-bases/${selectedKb.value.id}/documents`,
        )
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
    files.forEach((file) => form.append("files", file));
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
  } catch (e: any) {
    if (e instanceof Error) ElMessage.error(e.message || "删除失败");
  }
}
async function inspectChunks(doc: any) {
  activeDoc.value = doc;
  chunkModalVisible.value = true;
  chunkCount.value = 0;
  await fetchChunks(1);
}
async function fetchChunks(page: number) {
  const requestId = ++chunkRequest;
  chunkPage.value = page;
  chunkLoading.value = true;
  docChunks.value = [];
  try {
    const res = await api<any>(
      `/api/v1/knowledge-bases/${activeDoc.value.knowledge_base_id}/documents/${activeDoc.value.id}/chunks?offset=${(page - 1) * chunkPageSize}&limit=${chunkPageSize}`,
    );
    if (requestId !== chunkRequest) return;
    docChunks.value = res.items || [];
    chunkCount.value = res.total || 0;
  } catch (e: any) {
    if (requestId === chunkRequest)
      ElMessage.error(e.message || "切片加载失败");
  } finally {
    if (requestId === chunkRequest) chunkLoading.value = false;
  }
}
function strategyLabel(kb: any) {
  return kb.chunk_strategy === "structure" ? "结构分块" : "递归分块";
}
const filteredItems = computed(() =>
  !filter.value
    ? items.value
    : items.value.filter((item) =>
        item.name.toLowerCase().includes(filter.value.toLowerCase()),
      ),
);
const filteredDocs = computed(() =>
  !docFilter.value
    ? docs.value
    : docs.value.filter((doc) =>
        doc.filename.toLowerCase().includes(docFilter.value.toLowerCase()),
      ),
);
const chunkTotal = computed(() =>
  docs.value.reduce((total, doc) => total + (Number(doc.chunk_count) || 0), 0),
);
onMounted(load);
</script>

<template>
  <section class="kb-page">
    <div class="crumb">
      <span>控制台</span><b>/</b><span>工作区</span><b>/</b
      ><strong>知识库管理</strong>
    </div>
    <header class="kb-heading">
      <div>
        <div class="title-line">
          <h1>知识库管理 (Knowledge Bases)</h1>
          <span>{{ items.length }} Total</span>
        </div>
        <p>
          管理全局知识库、切片分块策略与流水线全生命周期，并提供标准检索端点。
        </p>
      </div>
      <div class="heading-actions">
        <button>
          <el-icon><Operation /></el-icon>批量重构索引</button
        ><button>＜＞ API 文档 ↗</button
        ><el-button type="primary" @click="showCreate = !showCreate"
          ><el-icon><Plus /></el-icon> 新建知识库 (New KB)</el-button
        >
      </div>
    </header>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      class="notice"
    />
    <form
      v-if="showCreate"
      class="create-kb"
      aria-labelledby="create-kb-title"
      @submit.prevent="create"
    >
      <header class="create-kb-heading">
        <span class="create-kb-icon"
          ><el-icon><Collection /></el-icon
        ></span>
        <div>
          <h2 id="create-kb-title">新建知识库</h2>
          <p>填写基本信息，并设置文档的切片方式。</p>
        </div>
      </header>
      <div class="create-kb-fields">
        <div class="create-kb-field">
          <label for="kb-name"
            >知识库名称 <span class="required">*</span></label
          >
          <el-input
            id="kb-name"
            v-model="name"
            autofocus
            required
            placeholder="例如：产品文档、内部知识库"
          />
        </div>
        <div class="create-kb-field">
          <label for="kb-description">知识库描述 <span>选填</span></label>
          <el-input
            id="kb-description"
            v-model="description"
            placeholder="简要描述知识库的内容或用途"
          />
        </div>
      </div>
      <fieldset class="create-kb-chunking">
        <legend>切片配置 <span>创建后固定</span></legend>
        <div class="create-kb-chunk-fields">
          <div class="create-kb-field">
            <label for="kb-chunk-strategy">切片策略</label>
            <el-select
              id="kb-chunk-strategy"
              v-model="chunkStrategy"
              aria-label="切片策略"
              aria-describedby="kb-chunk-help"
            >
              <el-option value="recursive" label="递归分块" />
              <el-option value="structure" label="结构分块" />
            </el-select>
          </div>
          <div class="create-kb-field">
            <label for="kb-chunk-size">块大小 <span>字符</span></label>
            <el-input-number
              id="kb-chunk-size"
              v-model="chunkSize"
              :min="100"
              :max="4000"
            />
          </div>
          <div class="create-kb-field">
            <label for="kb-chunk-overlap">重叠大小 <span>字符</span></label>
            <el-input-number
              id="kb-chunk-overlap"
              v-model="chunkOverlap"
              :min="0"
              :max="Math.min(1000, chunkSize - 1)"
            />
          </div>
        </div>
        <p id="kb-chunk-help" class="create-kb-help">
          <template v-if="chunkStrategy === 'structure'">
            按标题、章节和段落分块；TXT 按段落，PDF 按页或段落。
          </template>
          <template v-else>
            按设定的块大小递归拆分文本，相邻切片保留重叠内容以衔接上下文。
          </template>
        </p>
      </fieldset>
      <footer class="create-kb-actions">
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" native-type="submit">
          <el-icon><Plus /></el-icon>创建知识库
        </el-button>
      </footer>
    </form>
    <div class="metrics">
      <article>
        <span>活跃知识库</span><el-icon><Collection /></el-icon
        ><strong>{{ items.length }}</strong
        ><b>↑ 100% 可用</b>
        <footer>已同步 {{ items.length }} <em>正在构建 0</em></footer>
      </article>
      <article>
        <span>收录文档总数</span><el-icon><Files /></el-icon
        ><strong>{{ docs.length }}</strong
        ><b>篇格式化文档</b>
        <footer>PDF · MD · DOCX</footer>
      </article>
      <article>
        <span>向量分块 (Chunks)</span><el-icon><Coin /></el-icon
        ><strong>{{ chunkTotal.toLocaleString() }}</strong
        ><b>● 全部嵌入</b>
        <footer>
          所选库块大小 <em>{{ selectedKb?.chunk_size ?? "—" }} 字符</em>
        </footer>
      </article>
      <article>
        <span>向量存储 (HNSW)</span><el-icon><Box /></el-icon
        ><strong>Ready</strong><b>Chroma 本地索引</b>
        <footer>写入吞吐 <em>正常</em></footer>
      </article>
    </div>
    <div class="kb-filter">
      <el-icon><Search /></el-icon
      ><el-input
        v-model="filter"
        placeholder="搜索知识库名称、ID 或描述..."
        clearable
      /><el-select placeholder="全部嵌入模型"
        ><el-option label="全部嵌入模型" value="all" /></el-select
      ><el-select placeholder="全部状态"
        ><el-option label="全部状态" value="all"
      /></el-select>
      <div>
        <button
          :class="{ active: cardView }"
          type="button"
          @click="cardView = true"
        >
          <el-icon><Grid /></el-icon></button
        ><button
          :class="{ active: !cardView }"
          type="button"
          @click="cardView = false"
        >
          <el-icon><Menu /></el-icon>
        </button>
      </div>
    </div>
    <div class="kb-cards" :class="{ list: !cardView }">
      <article
        v-for="item in filteredItems"
        :key="item.id"
        class="kb-card"
        :class="{ selected: selectedKb?.id === item.id }"
        @click="choose(item)"
      >
        <header>
          <span class="kb-icon"
            ><el-icon><Files /></el-icon
          ></span>
          <div>
            <h2>{{ item.name }}</h2>
            <code>{{ item.id }}</code>
          </div>
          <span class="status-chip" :class="item.status"
            >●
            {{ item.status === "processing" ? "正在构建" : "已同步索引" }}</span
          >
        </header>
        <p>
          团队业务知识资产与上下文资料集合。上传文档后，系统会自动完成清洗、切块和向量化索引。
        </p>
        <section>
          <div>
            <small>收录规模</small
            ><b
              >{{ selectedKb?.id === item.id ? docs.length : "—" }} 篇文档 ·
              {{ selectedKb?.id === item.id ? chunkTotal : "—" }} chunks</b
            >
          </div>
          <div><small>嵌入模型</small><b>text-embedding-3-sm</b></div>
          <div>
            <small>切片策略</small
            ><b
              >{{ strategyLabel(item) }} · {{ item.chunk_size }} 字符 · 重叠
              {{ item.chunk_overlap }}</b
            >
          </div>
          <div><small>检索模式</small><b>Dense Vector Cosine</b></div>
        </section>
        <footer>
          <span>更新于：刚刚</span
          ><button type="button" @click.stop="testRetrieval(item)">
            <el-icon><Search /></el-icon>测试检索</button
          ><button type="button" @click.stop="manageDocuments(item)">
            文档管理</button
          ><!-- <i>⋮</i> -->
        </footer>
      </article>
      <div v-if="!filteredItems.length" class="no-kbs">
        尚未找到知识库。点击右上方按钮创建第一个知识库。
      </div>
    </div>
    <article v-if="selectedKb" ref="documentsRef" class="documents">
      <header>
        <div>
          <h2>「{{ selectedKb.name }}」文档集</h2>
          <p>
            {{ strategyLabel(selectedKb) }} · 块大小
            {{ selectedKb.chunk_size }} 字符 · 重叠
            {{ selectedKb.chunk_overlap }} 字符
          </p>
        </div>
        <span>{{ docs.length }} 个文档</span>
      </header>
      <div class="documents-body">
        <FileUploadZone
          ref="fileUploadZoneRef"
          :loading="uploadLoading"
          @upload="handleUpload"
        />
        <div class="docs-heading">
          <h3>包含文档列表</h3>
          <el-input v-model="docFilter" placeholder="搜索文档名称..." clearable
            ><template #prefix
              ><el-icon><Search /></el-icon></template
          ></el-input>
        </div>
        <el-table :data="filteredDocs" empty-text="当前知识库暂无文档"
          ><el-table-column prop="filename" label="文件名" min-width="260"
            ><template #default="s"
              ><span class="filename"
                ><el-icon><DocumentAdd /></el-icon>{{ s.row.filename }}</span
              ></template
            ></el-table-column
          ><el-table-column
            prop="status"
            label="状态"
            width="130"
          /><el-table-column
            prop="chunk_count"
            label="CHUNKS"
            width="120"
          /><el-table-column label="操作" width="160"
            ><template #default="s"
              ><el-button link type="primary" @click="inspectChunks(s.row)"
                ><el-icon><View /></el-icon>查看切块</el-button
              ><el-button link type="danger" @click="confirmRemove(s.row)"
                ><el-icon><Delete /></el-icon>删除</el-button
              ></template
            ></el-table-column
          ></el-table
        >
      </div>
    </article>
    <ChunkViewerModal
      v-model:visible="chunkModalVisible"
      :document="activeDoc"
      :chunks="docChunks"
      :loading="chunkLoading"
      :total="chunkCount"
      :page="chunkPage"
      :page-size="chunkPageSize"
      @page-change="fetchChunks"
    />
  </section>
</template>

<style scoped>
.kb-page {
  max-width: 1200px;
  margin: 0 auto;
}
.crumb {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  color: #64748b;
  font:
    12px "JetBrains Mono",
    monospace;
}
.crumb b {
  color: #cbd5e1;
}
.crumb strong {
  color: #0284c7;
}
.kb-heading {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 28px;
}
.title-line {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-line h1 {
  margin: 0;
  font-size: 26px;
  letter-spacing: -0.03em;
}
.title-line span {
  padding: 4px 10px;
  color: #0369a1;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 99px;
  font:
    11px "JetBrains Mono",
    monospace;
}
.kb-heading p {
  max-width: 670px;
  margin: 8px 0 0;
  color: #475569;
  font-size: 14px;
  line-height: 1.7;
}
.heading-actions {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.heading-actions button {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 38px;
  padding: 0 12px;
  color: #334155;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 7px;
  font-size: 12px;
  cursor: pointer;
}
.heading-actions .el-button {
  height: 40px;
}
.create-kb {
  margin: 0 0 28px;
  padding: 24px;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.03);
}
.create-kb-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}
.create-kb-icon {
  display: grid;
  flex: 0 0 40px;
  height: 40px;
  place-items: center;
  color: #0284c7;
  background: #f0f9ff;
  border-radius: 10px;
  font-size: 20px;
}
.create-kb-heading h2 {
  margin: 0;
  color: #0f172a;
  font-size: 16px;
  font-weight: 600;
}
.create-kb-heading p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}
.create-kb-fields,
.create-kb-chunk-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}
.create-kb-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
}
.create-kb-field label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #334155;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
}
.create-kb-field label span {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 400;
}
.create-kb-field label .required {
  color: #ef4444;
}
.create-kb-field :deep(.el-select),
.create-kb-field :deep(.el-input-number) {
  width: 100%;
}
.create-kb-field :deep(.el-input__wrapper),
.create-kb-field :deep(.el-select__wrapper) {
  min-height: 40px;
}
.create-kb-chunking {
  min-width: 0;
  margin: 24px 0 0;
  padding: 16px 20px 18px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}
.create-kb-chunking legend {
  padding: 0 6px;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}
.create-kb-chunking legend span {
  margin-left: 8px;
  color: #64748b;
  font-size: 11px;
  font-weight: 400;
}
.create-kb-chunk-fields {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.create-kb-help {
  margin: 14px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.7;
}
.create-kb-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #f1f5f9;
}
.create-kb-actions .el-button {
  height: 38px;
  margin-left: 0;
  padding: 0 18px;
}
.create-kb-actions .el-icon {
  margin-right: 5px;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 18px;
  margin-bottom: 28px;
}
.metrics article {
  position: relative;
  min-height: 146px;
  padding: 20px;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 14px;
}
.metrics article > span {
  color: #64748b;
  font-size: 12px;
}
.metrics article > .el-icon {
  position: absolute;
  top: 19px;
  right: 19px;
  padding: 8px;
  color: #0284c7;
  background: #f0f9ff;
  border-radius: 8px;
  font-size: 18px;
}
.metrics strong {
  display: inline-block;
  margin: 20px 8px 12px 0;
  font:
    600 27px "JetBrains Mono",
    monospace;
}
.metrics b {
  color: #059669;
  font-size: 11px;
}
.metrics footer {
  display: flex;
  justify-content: space-between;
  padding-top: 10px;
  color: #64748b;
  border-top: 1px solid #f1f5f9;
  font:
    11px "JetBrains Mono",
    monospace;
}
.metrics em {
  color: #0284c7;
  font-style: normal;
}
.kb-filter {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  margin-bottom: 28px;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 14px;
}
.kb-filter > .el-icon {
  margin-left: 3px;
  color: #94a3b8;
}
.kb-filter :deep(.el-input) {
  flex: 1;
}
.kb-filter :deep(.el-select) {
  width: 170px;
}
.kb-filter > div {
  display: flex;
  padding: 3px;
  background: #f1f5f9;
  border-radius: 7px;
}
.kb-filter button {
  display: grid;
  width: 30px;
  height: 28px;
  place-items: center;
  color: #64748b;
  background: transparent;
  border: 0;
  border-radius: 5px;
  cursor: pointer;
}
.kb-filter button.active {
  color: #0284c7;
  background: #fff;
  box-shadow: 0 1px 3px #cbd5e1;
}
.kb-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
}
.kb-cards.list {
  grid-template-columns: 1fr;
}
.kb-card {
  overflow: hidden;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 14px;
  cursor: pointer;
  transition: 0.2s;
}
.kb-card:hover,
.kb-card.selected {
  border-color: #7dd3fc;
  box-shadow: 0 8px 22px rgba(2, 132, 199, 0.09);
}
.kb-card > header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 24px 24px 10px;
}
.kb-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  place-items: center;
  color: #0284c7;
  background: #f0f9ff;
  border: 1px solid #e0f2fe;
  border-radius: 8px;
  font-size: 20px;
}
.kb-card h2 {
  margin: 1px 0 4px;
  font-size: 17px;
}
.kb-card code {
  color: #94a3b8;
  font:
    12px "JetBrains Mono",
    monospace;
}
.status-chip {
  margin-left: auto;
  padding: 6px 9px;
  color: #059669;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 99px;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 600;
}
.status-chip.processing {
  color: #0369a1;
  background: #f0f9ff;
}
.kb-card > p {
  min-height: 46px;
  margin: 4px 24px 18px;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}
.kb-card section {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin: 0 24px 16px;
  padding: 15px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}
.kb-card section div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.kb-card small {
  color: #94a3b8;
  font-size: 11px;
}
.kb-card section b {
  overflow: hidden;
  color: #1e293b;
  font:
    11px "JetBrains Mono",
    monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kb-card > footer {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 14px 24px;
  border-top: 1px solid #e2e8f0;
  color: #94a3b8;
  font:
    11px "JetBrains Mono",
    monospace;
}
.kb-card footer button {
  padding: 7px 10px;
  color: #334155;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 7px;
  cursor: pointer;
  font-size: 11px;
}
.kb-card footer button:first-of-type {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  color: #0284c7;
  background: #f0f9ff;
  border-color: #bae6fd;
  font-weight: 600;
}
.kb-card footer i {
  margin-left: 4px;
  color: #94a3b8;
  font-size: 20px;
  font-style: normal;
}
.no-kbs {
  grid-column: 1/-1;
  padding: 50px;
  color: #64748b;
  background: #fff;
  border: 1px dashed #cbd5e1;
  border-radius: 14px;
  text-align: center;
}
.documents {
  margin-top: 28px;
  overflow: hidden;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 14px;
}
.documents > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid #e2e8f0;
}
.documents h2 {
  margin: 0;
  font-size: 16px;
}
.documents p {
  margin: 5px 0 0;
  color: #64748b;
  font-size: 12px;
}
.documents > header > span {
  padding: 6px 10px;
  color: #0369a1;
  background: #f0f9ff;
  border-radius: 99px;
  font:
    11px "JetBrains Mono",
    monospace;
}
.documents-body {
  padding: 24px;
}
.docs-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 24px 0 12px;
}
.docs-heading h3 {
  margin: 0;
  font-size: 14px;
}
.docs-heading .el-input {
  width: 240px;
}
.filename {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #334155;
  font-weight: 600;
}
.filename .el-icon {
  color: #0284c7;
}
@media (max-width: 1000px) {
  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }
  .kb-heading {
    flex-direction: column;
  }
  .heading-actions {
    justify-content: flex-start;
  }
}
@media (max-width: 720px) {
  .kb-page {
    max-width: 100%;
  }
  .create-kb {
    padding: 20px 16px;
  }
  .create-kb-fields,
  .create-kb-chunk-fields {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .create-kb-chunking {
    padding: 14px;
  }
  .metrics,
  .kb-cards {
    grid-template-columns: 1fr;
  }
  .kb-filter {
    flex-wrap: wrap;
  }
  .kb-filter :deep(.el-select) {
    width: calc(50% - 6px);
  }
  .kb-filter :deep(.el-input) {
    flex-basis: calc(100% - 42px);
  }
  .kb-card > header {
    padding: 18px 18px 10px;
  }
  .kb-card > p {
    margin-left: 18px;
    margin-right: 18px;
  }
  .kb-card section {
    margin-left: 18px;
    margin-right: 18px;
  }
  .kb-card > footer {
    padding: 12px 18px;
  }
  .documents-body {
    padding: 16px;
  }
  .docs-heading {
    align-items: flex-start;
    gap: 10px;
    flex-direction: column;
  }
  .docs-heading .el-input {
    width: 100%;
  }
}
</style>
