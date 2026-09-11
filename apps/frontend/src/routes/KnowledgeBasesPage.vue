<script setup lang="ts">
import { DocumentAdd, Files, FolderAdd, UploadFilled } from "@element-plus/icons-vue";
import { onMounted, ref } from "vue"; import { api } from "../lib/request";
const items=ref<any[]>([]); const name=ref(""); const error=ref(""); const selected=ref<any>(); const files=ref<File[]>([]);
async function load(){try{items.value=(await api<any>("/api/v1/knowledge-bases")).items}catch(e:any){error.value=e.message}}
async function create(){await api("/api/v1/knowledge-bases",{method:"POST",body:JSON.stringify({name:name.value})});name.value="";await load()}
async function upload(){if(!selected.value||!files.value.length)return;const form=new FormData();files.value.forEach(f=>form.append("files",f));await api(`/api/v1/knowledge-bases/${selected.value.id}/documents`,{method:"POST",body:form});await documents()}
const docs=ref<any[]>([]); async function documents(){docs.value=(await api<any>(`/api/v1/knowledge-bases/${selected.value.id}/documents`)).items} async function choose(kb:any){selected.value=kb;await documents()} async function remove(doc:any){await api(`/api/v1/knowledge-bases/${selected.value.id}/documents/${doc.id}`,{method:"DELETE"});await documents()}
onMounted(load);
</script>
<template>
  <section class="page">
    <div class="page-heading"><div><p class="eyebrow">KNOWLEDGE HUB</p><h2>知识库</h2><p class="page-description">集中管理文档并为团队问答建立可靠的知识来源。</p></div></div>
    <el-alert v-if="error" :title="error" type="error" class="notice" />
    <article class="panel">
      <div class="panel-header"><div><h3 class="panel-title">全部知识库</h3><p class="panel-subtitle">点击一行即可查看和管理其中的文档</p></div><el-form class="create-form" @submit.prevent="create"><el-input v-model="name" placeholder="输入知识库名称" /><el-button type="primary" native-type="submit"><el-icon><FolderAdd /></el-icon>新建知识库</el-button></el-form></div>
      <div class="panel-body flush table-wrap"><el-table :data="items" class="clickable-table" @row-click="choose"><el-table-column prop="name" label="名称" min-width="240"><template #default="s"><span class="table-name"><el-icon><Files /></el-icon>{{s.row.name}}</span></template></el-table-column><el-table-column prop="status" label="状态" width="140"><template #default="s"><span class="status" :class="s.row.status">{{s.row.status}}</span></template></el-table-column><el-table-column label="默认" width="130"><template #default="s"><el-tag :type="s.row.is_default ? 'primary' : 'info'" effect="light" size="small">{{s.row.is_default?'默认':'—'}}</el-tag></template></el-table-column></el-table></div>
    </article>
    <article v-if="selected" class="panel document-panel">
      <div class="panel-header"><div><h3 class="panel-title">{{selected.name}} 的文档</h3><p class="panel-subtitle">上传新文件后会自动拆分并建立索引</p></div><span class="doc-count">{{ docs.length }} 个文件</span></div>
      <div class="upload-bar"><label class="file-input"><input type="file" multiple @change="files=Array.from(($event.target as HTMLInputElement).files ?? [])" /><el-icon><DocumentAdd /></el-icon><span>{{ files.length ? `已选择 ${files.length} 个文件` : '选择要上传的文件' }}</span></label><el-button type="primary" :disabled="!files.length" @click="upload"><el-icon><UploadFilled /></el-icon>上传并索引</el-button></div>
      <div class="panel-body flush table-wrap"><el-table :data="docs"><el-table-column prop="filename" label="文件" min-width="270"><template #default="s"><span class="table-name"><el-icon><DocumentAdd /></el-icon>{{s.row.filename}}</span></template></el-table-column><el-table-column prop="status" label="状态" width="140"><template #default="s"><span class="status" :class="s.row.status">{{s.row.status}}</span></template></el-table-column><el-table-column prop="chunk_count" label="CHUNKS" width="120"/><el-table-column label="操作" width="100"><template #default="s"><el-button link type="danger" @click="remove(s.row)">删除</el-button></template></el-table-column></el-table></div>
    </article>
  </section>
</template>
<style scoped>
.create-form { display: flex; gap: 10px; }.create-form :deep(.el-input) { width: 220px; }.create-form :deep(.el-button .el-icon), .upload-bar :deep(.el-button .el-icon) { margin-right: 5px; }.table-name { display: inline-flex; align-items: center; gap: 9px; color: #344157; font-weight: 700; }.table-name .el-icon { color: var(--brand); font-size: 17px; }.clickable-table :deep(.el-table__row) { cursor: pointer; }.document-panel { margin-top: 20px; }.doc-count { padding: 5px 9px; color: #6f7c90; background: #f5f7fb; border-radius: 6px; font-size: 11px; font-weight: 700; }.upload-bar { display: flex; align-items: center; gap: 12px; padding: 16px 22px; border-bottom: 1px solid var(--line); background: #fafbfe; }.file-input { display: inline-flex; align-items: center; gap: 8px; min-width: 250px; color: #607087; font-size: 12px; font-weight: 600; cursor: pointer; }.file-input input { position: absolute; width: 1px; height: 1px; opacity: 0; }.file-input .el-icon { color: var(--brand); font-size: 17px; } @media (max-width: 720px) { .panel-header { align-items: flex-start; flex-direction: column; }.create-form { width: 100%; }.create-form :deep(.el-input) { width: auto; flex: 1; }.upload-bar { align-items: flex-start; flex-direction: column; } }
</style>
