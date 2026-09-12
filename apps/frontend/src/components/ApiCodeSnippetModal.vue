<script setup lang="ts">
import { ref, computed } from "vue";
import { CopyDocument, Operation } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

const props = defineProps<{
  visible: boolean;
  knowledgeBaseId?: string;
  query?: string;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
}>();

const activeTab = ref("curl");

const kbId = computed(() => props.knowledgeBaseId || "YOUR_KNOWLEDGE_BASE_ID");
const testQuery = computed(() => props.query || "退款政策是什么？");

const baseUrl = computed(() => window.location.origin);

const curlSnippet = computed(() => {
  return `curl -X POST "${baseUrl.value}/api/v1/retrieve" \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: ark_your_api_key" \\
  -d '{
    "knowledge_base_id": "${kbId.value}",
    "query": "${testQuery.value}",
    "top_k": 5
  }'`;
});

const pythonSnippet = computed(() => {
  return `import requests

url = "${baseUrl.value}/api/v1/retrieve"
headers = {
    "Content-Type": "application/json",
    "X-API-Key": "ark_your_api_key"
}
payload = {
    "knowledge_base_id": "${kbId.value}",
    "query": "${testQuery.value}",
    "top_k": 5
}

response = requests.post(url, json=payload, headers=headers)
results = response.json().get("results", [])

for item in results:
    print(f"[{item['filename']} | dist={item['distance']}]: {item['content']}")
`;
});

const jsSnippet = computed(() => {
  return `const response = await fetch("${baseUrl.value}/api/v1/retrieve", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": "ark_your_api_key"
  },
  body: JSON.stringify({
    knowledge_base_id: "${kbId.value}",
    query: "${testQuery.value}",
    top_k: 5
  })
});

const data = await response.json();
console.log("Retrieved chunks:", data.results);`;
});

const activeCode = computed(() => {
  if (activeTab.value === "python") return pythonSnippet.value;
  if (activeTab.value === "js") return jsSnippet.value;
  return curlSnippet.value;
});

function handleClose() {
  emit("update:visible", false);
}

function copyCode() {
  navigator.clipboard.writeText(activeCode.value);
  ElMessage.success("代码片段已复制到剪贴板");
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="API 接入代码生成器"
    width="680px"
    class="code-modal"
    destroy-on-close
    @close="handleClose"
  >
    <template #header>
      <div class="modal-header">
        <span class="header-icon"><Operation /></span>
        <div>
          <h3 class="modal-title">快速接入数据 API</h3>
          <p class="modal-subtitle">在您的应用或 Agent 中直接调用通用检索与问答接口</p>
        </div>
      </div>
    </template>

    <div class="modal-body">
      <div class="tab-toolbar">
        <el-radio-group v-model="activeTab" size="small">
          <el-radio-button value="curl">cURL</el-radio-button>
          <el-radio-button value="python">Python</el-radio-button>
          <el-radio-button value="js">JavaScript / Node</el-radio-button>
        </el-radio-group>

        <el-button type="primary" size="small" @click="copyCode">
          <el-icon class="mr-1"><CopyDocument /></el-icon> 复制代码
        </el-button>
      </div>

      <div class="code-container">
        <pre><code>{{ activeCode }}</code></pre>
      </div>

      <div class="tip-box">
        <strong>提示：</strong> API Key 可在 <router-link to="/api-keys" @click="handleClose">API Key 页面</router-link> 创建，并按 scope 授予全局工作区 API 权限。
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

.modal-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.code-container {
  background: #172235;
  border-radius: 10px;
  padding: 16px;
  max-height: 320px;
  overflow-y: auto;
}

.code-container pre {
  margin: 0;
  font-family: "DM Mono", monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #e2e8f0;
}

.tip-box {
  padding: 10px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  color: #64748b;
}

.tip-box a {
  color: var(--brand, #315efb);
  font-weight: 700;
  text-decoration: none;
}

.mr-1 {
  margin-right: 4px;
}
</style>
