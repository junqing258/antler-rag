<script setup lang="ts">
defineProps<{ chunk: any }>();
const qualityLabels: Record<string, string> = {
  headings: "标题/章节",
  paragraphs: "按段落",
  page_text: "按页/段落（未识别章节）",
};
</script>

<template>
  <div class="chunk-provenance">
    <span v-if="chunk.heading_path?.length">{{
      chunk.heading_path.join(" → ")
    }}</span>
    <span v-if="chunk.page_start != null"
      >第 {{ chunk.page_start
      }}<template v-if="chunk.page_end !== chunk.page_start"
        >–{{ chunk.page_end }}</template
      >
      页</span
    >
    <span v-if="chunk.line_start != null"
      >行 {{ chunk.line_start }}–{{ chunk.line_end }}</span
    >
    <span v-if="chunk.structure_quality">{{
      qualityLabels[chunk.structure_quality] || chunk.structure_quality
    }}</span>
    <span v-else-if="chunk.chunk_strategy === 'recursive'">递归分块</span>
  </div>
</template>

<style scoped>
.chunk-provenance {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 6px 0;
  color: #64748b;
  font-size: 12px;
}
</style>
