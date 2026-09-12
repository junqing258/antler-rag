<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import {
  Collection,
  DocumentAdd,
  Promotion,
  Search,
  Key,
  Lock,
  Files,
  ArrowRight,
  Operation,
} from "@element-plus/icons-vue";
import { authState } from "../composables/useAuth";
import { api } from "../lib/request";
import StatCard from "../components/StatCard.vue";
import ApiCodeSnippetModal from "../components/ApiCodeSnippetModal.vue";

const mustChange = computed(() => authState.user?.must_change_password);

const stats = ref({
  kbCount: 0,
  docCount: 0,
  chunkCount: 0,
  keyCount: 0,
  loading: true,
});

const showCodeModal = ref(false);

onMounted(async () => {
  try {
    const kbsRes = await api<any>("/api/v1/knowledge-bases");
    const kbs = kbsRes.items || [];
    stats.value.kbCount = kbs.length;

    let totalDocs = 0;
    for (const kb of kbs) {
      try {
        const docsRes = await api<any>(`/api/v1/knowledge-bases/${kb.id}/documents`);
        const docs = docsRes.items || [];
        totalDocs += docs.length;
      } catch {
        // Continue
      }
    }
    stats.value.docCount = totalDocs;

    const keysRes = await api<any>("/api/v1/api-keys");
    stats.value.keyCount = keysRes.items?.length || 0;
  } catch {
    // Fallback gracefully
  } finally {
    stats.value.loading = false;
  }
});
</script>

<template>
  <section class="page dashboard">
    <!-- Header -->
    <div class="page-heading">
      <div>
        <p class="eyebrow">CONTROL CENTER</p>
        <h2>工作区概览</h2>
        <p class="page-description">
          高效管理团队知识库与向量数据，调测高质量 RAG 检索结果，并轻松接入各类 Agent 框架。
        </p>
      </div>
      <div class="header-chip">
        <span class="chip-dot"></span>
        <span>Antler RAG · Admin</span>
      </div>
    </div>

    <!-- Password Change Alert -->
    <el-alert
      v-if="mustChange"
      title="安全提醒：请先在 API 中修改初始密码后重新登录。"
      type="warning"
      show-icon
      :closable="false"
      class="notice"
    />

    <!-- Stat Grid -->
    <div class="stats-grid">
      <StatCard
        title="知识库总数"
        :value="stats.loading ? '-' : stats.kbCount"
        subtitle="工作区中已创建的知识库"
        :icon="Collection"
        color="blue"
      />
      <StatCard
        title="文档库总数"
        :value="stats.loading ? '-' : stats.docCount"
        subtitle="已解析入库的源文档"
        :icon="Files"
        color="emerald"
      />
      <StatCard
        title="活跃 API Key"
        :value="stats.loading ? '-' : stats.keyCount"
        subtitle="应用与 Agent 鉴权密钥"
        :icon="Key"
        color="violet"
      />
      <StatCard
        title="多租户隔离"
        value="SQLite + Chroma"
        subtitle="租户间数据全链路物理隔离"
        :icon="Lock"
        color="indigo"
      />
    </div>

    <!-- Quick Workflows -->
    <div class="section-title">
      <h3>核心应用场景</h3>
      <p>按步骤快速搭建并上线您的专属 AI 知识问答</p>
    </div>

    <div class="workflow-grid">
      <div class="workflow-card">
        <div class="card-step-badge blue">STEP 01</div>
        <div class="card-icon-box blue">
          <el-icon><DocumentAdd /></el-icon>
        </div>
        <div class="card-content">
          <h4>构建知识库与上传文档</h4>
          <p>支持 TXT、Markdown、PDF、DOCX 等多样格式，自动提取文本与向量切块。</p>
          <router-link to="/knowledge-bases" class="card-action">
            前往知识库 <el-icon><ArrowRight /></el-icon>
          </router-link>
        </div>
      </div>

      <div class="workflow-card">
        <div class="card-step-badge emerald">STEP 02</div>
        <div class="card-icon-box emerald">
          <el-icon><Search /></el-icon>
        </div>
        <div class="card-content">
          <h4>调测验证向量检索效果</h4>
          <p>输入自然语言提问，即时透视语义召回匹配度与底层文档 Context 片段。</p>
          <router-link to="/retrieve" class="card-action">
            前往检索调试 <el-icon><ArrowRight /></el-icon>
          </router-link>
        </div>
      </div>

      <div class="workflow-card">
        <div class="card-step-badge violet">STEP 03</div>
        <div class="card-icon-box violet">
          <el-icon><Operation /></el-icon>
        </div>
        <div class="card-content">
          <h4>创建凭证与 Agent 接入</h4>
          <p>按需分配细粒度 Scope 凭证，生成 cURL、Python 或 JS 代码直连 API。</p>
          <button class="card-action-btn" @click="showCodeModal = true">
            生成 API 代码 <el-icon><ArrowRight /></el-icon>
          </button>
        </div>
      </div>
    </div>

    <!-- Features Overview -->
    <div class="dashboard-grid">
      <article class="panel intro-card">
        <div class="panel-body">
          <div class="intro-content">
            <span class="eyebrow">DESIGNED FOR AGENTS</span>
            <h3>为企业级 Agent 提供<br />极速、可靠的知识基座</h3>
            <p>
              Antler Knowledge 采用同源单容器轻量设计，无缝提供管理控制台与高并发 OpenAPI 接入端点。
            </p>
            <div class="intro-actions">
              <router-link to="/knowledge-bases" class="btn-primary-link">
                <el-icon class="mr-1"><DocumentAdd /></el-icon>新建知识库
              </router-link>
              <button class="btn-secondary-link" @click="showCodeModal = true">
                <el-icon class="mr-1"><Operation /></el-icon>查看 API 示例
              </button>
            </div>
          </div>
        </div>
      </article>

      <article class="panel secure-card">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">安全隔离与架构设计</h3>
            <p class="panel-subtitle">了解当前工作区的数据安全保护机制</p>
          </div>
          <span class="secure-dot"></span>
        </div>
        <div class="panel-body">
          <div class="secure-row">
            <span>数据层隔离</span>
            <strong>SQLite & Chroma 隔离</strong>
          </div>
          <div class="secure-row">
            <span>模型密钥防护</span>
            <strong>LLM Key 仅服务端持有</strong>
          </div>
          <div class="secure-row">
            <span>鉴权模式</span>
            <strong>Bearer / API Key</strong>
          </div>
          <p class="secure-note">
            前端浏览器仅处理管理与调试操作，部署级 LLM Key 永远不会泄露到客户端。未配置大模型密钥时，系统仍可作为高质召回引擎使用。
          </p>
        </div>
      </article>
    </div>

    <!-- API Snippet Modal -->
    <ApiCodeSnippetModal v-model:visible="showCodeModal" />
  </section>
</template>

<style scoped>
.header-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  padding: 8px 14px;
  color: #475569;
  background: #ffffff;
  border: 1px solid var(--line, #e2e8f0);
  border-radius: 99px;
  font-size: 12px;
  font-weight: 700;
  box-shadow: var(--shadow-sm);
}

.chip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brand, #3b82f6);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 28px;
}

.section-title {
  margin-bottom: 16px;
}

.section-title h3 {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 800;
  color: var(--ink, #111827);
}

.section-title p {
  margin: 0;
  font-size: 13px;
  color: var(--muted, #64748b);
}

.workflow-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 28px;
}

.workflow-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 24px;
  background: #ffffff;
  border: 1px solid var(--line, #e2e8f0);
  border-radius: 16px;
  box-shadow: var(--shadow-sm);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.workflow-card:hover {
  transform: translateY(-3px);
  border-color: #cbd5e1;
  box-shadow: var(--shadow-md);
}

.card-step-badge {
  position: absolute;
  top: 18px;
  right: 18px;
  font-family: "DM Mono", monospace;
  font-size: 10px;
  font-weight: 800;
  padding: 3px 8px;
  border-radius: 6px;
}

.card-step-badge.blue { color: #3b82f6; background: #eff6ff; }
.card-step-badge.emerald { color: #10b981; background: #ecfdf5; }
.card-step-badge.violet { color: #8b5cf6; background: #f5f3ff; }

.card-icon-box {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  font-size: 22px;
  margin-bottom: 16px;
}

.card-icon-box.blue { color: #3b82f6; background: #eff6ff; }
.card-icon-box.emerald { color: #10b981; background: #ecfdf5; }
.card-icon-box.violet { color: #8b5cf6; background: #f5f3ff; }

.card-content h4 {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 800;
  color: var(--ink, #111827);
}

.card-content p {
  margin: 0 0 16px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--muted, #64748b);
}

.card-action,
.card-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 800;
  color: var(--brand, #3b82f6);
  text-decoration: none;
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
}

.card-action:hover,
.card-action-btn:hover {
  color: var(--brand-deep, #2563eb);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 20px;
}

.intro-card {
  background: linear-gradient(135deg, #f0f5ff 0%, #ffffff 80%);
}

.intro-card .panel-body {
  padding: 32px;
}

.intro-content h3 {
  margin: 10px 0 12px;
  color: var(--ink, #111827);
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.35;
}

.intro-content p {
  margin: 0 0 20px;
  color: var(--muted, #64748b);
  font-size: 14px;
  line-height: 1.7;
}

.intro-actions {
  display: flex;
  gap: 12px;
}

.btn-primary-link {
  display: inline-flex;
  align-items: center;
  padding: 10px 18px;
  background: var(--brand, #3b82f6);
  color: #ffffff;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  transition: all 0.2s;
}

.btn-primary-link:hover {
  background: var(--brand-deep, #2563eb);
  box-shadow: 0 4px 14px rgba(59, 130, 246, 0.3);
}

.btn-secondary-link {
  display: inline-flex;
  align-items: center;
  padding: 10px 18px;
  background: #ffffff;
  color: #334155;
  border: 1px solid var(--line, #e2e8f0);
  border-radius: 10px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary-link:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.secure-dot {
  width: 8px;
  height: 8px;
  background: #10b981;
  border-radius: 50%;
  box-shadow: 0 0 0 4px #d1fae5;
}

.secure-row {
  display: flex;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 13px;
  color: #475569;
}

.secure-row strong {
  color: #10b981;
  font-weight: 700;
}

.secure-note {
  margin: 16px 0 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.75;
}

.mr-1 {
  margin-right: 4px;
}

@media (max-width: 1024px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .workflow-grid {
    grid-template-columns: 1fr;
  }
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
