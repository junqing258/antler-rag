<script setup lang="ts">
import { Collection, DocumentAdd, Promotion, Search } from "@element-plus/icons-vue";
import { computed } from "vue"; import { authState } from "../composables/useAuth";
const mustChange = computed(()=>authState.user?.must_change_password);
</script>
<template>
  <section class="page dashboard">
    <div class="page-heading"><div><p class="eyebrow">CONTROL CENTER</p><h2>工作区概览</h2><p class="page-description">管理知识库内容，快速验证检索质量，并保持团队访问权限有序。</p></div><div class="date-chip">Antler RAG · 控制台</div></div>
    <el-alert v-if="mustChange" title="请先在 API 中修改初始密码后重新登录。" type="warning" :closable="false" class="notice" />
    <div class="quick-grid">
      <router-link to="/knowledge-bases" class="quick-card"><span class="quick-icon blue"><DocumentAdd /></span><div><strong>构建知识库</strong><p>上传文档，开始建立可检索的资料库。</p></div><el-icon><Promotion /></el-icon></router-link>
      <router-link to="/retrieve" class="quick-card"><span class="quick-icon green"><Search /></span><div><strong>验证检索结果</strong><p>输入问题，检查召回内容与相似度。</p></div><el-icon><Promotion /></el-icon></router-link>
    </div>
    <div class="dashboard-grid">
      <article class="panel intro-card"><div class="panel-body"><span class="quick-icon violet"><Collection /></span><div><p class="eyebrow">START HERE</p><h3>让团队知识<br />真正触手可及。</h3><p>从创建知识库开始，上传资料后即可通过检索调试验证召回质量。</p><router-link to="/knowledge-bases">前往知识库 <el-icon><Promotion /></el-icon></router-link></div></div></article>
      <article class="panel secure-card"><div class="panel-header"><div><h3 class="panel-title">安全与配置</h3><p class="panel-subtitle">关于当前工作区的数据保护</p></div><span class="secure-dot"></span></div><div class="panel-body"><div class="secure-row"><span>访问凭证</span><strong>安全存储</strong></div><div class="secure-row"><span>LLM 密钥</span><strong>浏览器不可见</strong></div><p class="secure-note">部署级 LLM 配置不会向浏览器暴露密钥；未配置时，问答接口仍会返回可用的来源片段。</p></div></article>
    </div>
  </section>
</template>
<style scoped>
.date-chip { margin-top: 8px; padding: 8px 11px; color: #718097; background: #fff; border: 1px solid var(--line); border-radius: 8px; font-size: 11px; font-weight: 700; }.quick-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 18px; margin-bottom: 20px; }.quick-card { display: flex; align-items: center; gap: 16px; min-height: 108px; padding: 20px; color: inherit; text-decoration: none; background: #fff; border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 8px 24px rgba(30,49,86,.03); transition: transform .2s, border-color .2s, box-shadow .2s; }.quick-card:hover { border-color: #cbd6ff; box-shadow: 0 12px 30px rgba(49,94,251,.1); transform: translateY(-2px); }.quick-card > .el-icon { margin-left: auto; color: #aab4c4; }.quick-card strong { display: block; font-size: 15px; }.quick-card p { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.55; }.quick-icon { display: grid; flex: 0 0 auto; width: 42px; height: 42px; place-items: center; border-radius: 12px; font-size: 20px; }.blue { color: #315efb; background: #edf1ff; }.green { color: #138468; background: #e7f8f1; }.violet { color: #7048cf; background: #f1ebff; }.dashboard-grid { display: grid; grid-template-columns: 1.1fr .9fr; gap: 20px; }.intro-card { background: linear-gradient(135deg, #f1f4ff, #fff 70%); }.intro-card .panel-body { display: flex; gap: 22px; padding: 30px; }.intro-card h3 { margin: 10px 0 11px; color: var(--ink); font-size: 25px; letter-spacing: -.7px; line-height: 1.32; }.intro-card p:not(.eyebrow) { max-width: 350px; margin: 0 0 17px; color: var(--muted); font-size: 13px; line-height: 1.7; }.intro-card a { display: inline-flex; align-items: center; gap: 5px; color: var(--brand); font-size: 13px; font-weight: 800; text-decoration: none; }.secure-dot { width: 8px; height: 8px; background: #27aa7e; border-radius: 50%; box-shadow: 0 0 0 4px #e7f7f1; }.secure-row { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #eff1f5; color: #627087; font-size: 12px; }.secure-row strong { color: #25876c; font-weight: 800; }.secure-note { margin: 15px 0 0; color: #8792a5; font-size: 12px; line-height: 1.7; } @media (max-width: 850px) { .quick-grid, .dashboard-grid { grid-template-columns: 1fr; } }
</style>
