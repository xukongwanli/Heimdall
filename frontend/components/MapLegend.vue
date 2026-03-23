<script setup lang="ts">
const props = defineProps<{
  label: string
  min: number
  max: number
}>()

const midLabel = computed(() => {
  const mid = (props.min + props.max) / 2
  return mid.toFixed(2)
})
</script>

<template>
  <div class="map-legend">
    <div class="legend-title label">{{ label }}</div>
    <div class="legend-bar"></div>
    <div class="legend-labels">
      <span>{{ min.toFixed(2) }}</span>
      <span>{{ midLabel }}</span>
      <span>{{ max.toFixed(2) }}</span>
    </div>
  </div>
</template>

<style scoped>
.map-legend {
  position: absolute;
  bottom: 16px;
  left: 16px;
  background: rgba(22, 27, 34, 0.92);
  border: 1px solid var(--border-interactive);
  border-radius: 6px;
  padding: 10px 14px;
  z-index: 1000;
}

.legend-title {
  margin-bottom: 6px;
  font-size: 10px;
}

.legend-bar {
  width: 120px;
  height: 10px;
  border-radius: 5px;
  background: linear-gradient(90deg, #0a84ff, #32d74b, #ff9f0a, #ff453a);
}

.legend-labels {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: var(--text-muted);
  margin-top: 2px;
}
</style>
