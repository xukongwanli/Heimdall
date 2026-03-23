<script setup lang="ts">
const props = defineProps<{
  active: string
}>()

const emit = defineEmits<{
  change: [metric: string]
}>()

const options = [
  { value: 'rent_to_price_ratio', label: 'Rent/Price' },
  { value: 'avg_buy_price_per_sqft', label: 'Buy $/sqft' },
  { value: 'avg_rent_per_sqft', label: 'Rent $/sqft' },
]
</script>

<template>
  <div class="metric-toggle">
    <button
      v-for="opt in options"
      :key="opt.value"
      :class="{ active: active === opt.value }"
      @click="emit('change', opt.value)"
    >
      {{ opt.label }}
    </button>
  </div>
</template>

<style scoped>
.metric-toggle {
  display: flex;
  gap: 6px;
}

.metric-toggle button {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--border-subtle);
  transition: background 0.2s, color 0.2s;
}

.metric-toggle button.active {
  background: var(--active);
  color: #fff;
}

.metric-toggle button:hover:not(.active) {
  color: var(--text-primary);
}
</style>
