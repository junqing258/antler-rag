<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    title: string;
    value: string | number;
    subtitle?: string;
    trend?: string;
    trendType?: "up" | "down" | "neutral";
    icon?: any;
    color?: "blue" | "emerald" | "violet" | "amber" | "indigo";
  }>(),
  {
    subtitle: "",
    trend: "",
    trendType: "neutral",
    color: "blue",
  },
);

const themeClass = computed(() => `stat-${props.color}`);
</script>

<template>
  <div class="stat-card" :class="themeClass">
    <div class="stat-main">
      <p class="stat-title">{{ title }}</p>

      <div class="stat-value-row">
        <span class="stat-value">{{ value }}</span>
        <span
          v-if="trend"
          class="stat-trend"
          :class="`trend-${trendType}`"
        >
          {{ trend }}
        </span>
      </div>

      <p v-if="subtitle" class="stat-subtitle">{{ subtitle }}</p>
    </div>

    <div v-if="icon" class="stat-icon-wrapper">
      <component :is="icon" class="stat-icon" />
    </div>
  </div>
</template>

<style scoped>
.stat-card {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22px 24px;
  background: var(--surface, #ffffff);
  border: 1px solid var(--line, #e7ebf1);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(30, 49, 86, 0.03);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

.stat-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  border-radius: 4px 0 0 4px;
  background: transparent;
  transition: background 0.25s;
}

.stat-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 32px rgba(30, 49, 86, 0.08);
  border-color: #d1dbed;
}

.stat-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  z-index: 1;
}

.stat-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--muted, #687386);
  letter-spacing: 0.01em;
}

.stat-value-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.stat-value {
  font-size: 30px;
  font-weight: 800;
  color: var(--ink, #172235);
  letter-spacing: -0.03em;
  line-height: 1.15;
}

.stat-trend {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 6px;
}

.trend-up {
  color: #107555;
  background: #e6f7f1;
}

.trend-down {
  color: #c0392b;
  background: #fdf0ed;
}

.trend-neutral {
  color: #5c6b84;
  background: #f0f3f8;
}

.stat-subtitle {
  margin: 2px 0 0;
  font-size: 12px;
  color: #8996ab;
}

.stat-icon-wrapper {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  font-size: 22px;
  transition: transform 0.25s;
}

.stat-card:hover .stat-icon-wrapper {
  transform: scale(1.08);
}

/* Colors */
.stat-blue .stat-icon-wrapper {
  color: #315efb;
  background: #edf1ff;
}
.stat-blue::before { background: #315efb; }

.stat-emerald .stat-icon-wrapper {
  color: #108967;
  background: #e6f7f1;
}
.stat-emerald::before { background: #108967; }

.stat-violet .stat-icon-wrapper {
  color: #7c3aed;
  background: #f3e8ff;
}
.stat-violet::before { background: #7c3aed; }

.stat-amber .stat-icon-wrapper {
  color: #d97706;
  background: #fef3c7;
}
.stat-amber::before { background: #d97706; }

.stat-indigo .stat-icon-wrapper {
  color: #4f46e5;
  background: #eef2ff;
}
.stat-indigo::before { background: #4f46e5; }
</style>
