<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  ChatDotRound,
  Document,
  Search,
  Operation,
  CopyDocument,
  Promotion,
  Cpu,
  DataAnalysis,
  RefreshLeft,
  Setting,
  Lightning,
  Check,
  Collection,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { api } from "../lib/request";
import ApiCodeSnippetModal from "../components/ApiCodeSnippetModal.vue";

const kbs = ref<any[]>([]);
const kb = ref("");
const query = ref("");
const mode = ref<"retrieve" | "chat">("retrieve");
const topK = ref(5);
const threshold = ref(0.65);
const rerank = ref(false);
const results = ref<any[]>([]);
const chatAnswer = ref("");
const chatSources = ref<any[]>([]);
const loading = ref(false);
const error = ref("");
const showCodeModal = ref(false);
const route = useRoute();
const selectedKb = computed(() =>
  kbs.value.find((item) => item.id === kb.value),
);
const renderedAnswer = computed(() =>
  DOMPurify.sanitize(marked.parse(chatAnswer.value, { async: false }) as string),
);
onMounted(async () => {
  try {
    kbs.value = (await api<any>("/api/v1/knowledge-bases")).items || [];
    const preset = route.query.kb;
    kb.value =
      preset && kbs.value.some((item) => item.id === preset)
        ? String(preset)
        : (kbs.value[0]?.id ?? "");
  } catch (e: any) {
    error.value = e.message;
  }
});
async function executeSearch() {
  if (!kb.value || !query.value.trim()) return;
  loading.value = true;
  error.value = "";
  results.value = [];
  chatAnswer.value = "";
  chatSources.value = [];
  try {
    if (mode.value === "retrieve") {
      const res = await api<any>("/api/v1/retrieve", {
        method: "POST",
        body: JSON.stringify({
          knowledge_base_id: kb.value,
          query: query.value,
          top_k: topK.value,
          score_threshold: threshold.value,
          rerank: rerank.value,
        }),
      });
      results.value = res.results || [];
    } else {
      const res = await api<any>("/api/v1/chat", {
        method: "POST",
        body: JSON.stringify({
          knowledge_base_id: kb.value,
          message: query.value,
          top_k: topK.value,
          score_threshold: threshold.value,
          rerank: rerank.value,
        }),
      });
      chatAnswer.value = res.answer || res.message || "收到召回结果：";
      chatSources.value = res.sources || res.results || [];
    }
  } catch (e: any) {
    error.value = e.message || "请求失败";
  } finally {
    loading.value = false;
  }
}
function similarity(distance: number) {
  return typeof distance === "number"
    ? Math.round(Math.max(0, Math.min(100, (1 - distance) * 100)))
    : 85;
}
function copyChunk(content: string) {
  navigator.clipboard.writeText(content);
  ElMessage.success("片段文本已复制到剪贴板");
}
function useExample(text: string) {
  query.value = text;
}
</script>

<template>
  <section class="search-page">
    <div class="search-heading">
      <div>
        <div class="crumb">
          <span>控制台</span><b>/</b
          ><span>{{ selectedKb?.id || "知识库" }}</span
          ><b>/</b><strong>检索测试</strong>
        </div>
        <h1>检索测试</h1>
        <p>
          实时调试知识库的向量召回、相似度过滤与可选的神经重排效果
        </p>
      </div>
      <div class="heading-buttons">
        <button @click="showCodeModal = true">＜＞ API 代码预览</button
        ><button>
          <el-icon><RefreshLeft /></el-icon>历史记录 <b>12</b></button
        ><button title="配置">
          <el-icon><Setting /></el-icon>
        </button>
      </div>
    </div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      class="notice"
    />
    <div class="debug-layout">
      <aside class="debug-form">
        <article>
          <header>
            <h2>
              <el-icon><Collection /></el-icon>目标知识库
            </h2>
            <span>● 已同步索引</span>
          </header>
          <el-select v-model="kb" class="kb-picker"
            ><el-option
              v-for="item in kbs"
              :key="item.id"
              :label="item.name"
              :value="item.id"
          /></el-select>
          <p class="cluster-note">Cluster Node: <b>local-chroma-01</b></p>
          <div class="kb-stats">
            <div><small>文档总数</small><b>已连接</b></div>
            <div>
              <small>切片总数</small><b>{{ topK }} Top-K</b>
            </div>
            <div><small>嵌入向量模型</small><b>text-emb-3-sm</b></div>
          </div>
        </article>
        <article>
          <header>
            <h2>
              <el-icon><Search /></el-icon>测试查询文本 (Test Query)
            </h2>
            <span>{{ query.length }} / 512</span>
          </header>
          <textarea
            v-model="query"
            maxlength="512"
            placeholder="如何配置多租户隔离与 API 鉴权？"
            @keydown.ctrl.enter="executeSearch"
            @keydown.meta.enter="executeSearch"
          ></textarea>
          <div class="quick-examples">
            <b>快速示例：</b
            ><button @click="useExample('如何配置多租户隔离与 API 鉴权？')">
              多租户鉴权</button
            ><button @click="useExample('文档切片重排配置有哪些建议？')">
              切片重排配置</button
            ><button @click="useExample('API 的限流规则是什么？')">
              API限流规则
            </button>
          </div>
        </article>
        <article class="parameters">
          <header>
            <h2>
              <el-icon><DataAnalysis /></el-icon>检索管道超参数
            </h2>
            <span>向量检索</span>
          </header>
          <label>召回算法模式 (MODE)</label>
          <div class="mode-toggle">
            <button
              :class="{ active: mode === 'retrieve' }"
              @click="mode = 'retrieve'"
            >
              向量检索<br />(Vector)
            </button>
            <button
              :class="{ active: mode === 'chat' }"
              @click="mode = 'chat'"
            >
              RAG 问答<br />(Chat)
            </button>
          </div>
          <div class="topk-row">
            <div>
              <b>TOP-K 返回限制</b><span>最终返回的结果数量</span>
            </div>
            <div>
              <button
                v-for="number in [3, 5, 10, 20]"
                :key="number"
                :class="{ active: topK === number }"
                @click="topK = number"
              >
                {{ number }}
              </button>
            </div>
          </div>
          <div class="threshold">
            <div>
              <b>相似度阈值 (SCORE THRESHOLD)</b
              ><span>{{ threshold.toFixed(2) }}</span>
            </div>
            <input
              v-model.number="threshold"
              type="range"
              min="0"
              max="1"
              step="0.05"
            />
            <footer>
              <span>0.0（宽松全量）</span><span>0.50</span
              ><span>1.0（极严格）</span>
            </footer>
          </div>
          <div class="rerank">
            <el-icon><DataAnalysis /></el-icon>
            <div>
              <b>神经重排 (Reranker)</b
              ><span>Cross-Encoder（需配置 RAG_RERANKER_BASE_URL）</span>
            </div>
            <el-switch v-model="rerank" />
          </div>
          <div class="metadata">
            <label>元数据硬过滤 (METADATA FILTER)</label
            ><code>knowledge_base_id = "selected" &amp;&amp; status = "active"</code>
          </div>
          <el-button
            type="primary"
            class="execute"
            :loading="loading"
            :disabled="!kb || !query.trim()"
            @click="executeSearch"
            ><el-icon><Lightning /></el-icon>执行检索 (Test Query)<kbd
              >⌘ + Enter</kbd
            ></el-button
          >
        </article>
      </aside>
      <main class="search-results" v-loading="loading">
        <article class="request-status">
          <div>
            <span>● 200 OK</span
            ><b>命中：{{ results.length || chatSources.length || "—" }} Hits</b>
          </div>
          <p>
            <el-icon><Check /></el-icon>已应用阈值过滤
            <strong v-if="rerank">与神经重排</strong
            ><strong v-else>；未启用神经重排</strong>
          </p>
          <footer>
            <button class="active">▤ 卡片</button><button>▦ 表格</button
            ><button>{ } JSON</button>
          </footer>
        </article>
        <template v-if="mode === 'retrieve' && results.length"
          ><article
            v-for="(result, index) in results"
            :key="result.chunk_id || index"
            class="result-item"
            :class="{ best: index === 0 }"
          >
            <header>
              <div>
                <span>#{{ String(index + 1).padStart(2, "0") }}</span>
                <h2>
                  <el-icon><Document /></el-icon
                  >{{ result.filename || "知识库文档" }}
                </h2>
              </div>
              <div class="score">
                Score: {{ (similarity(result.distance) / 100).toFixed(3)
                }}<small>（Cosine Dist: {{ result.distance ?? "—" }}）</small
                ><small v-if="result.rerank_score !== null && result.rerank_score !== undefined">Rerank: {{ result.rerank_score.toFixed(3) }}</small>
              </div>
            </header>
            <div class="result-content">{{ result.content }}</div>
            <footer>
              <div>
                Chunk
                <b
                  >#{{
                    result.chunk_id || String(index + 1).padStart(4, "0")
                  }}</b
                ><i>•</i
                ><b>{{ result.content?.length || 0 }}</b> Tokens<i>•</i>Cosine
                Dist: <strong>{{ result.distance ?? "—" }}</strong>
              </div>
              <div>
                <button>＜＞ Metadata</button
                ><button @click="copyChunk(result.content)">
                  <el-icon><CopyDocument /></el-icon>复制</button
                ><button>♧ 有效</button><button>♧ Bad Case</button>
              </div>
            </footer>
          </article></template
        >
        <template
          v-else-if="mode === 'chat' && (chatAnswer || chatSources.length)"
          ><article class="chat-answer">
            <header>
              <h2>
                <el-icon><Cpu /></el-icon>AI 生成回答
              </h2>
              <span>RAG Model Complete</span>
            </header>
            <!-- eslint-disable-next-line vue/no-v-html -- 内容经 DOMPurify 消毒 -->
            <div class="chat-answer-body markdown-body" v-html="renderedAnswer"></div>
          </article>
          <article
            v-for="(source, index) in chatSources"
            :key="index"
            class="result-item"
          >
            <header>
              <div>
                <span>#{{ String(index + 1).padStart(2, "0") }}</span>
                <h2>
                  <el-icon><Document /></el-icon
                  >{{ source.filename || "引用来源" }}
                </h2>
              </div>
            </header>
            <div class="result-content">{{ source.content }}</div>
            <footer>
              <button @click="copyChunk(source.content)">
                <el-icon><CopyDocument /></el-icon>复制片段
              </button>
            </footer>
          </article></template
        >
        <div v-else class="empty-result">
          <el-icon><ChatDotRound /></el-icon><strong>等待执行检索</strong>
          <p>设置查询文本和调试参数后，召回片段将在此展示。</p>
        </div>
        <div class="search-tip mt-4">
          <el-icon><Lightning /></el-icon
          ><span
            >提示：若召回结果过多噪音切片，可尝试调高 Rerank 过滤阈值至
            0.75+，或在超参数栏补充元数据硬谓词约束。</span
          ><a href="#">调优手册 →</a>
        </div>
      </main>
    </div>
    <ApiCodeSnippetModal
      v-model:visible="showCodeModal"
      :knowledge-base-id="kb"
      :query="query"
      :score-threshold="threshold"
      :rerank="rerank"
    />
  </section>
</template>

<style scoped>
.search-page {
  max-width: 1220px;
  margin: 0 auto;
}
.search-heading {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 26px;
}
.crumb {
  display: flex;
  gap: 8px;
  margin-bottom: 7px;
  color: #64748b;
  font:
    11px "JetBrains Mono",
    monospace;
}
.crumb b {
  color: #cbd5e1;
}
.crumb strong {
  color: #0284c7;
}
.search-heading h1 {
  margin: 0;
  color: #0f172a;
  font-size: 29px;
  letter-spacing: -0.04em;
}
.search-heading p {
  margin: 5px 0 0;
  color: #64748b;
  font-size: 13px;
}
.heading-buttons {
  display: flex;
  align-items: flex-end;
  gap: 9px;
}
.heading-buttons button {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 38px;
  padding: 0 12px;
  color: #334155;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.heading-buttons b {
  padding: 2px 6px;
  color: #0284c7;
  background: #e0f2fe;
  border-radius: 99px;
  font:
    10px "JetBrains Mono",
    monospace;
}
.debug-layout {
  display: grid;
  grid-template-columns: 490px minmax(0, 1fr);
  gap: 28px;
}
.debug-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.debug-form article,
.request-status,
.result-item,
.chat-answer {
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 12px;
  box-shadow: 0 2px 4px rgba(15, 23, 42, 0.02);
}
.debug-form article {
  overflow: hidden;
  padding: 20px;
}
.debug-form article > header,
.request-status > header,
.chat-answer header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 13px;
}
.debug-form h2,
.chat-answer h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 16px;
}
.debug-form h2 .el-icon {
  color: #0284c7;
}
.debug-form header > span {
  color: #059669;
  font:
    11px "JetBrains Mono",
    monospace;
}
.kb-picker {
  width: 100%;
}
.cluster-note {
  margin: 5px 0 12px;
  color: #64748b;
  font:
    11px "JetBrains Mono",
    monospace;
}
.cluster-note b {
  color: #0369a1;
}
.kb-stats {
  display: grid;
  grid-template-columns: 1fr 1fr 1.25fr;
  gap: 7px;
}
.kb-stats div {
  padding: 9px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
}
.kb-stats small,
.topk-row span,
.rerank span {
  display: block;
  color: #94a3b8;
  font-size: 10px;
}
.kb-stats b {
  display: block;
  margin-top: 3px;
  color: #0284c7;
  font:
    600 11px "JetBrains Mono",
    monospace;
}
.debug-form textarea {
  width: 100%;
  height: 103px;
  padding: 13px;
  resize: vertical;
  color: #1e293b;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  font:
    13px "Geist",
    "Noto Sans SC",
    sans-serif;
  line-height: 1.6;
}
.debug-form textarea:focus {
  outline: 2px solid #7dd3fc;
  border-color: #0284c7;
}
.quick-examples {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
  color: #64748b;
  font-size: 11px;
}
.quick-examples button {
  padding: 4px 8px;
  color: #334155;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  cursor: pointer;
  font:
    10px "JetBrains Mono",
    monospace;
}
.parameters > label,
.metadata label {
  display: block;
  margin-bottom: 8px;
  color: #475569;
  font:
    600 11px "JetBrains Mono",
    monospace;
}
.mode-toggle {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin-bottom: 18px;
  padding: 4px;
  background: #f1f5f9;
  border: 1px solid #dbe3ed;
  border-radius: 6px;
}
.mode-toggle button {
  padding: 8px 3px;
  color: #475569;
  background: transparent;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.mode-toggle button.active {
  color: #fff;
  background: #0284c7;
  font-weight: 700;
}
.topk-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 18px;
}
.topk-row b {
  display: block;
  color: #334155;
  font:
    600 11px "JetBrains Mono",
    monospace;
}
.topk-row div:last-child {
  display: flex;
  gap: 5px;
}
.topk-row button {
  width: 31px;
  height: 28px;
  color: #334155;
  background: #fff;
  border: 1px solid #dbe3ed;
  border-radius: 3px;
  cursor: pointer;
  font:
    11px "JetBrains Mono",
    monospace;
}
.topk-row button.active {
  color: #fff;
  background: #0284c7;
  border-color: #0284c7;
}
.threshold > div {
  display: flex;
  justify-content: space-between;
  color: #334155;
  font:
    600 11px "JetBrains Mono",
    monospace;
}
.threshold > div span {
  padding: 3px 7px;
  color: #0369a1;
  background: #e0f2fe;
  border-radius: 3px;
}
.threshold input {
  width: 100%;
  margin: 8px 0 0;
  accent-color: #0284c7;
}
.threshold footer {
  display: flex;
  justify-content: space-between;
  color: #64748b;
  font:
    10px "JetBrains Mono",
    monospace;
}
.rerank {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 19px 0;
  padding: 13px;
  background: #f8fafc;
  border: 1px solid #dbe3ed;
  border-radius: 6px;
}
.rerank > .el-icon {
  color: #4f46e5;
  font-size: 20px;
}
.rerank div {
  flex: 1;
}
.rerank b {
  display: block;
  font-size: 13px;
}
.metadata code {
  display: block;
  padding: 12px;
  color: #059669;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 5px;
  font:
    11px "JetBrains Mono",
    monospace;
}
.execute {
  width: 100%;
  margin-top: 19px;
  font-size: 16px;
}
.execute kbd {
  margin-left: 8px;
  padding: 3px 6px;
  color: #bae6fd;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 3px;
  font:
    10px "JetBrains Mono",
    monospace;
}
.search-results {
  min-width: 0;
}
.request-status {
  padding: 16px;
  margin-bottom: 16px;
}
.request-status > div {
  display: flex;
  align-items: center;
  gap: 25px;
}
.request-status > div span {
  color: #059669;
  font:
    11px "JetBrains Mono",
    monospace;
}
.request-status > div b {
  color: #475569;
  font:
    11px "JetBrains Mono",
    monospace;
}
.request-status p {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin: 10px 0;
  color: #64748b;
  background: #f1f5f9;
  padding: 8px 12px;
  font:
    11px "JetBrains Mono",
    monospace;
}
.request-status p .el-icon,
.request-status p strong {
  color: #0284c7;
}
.request-status footer {
  display: flex;
  gap: 3px;
  padding: 3px;
  background: #f1f5f9;
  border-radius: 4px;
  width: max-content;
}
.request-status footer button {
  padding: 6px 9px;
  color: #475569;
  background: transparent;
  border: 0;
  border-radius: 3px;
  cursor: pointer;
  font:
    12px "JetBrains Mono",
    monospace;
}
.request-status footer button.active {
  color: #0284c7;
  background: #fff;
  box-shadow: 0 1px 3px #cbd5e1;
}
.result-item {
  position: relative;
  margin-bottom: 16px;
  padding: 20px;
}
.result-item.best {
  border-left: 5px solid #0284c7;
}
.result-item header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.result-item header > div:first-child {
  display: flex;
  align-items: center;
  gap: 9px;
}
.result-item header span {
  padding: 4px 8px;
  color: #334155;
  background: #e2e8f0;
  border-radius: 3px;
  font:
    600 11px "JetBrains Mono",
    monospace;
}
.best header span {
  color: #fff;
  background: #0284c7;
}
.result-item h2 {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0;
  font-size: 14px;
}
.result-item h2 .el-icon {
  color: #0284c7;
}
.score {
  padding: 7px 9px;
  color: #0369a1;
  background: #e0f2fe;
  font:
    600 11px "JetBrains Mono",
    monospace;
}
.score small {
  display: block;
  margin-top: 2px;
  color: #64748b;
  font-weight: 400;
}
.result-content {
  padding: 15px;
  color: #1e293b;
  background: #f8fafc;
  border: 1px solid #dbe3ed;
  line-height: 1.7;
  white-space: pre-wrap;
  font-size: 13px;
}
.result-item footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 15px;
  color: #64748b;
  font:
    10px "JetBrains Mono",
    monospace;
}
.result-item footer > div {
  display: flex;
  align-items: center;
  gap: 9px;
}
.result-item footer i {
  font-style: normal;
}
.result-item footer strong {
  color: #059669;
}
.result-item footer button {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 6px 8px;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  cursor: pointer;
  font-size: 10px;
}
.chat-answer {
  padding: 20px;
  margin-bottom: 16px;
}
.chat-answer header span {
  padding: 5px 8px;
  color: #059669;
  background: #ecfdf5;
  border-radius: 4px;
  font:
    10px "JetBrains Mono",
    monospace;
}
.chat-answer-body {
  margin: 0;
  color: #334155;
  line-height: 1.7;
  font-size: 13px;
  word-break: break-word;
}
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 16px 0 8px;
  color: #0f172a;
  font-weight: 600;
  line-height: 1.4;
}
.markdown-body :deep(h1) {
  font-size: 18px;
}
.markdown-body :deep(h2) {
  font-size: 16px;
}
.markdown-body :deep(h3) {
  font-size: 14px;
}
.markdown-body :deep(h1:first-child),
.markdown-body :deep(h2:first-child),
.markdown-body :deep(h3:first-child) {
  margin-top: 0;
}
.markdown-body :deep(p) {
  margin: 0 0 10px;
}
.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 10px;
  padding-left: 22px;
}
.markdown-body :deep(li) {
  margin: 4px 0;
}
.markdown-body :deep(a) {
  color: #0284c7;
  text-decoration: none;
}
.markdown-body :deep(a:hover) {
  text-decoration: underline;
}
.markdown-body :deep(code) {
  padding: 2px 5px;
  color: #0f172a;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 3px;
  font:
    12px "JetBrains Mono",
    monospace;
}
.markdown-body :deep(pre) {
  margin: 0 0 10px;
  padding: 12px;
  background: #0f172a;
  border-radius: 6px;
  overflow-x: auto;
}
.markdown-body :deep(pre code) {
  padding: 0;
  color: #e2e8f0;
  background: transparent;
  border: 0;
  font-size: 12px;
}
.markdown-body :deep(blockquote) {
  margin: 0 0 10px;
  padding: 6px 12px;
  color: #475569;
  border-left: 3px solid #7dd3fc;
  background: #f8fafc;
}
.markdown-body :deep(table) {
  margin: 0 0 10px;
  border-collapse: collapse;
  font-size: 12px;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 6px 10px;
  border: 1px solid #dbe3ed;
  text-align: left;
}
.markdown-body :deep(th) {
  color: #334155;
  background: #f8fafc;
  font-weight: 600;
}
.markdown-body :deep(hr) {
  margin: 14px 0;
  border: 0;
  border-top: 1px solid #e2e8f0;
}
.markdown-body :deep(strong) {
  color: #0f172a;
}
.empty-result {
  display: flex;
  min-height: 300px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  background: #fff;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
}
.empty-result > .el-icon {
  margin-bottom: 12px;
  color: #0284c7;
  font-size: 32px;
}
.empty-result strong {
  color: #475569;
}
.empty-result p {
  margin: 6px 0 0;
  font-size: 12px;
}
.search-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  color: #0369a1;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 10px;
  font-size: 11px;
}
.search-tip .el-icon {
  font-size: 18px;
}
.search-tip a {
  margin-left: auto;
  color: #0284c7;
  text-decoration: none;
  font-weight: 600;
  white-space: nowrap;
}
@media (max-width: 1100px) {
  .debug-layout {
    grid-template-columns: 380px minmax(0, 1fr);
  }
}
@media (max-width: 860px) {
  .search-heading {
    flex-direction: column;
  }
  .heading-buttons {
    align-items: flex-start;
  }
  .debug-layout {
    grid-template-columns: 1fr;
  }
  .result-item footer {
    align-items: flex-start;
    flex-direction: column;
  }
  .search-tip {
    align-items: flex-start;
  }
  .search-tip a {
    margin-left: 0;
  }
}
@media (max-width: 540px) {
  .heading-buttons {
    flex-wrap: wrap;
  }
  .debug-form article {
    padding: 15px;
  }
  .kb-stats {
    grid-template-columns: 1fr;
  }
  .result-item {
    padding: 14px;
  }
  .result-item header {
    flex-direction: column;
  }
  .score {
    align-self: flex-start;
  }
  .result-item footer > div:last-child {
    flex-wrap: wrap;
  }
}
</style>
