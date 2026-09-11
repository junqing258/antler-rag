<script setup lang="ts">
import { ref, onMounted } from "vue";
import {
  ChatDotRound,
  Document,
  Search,
  Operation,
  CopyDocument,
  Promotion,
  Cpu,
  Files,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { api } from "../lib/request";
import ApiCodeSnippetModal from "../components/ApiCodeSnippetModal.vue";

const kbs = ref<any[]>([]);
const kb = ref("");
const query = ref("");
const mode = ref<"retrieve" | "chat">("retrieve");
const topK = ref(5);

const results = ref<any[]>([]);
const chatAnswer = ref("");
const chatSources = ref<any[]>([]);

const loading = ref(false);
const error = ref("");
const showCodeModal = ref(false);

onMounted(async () => {
  try {
    kbs.value = (await api<any>("/api/v1/knowledge-bases")).items || [];
    kb.value = kbs.value[0]?.id ?? "";
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

function calculateSimilarity(distance: number): number {
  if (typeof distance !== "number") return 85;
  const sim = Math.max(0, Math.min(100, (1 - distance / 1.5) * 100));
  return Math.round(sim);
}

function copyChunk(content: string) {
  navigator.clipboard.writeText(content);
  ElMessage.success("片段文本已复制到剪贴板");
}
</script>

<template>
  <div class="page-layout">
    <!-- Header Card -->
    <div class="page-heading-card">
      <div class="heading-main">
        <div class="heading-icon-badge"><Search /></div>
        <div>
          <p class="eyebrow">RETRIEVAL LAB</p>
          <h2>检索调试实验室</h2>
          <p class="page-description">
            在正式生产接入前，即时验证知识库向量召回匹配质量或测试 AI 问答效果。
          </p>
        </div>
      </div>

      <el-button type="primary" plain size="default" class="header-btn" @click="showCodeModal = true">
        <el-icon class="mr-1"><Operation /></el-icon>生成接入代码
      </el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" show-icon class="notice" />

    <!-- Query Setup Form Panel -->
    <article class="panel query-panel">
      <div class="panel-header">
        <div class="panel-title-row">
          <h3 class="panel-title">调测参数与提问</h3>
          <span class="panel-subtitle">选择目标知识库并输入测试 Prompt</span>
        </div>

        <!-- Mode Switcher -->
        <div class="mode-switcher-bar">
          <el-radio-group v-model="mode" size="small">
            <el-radio-button value="retrieve">
              <el-icon class="mr-1"><Search /></el-icon>向量检索 (Retrieve)
            </el-radio-button>
            <el-radio-button value="chat">
              <el-icon class="mr-1"><Cpu /></el-icon>RAG 问答 (Chat)
            </el-radio-button>
          </el-radio-group>

          <div class="topk-box">
            <span>Top-K</span>
            <el-input-number v-model="topK" :min="1" :max="20" size="small" />
          </div>
        </div>
      </div>

      <div class="panel-body">
        <div class="search-form-grid">
          <div class="form-field kb-select-field">
            <label class="form-label">目标知识库</label>
            <el-select v-model="kb" placeholder="选择一个知识库">
              <el-option
                v-for="item in kbs"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-select>
          </div>

          <div class="form-field query-input-field">
            <label class="form-label">测试问题 / Prompt Query</label>
            <el-input
              v-model="query"
              placeholder="例如：产品退款与质保流程是怎样的？"
              clearable
              size="default"
              @keyup.enter="executeSearch"
            />
          </div>

          <div class="form-field action-btn-field">
            <label class="form-label">&nbsp;</label>
            <el-button
              type="primary"
              class="search-submit-btn"
              :loading="loading"
              :disabled="!kb || !query.trim()"
              @click="executeSearch"
            >
              <el-icon class="mr-1"><Promotion /></el-icon>开始调试
            </el-button>
          </div>
        </div>
      </div>
    </article>

    <!-- Results Section -->
    <div class="results-container" v-loading="loading">
      <!-- Retrieve Mode Results -->
      <template v-if="mode === 'retrieve'">
        <div class="result-heading">
          <div>
            <h3>召回 Context 片段</h3>
            <p>
              {{
                results.length
                  ? `找到 ${results.length} 条高度相似的文档片段`
                  : "输入测试问题并提交后，检索结果将展示在这里"
              }}
            </p>
          </div>

          <span v-if="results.length" class="result-count-badge">
            TOP {{ results.length }} RESULTS
          </span>
        </div>

        <div v-if="results.length" class="results-grid">
          <article
            v-for="(result, index) in results"
            :key="result.chunk_id || index"
            class="panel result-card"
          >
            <div class="result-index-badge">
              {{ String(index + 1).padStart(2, "0") }}
            </div>

            <div class="panel-body">
              <div class="result-meta">
                <span class="doc-tag">
                  <el-icon><Document /></el-icon>
                  {{ result.filename }}
                </span>

                <div class="score-pill">
                  <span class="distance-text">距离 {{ result.distance }}</span>
                  <div class="similarity-bar-wrap" title="匹配相似度估算">
                    <div
                      class="similarity-bar-inner"
                      :style="{ width: calculateSimilarity(result.distance) + '%' }"
                    ></div>
                  </div>
                  <span class="similarity-pct">
                    {{ calculateSimilarity(result.distance) }}% 匹配
                  </span>
                </div>
              </div>

              <div class="chunk-content-box">
                <pre>{{ result.content }}</pre>
                <button
                  class="copy-btn"
                  title="复制片段文本"
                  @click="copyChunk(result.content)"
                >
                  <el-icon><CopyDocument /></el-icon>
                </button>
              </div>
            </div>
          </article>
        </div>

        <div v-else-if="!loading" class="empty-state">
          <span class="empty-icon"><ChatDotRound /></span>
          <strong>等待输入提问</strong>
          <p>选择知识库并输入测试问题，直观透视 Chunk 片段的语义关联性。</p>
        </div>
      </template>

      <!-- Chat Mode Results -->
      <template v-else>
        <div class="result-heading">
          <h3>RAG 问答生成结果</h3>
        </div>

        <div v-if="chatAnswer" class="panel chat-answer-panel">
          <div class="panel-header">
            <h4 class="panel-title">AI 生成回答</h4>
            <el-tag type="success" size="small">RAG Model Complete</el-tag>
          </div>
          <div class="panel-body">
            <div class="chat-answer-text">{{ chatAnswer }}</div>
          </div>
        </div>

        <div v-if="chatSources.length" class="sources-section">
          <h4>参考来源片段 ({{ chatSources.length }})</h4>
          <div class="results-grid">
            <article
              v-for="(source, idx) in chatSources"
              :key="idx"
              class="panel result-card"
            >
              <div class="panel-body">
                <div class="result-meta">
                  <span class="doc-tag">
                    <el-icon><Document /></el-icon>
                    {{ source.filename }}
                  </span>
                </div>
                <pre class="chunk-content-box">{{ source.content }}</pre>
              </div>
            </article>
          </div>
        </div>

        <div v-else-if="!chatAnswer && !loading" class="empty-state">
          <span class="empty-icon"><Cpu /></span>
          <strong>等待提交对话</strong>
          <p>输入问题测试包含后端 LLM 生成的完整对话流程。</p>
        </div>
      </template>
    </div>

    <!-- Code Snippet Modal -->
    <ApiCodeSnippetModal
      v-model:visible="showCodeModal"
      :knowledge-base-id="kb"
      :query="query"
    />
  </div>
</template>

<style scoped>
.page-layout {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-heading-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 28px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.02);
}

.heading-main {
  display: flex;
  align-items: center;
  gap: 18px;
}

.heading-icon-badge {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: #eff6ff;
  color: #3b82f6;
  font-size: 24px;
}

.page-heading-card h2 {
  margin: 2px 0 4px;
  font-size: 22px;
  font-weight: 800;
  color: #0f172a;
}

.mode-switcher-bar {
  display: flex;
  align-items: center;
  gap: 16px;
}

.topk-box {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}

.search-form-grid {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}

.form-field {
  display: flex;
  flex-direction: column;
}

.kb-select-field {
  width: 260px;
}

.query-input-field {
  flex: 1;
  min-width: 300px;
}

.search-submit-btn {
  height: 40px;
  padding: 0 24px;
  font-weight: 700;
  border-radius: 10px;
}

.results-container {
  margin-top: 8px;
}

.result-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 16px;
}

.result-heading h3 {
  margin: 0 0 4px;
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
}

.result-heading p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.result-count-badge {
  padding: 5px 10px;
  color: #3b82f6;
  background: #eff6ff;
  border-radius: 6px;
  font-family: "DM Mono", monospace;
  font-size: 11px;
  font-weight: 800;
}

.results-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.result-card {
  position: relative;
  overflow: visible;
}

.result-index-badge {
  position: absolute;
  top: 20px;
  left: -12px;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: #64748b;
  background: #ffffff;
  border: 2px solid #3b82f6;
  border-radius: 50%;
  font-family: "DM Mono", monospace;
  font-size: 11px;
  font-weight: 800;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  z-index: 2;
}

.result-card .panel-body {
  padding-left: 28px;
}

.result-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 14px;
}

.doc-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}

.doc-tag .el-icon {
  color: #3b82f6;
  font-size: 16px;
}

.score-pill {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.distance-text {
  font-family: "DM Mono", monospace;
  font-size: 11px;
  color: #64748b;
}

.similarity-bar-wrap {
  width: 60px;
  height: 6px;
  background: #e2e8f0;
  border-radius: 99px;
  overflow: hidden;
}

.similarity-bar-inner {
  height: 100%;
  background: linear-gradient(90deg, #10b981, #3b82f6);
  border-radius: 99px;
}

.similarity-pct {
  font-size: 11px;
  font-weight: 800;
  color: #10b981;
}

.chunk-content-box {
  position: relative;
  background: #f8fafc;
  border: 1px solid #e9eef5;
  border-radius: 10px;
  padding: 14px;
}

.chunk-content-box pre {
  margin: 0;
  font-family: "DM Mono", monospace;
  font-size: 13px;
  line-height: 1.7;
  color: #334155;
  white-space: pre-wrap;
}

.copy-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  border-radius: 6px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.copy-btn:hover {
  color: #3b82f6;
  border-color: #3b82f6;
  background: #f0f5ff;
}

.chat-answer-panel {
  margin-bottom: 24px;
}

.chat-answer-text {
  font-size: 15px;
  line-height: 1.75;
  color: #1e293b;
  white-space: pre-wrap;
}

.sources-section h4 {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 800;
  color: #475569;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  padding: 32px;
  background: #ffffff;
  border: 2px dashed #e2e8f0;
  border-radius: 16px;
  text-align: center;
  color: #94a3b8;
}

.empty-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 24px;
  margin-bottom: 12px;
}

.empty-state strong {
  font-size: 14px;
  color: #475569;
}

.empty-state p {
  margin: 6px 0 0;
  font-size: 12px;
}

.mr-1 {
  margin-right: 4px;
}

@media (max-width: 768px) {
  .search-form-grid {
    flex-direction: column;
    align-items: stretch;
  }
  .kb-select-field,
  .query-input-field {
    width: 100%;
  }
  .search-submit-btn {
    width: 100%;
  }
}
</style>
