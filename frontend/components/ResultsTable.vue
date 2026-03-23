<script setup lang="ts">
import type { SearchResult } from '~/composables/useSearch'

const props = defineProps<{
  results: SearchResult[]
  loading: boolean
}>()

const { convert, unitLabel } = useUnits()

type SortKey = 'location' | 'buy' | 'rent' | 'ratio'
const sortKey = ref<SortKey>('ratio')
const sortAsc = ref(false)

function locationName(r: SearchResult): string {
  return r.city ? `${r.city}, ${r.region}` : r.region
}

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    sortAsc.value = !sortAsc.value
  } else {
    sortKey.value = key
    sortAsc.value = false
  }
}

const sorted = computed(() => {
  const rows = [...props.results]
  const dir = sortAsc.value ? 1 : -1

  rows.sort((a, b) => {
    let va: number | string | null
    let vb: number | string | null

    switch (sortKey.value) {
      case 'location':
        return dir * locationName(a).localeCompare(locationName(b))
      case 'buy':
        va = a.avg_buy_price_per_sqft
        vb = b.avg_buy_price_per_sqft
        break
      case 'rent':
        va = a.avg_rent_per_sqft
        vb = b.avg_rent_per_sqft
        break
      case 'ratio':
        va = a.rent_to_price_ratio
        vb = b.rent_to_price_ratio
        break
    }

    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    return dir * ((va as number) - (vb as number))
  })

  return rows
})

function formatValue(v: number | null | undefined): string {
  if (v == null) return '—'
  return `$${convert(v)?.toFixed(2)}`
}

function formatRatio(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toFixed(4)
}
</script>

<template>
  <div v-if="results.length > 0 || loading" class="results-container">
    <div class="results-header label">
      <span v-if="loading">Searching...</span>
      <span v-else>{{ results.length }} result{{ results.length !== 1 ? 's' : '' }}</span>
    </div>
    <div class="results-table-wrapper">
      <table class="results-table">
        <thead>
          <tr>
            <th @click="toggleSort('location')">Location</th>
            <th @click="toggleSort('buy')">Buy {{ unitLabel }}</th>
            <th @click="toggleSort('rent')">Rent {{ unitLabel }}</th>
            <th @click="toggleSort('ratio')">Ratio</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in sorted" :key="locationName(r)">
            <td>{{ locationName(r) }}</td>
            <td class="val-buy">{{ formatValue(r.avg_buy_price_per_sqft) }}</td>
            <td class="val-rent">{{ formatValue(r.avg_rent_per_sqft) }}</td>
            <td class="val-ratio">{{ formatRatio(r.rent_to_price_ratio) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.results-container {
  max-width: 700px;
  margin: 0 auto 16px;
  padding: 0 24px;
}

.results-header {
  margin-bottom: 8px;
}

.results-table-wrapper {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  overflow: hidden;
}

.results-table {
  width: 100%;
  border-collapse: collapse;
}

.results-table th {
  padding: 10px 16px;
  font-size: 11px;
  text-transform: uppercase;
  color: var(--text-secondary);
  text-align: left;
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  user-select: none;
}

.results-table th:hover {
  color: var(--text-primary);
}

.results-table td {
  padding: 10px 16px;
  font-size: 13px;
  border-top: 1px solid var(--border-subtle);
}

.results-table tr:first-child td {
  border-top: none;
}

.val-buy { color: var(--color-buy); }
.val-rent { color: var(--color-rent); }
.val-ratio { color: var(--color-ratio); }
</style>
