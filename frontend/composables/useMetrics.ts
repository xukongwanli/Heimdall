/**
 * Fetches /api/metrics for a given metric name and geographic level.
 * Caches results per metric+level to avoid redundant API calls.
 */

import type { MetricPoint } from '~/utils/aggregate'

type MetricName = 'rent_to_price_ratio' | 'avg_buy_price_per_sqft' | 'avg_rent_per_sqft'
type GeoLevel = 'state' | 'county' | 'city' | 'zip'

const METRIC_LABELS: Record<MetricName, string> = {
  rent_to_price_ratio: 'Rent/Price Ratio',
  avg_buy_price_per_sqft: 'Buy',
  avg_rent_per_sqft: 'Rent',
}

export function useMetrics() {
  const currentMetric = ref<MetricName>('rent_to_price_ratio')
  const currentLevel = ref<GeoLevel>('state')
  const metrics = ref<MetricPoint[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const cache = new Map<string, MetricPoint[]>()

  async function fetchMetrics(metric: MetricName, level: GeoLevel = 'state') {
    const cacheKey = `${metric}:${level}`
    if (cache.has(cacheKey)) {
      metrics.value = cache.get(cacheKey)!
      currentMetric.value = metric
      currentLevel.value = level
      return
    }

    loading.value = true
    error.value = null
    try {
      const data = await $fetch<MetricPoint[]>('/api/metrics', {
        params: { metric, level },
      })
      cache.set(cacheKey, data)
      metrics.value = data
      currentMetric.value = metric
      currentLevel.value = level
    } catch (e: any) {
      error.value = e.message ?? 'Failed to fetch metrics'
      metrics.value = []
    } finally {
      loading.value = false
    }
  }

  async function switchMetric(metric: MetricName) {
    await fetchMetrics(metric, currentLevel.value)
  }

  async function switchLevel(level: GeoLevel) {
    await fetchMetrics(currentMetric.value, level)
  }

  const metricLabel = computed(() => METRIC_LABELS[currentMetric.value])

  return {
    currentMetric: readonly(currentMetric),
    currentLevel: readonly(currentLevel),
    metrics: readonly(metrics),
    loading: readonly(loading),
    error: readonly(error),
    metricLabel,
    switchMetric,
    switchLevel,
    fetchMetrics,
  }
}
