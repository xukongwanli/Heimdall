<script setup lang="ts">
const { currentMetric, metrics, loading: metricsLoading, metricLabel, switchMetric, switchLevel, fetchMetrics } = useMetrics()
const { results, loading: searchLoading, search } = useSearch()

const mapBounds = ref({ min: 0, max: 0 })

onMounted(() => {
  fetchMetrics('rent_to_price_ratio', 'state')
})

function onMetricChange(metric: string) {
  switchMetric(metric as any)
}

function onBoundsChange(bounds: { min: number; max: number }) {
  mapBounds.value = bounds
}

function onLevelChange(level: 'state' | 'county') {
  switchLevel(level)
}
</script>

<template>
  <div class="page">
    <NavBar />

    <SearchBar @search="search" />

    <ResultsTable
      :results="results"
      :loading="searchLoading"
    />

    <section class="map-section">
      <div class="map-header">
        <span class="label">Choropleth Map</span>
        <MetricToggle
          :active="currentMetric"
          @change="onMetricChange"
        />
      </div>

      <div class="map-wrapper">
        <ClientOnly>
          <ChoroplethMap
            :metrics="metrics"
            :metric-label="metricLabel"
            @bounds-change="onBoundsChange"
            @level-change="onLevelChange"
          />
        </ClientOnly>
        <MapLegend
          :label="metricLabel"
          :min="mapBounds.min"
          :max="mapBounds.max"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
}

.map-section {
  padding: 12px 24px 24px;
}

.map-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.map-wrapper {
  position: relative;
}
</style>
