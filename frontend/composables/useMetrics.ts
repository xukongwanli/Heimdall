/**
 * Fetches /api/metrics for a given metric name.
 * Caches results per metric to avoid redundant API calls.
 */

import type { MetricPoint } from '~/utils/aggregate'

type MetricName = 'rent_to_price_ratio' | 'avg_buy_price_per_sqft' | 'avg_rent_per_sqft'

const METRIC_LABELS: Record<MetricName, string> = {
  rent_to_price_ratio: 'Rent/Price Ratio',
  avg_buy_price_per_sqft: 'Buy',
  avg_rent_per_sqft: 'Rent',
}

export function useMetrics() {
  const currentMetric = ref<MetricName>('rent_to_price_ratio')
  const metrics = ref<MetricPoint[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const cache = new Map<MetricName, MetricPoint[]>()

  async function fetchMetrics(metric: MetricName) {
    if (cache.has(metric)) {
      metrics.value = cache.get(metric)!
      return
    }

    loading.value = true
    error.value = null
    try {
      const data = await $fetch<MetricPoint[]>('/api/metrics', {
        params: { metric },
      })
      cache.set(metric, data)
      metrics.value = data
    } catch (e: any) {
      error.value = e.message ?? 'Failed to fetch metrics'
      metrics.value = []
    } finally {
      loading.value = false
    }
  }

  async function switchMetric(metric: MetricName) {
    currentMetric.value = metric
    await fetchMetrics(metric)
  }

  const metricLabel = computed(() => METRIC_LABELS[currentMetric.value])

  return {
    currentMetric: readonly(currentMetric),
    metrics: readonly(metrics),
    loading: readonly(loading),
    error: readonly(error),
    metricLabel,
    switchMetric,
    fetchMetrics,
  }
}
