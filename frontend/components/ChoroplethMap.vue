<script setup lang="ts">
import L from 'leaflet'
import { valueToColor, computeBounds } from '~/utils/colorScale'
import { aggregateByCode, type AggregatedMetric, type MetricPoint } from '~/utils/aggregate'

const props = defineProps<{
  metrics: MetricPoint[]
  metricLabel: string
}>()

const emit = defineEmits<{
  boundsChange: [bounds: { min: number; max: number }]
  levelChange: [level: 'state' | 'county']
}>()

const { convert, unitLabel } = useUnits()

const mapContainer = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let stateLayer: L.GeoJSON | null = null
let countyLayer: L.GeoJSON | null = null
let statesGeoJson: any = null
let countiesGeoJson: any = null
let currentZoomLevel: 'state' | 'county' = 'state'

const ZOOM_THRESHOLD = 7
const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'

async function loadGeoData() {
  try {
    const [states, counties] = await Promise.all([
      fetch('/geo/us-states.json').then(r => r.json()).catch(() => null),
      fetch('/geo/us-counties.json').then(r => r.json()).catch(() => null),
    ])
    statesGeoJson = states
    countiesGeoJson = counties
  } catch (e) {
    console.error('Failed to load GeoJSON:', e)
  }
}

function createPopupContent(name: string, data: AggregatedMetric | undefined): string {
  if (!data) {
    return `
      <div class="map-popup">
        <div class="popup-title">${name}</div>
        <div class="popup-body">No data available</div>
      </div>
    `
  }
  return `
    <div class="map-popup">
      <div class="popup-title">${data.name || name}</div>
      <div class="popup-body">
        Value: <span class="popup-value">${data.value.toFixed(4)}</span><br>
        Listings: <span>${data.totalListings.toLocaleString()}</span>
      </div>
    </div>
  `
}

function styleFeature(
  feature: any,
  aggregated: Map<string, AggregatedMetric>,
  keyProp: string,
  bounds: { min: number; max: number },
) {
  const key = feature.properties?.[keyProp]
  const data = key ? aggregated.get(key.toUpperCase?.() ?? key) : undefined

  return {
    fillColor: data ? valueToColor(data.value, bounds.min, bounds.max) : '#161b22',
    fillOpacity: data ? 0.7 : 0.3,
    color: '#30363d',
    weight: 0.8,
  }
}

function addInteraction(layer: L.Layer, feature: any, aggregated: Map<string, AggregatedMetric>, keyProp: string) {
  const key = feature.properties?.[keyProp]
  const name = feature.properties?.name ?? feature.properties?.NAME ?? key ?? 'Unknown'
  const data = key ? aggregated.get(key.toUpperCase?.() ?? key) : undefined

  layer.on('mouseover', (e: any) => {
    e.target.setStyle({ weight: 2, color: '#58a6ff' })
    e.target.bringToFront()
  })

  layer.on('mouseout', (e: any) => {
    e.target.setStyle({ weight: 0.8, color: '#30363d' })
  })

  layer.bindPopup(createPopupContent(name, data))
}

function renderStateLayer() {
  if (!map || !statesGeoJson) return

  const aggregated = aggregateByCode(props.metrics)
  const values = Array.from(aggregated.values()).map(a => a.value)
  const bounds = computeBounds(values)
  emit('boundsChange', bounds)

  if (stateLayer) {
    map.removeLayer(stateLayer)
  }

  stateLayer = L.geoJSON(statesGeoJson, {
    style: (feature) => styleFeature(feature, aggregated, 'STUSPS', bounds),
    onEachFeature: (feature, layer) => addInteraction(layer, feature, aggregated, 'STUSPS'),
  }).addTo(map)
}

function renderCountyLayer() {
  if (!map || !countiesGeoJson) return

  const aggregated = aggregateByCode(props.metrics)
  const values = Array.from(aggregated.values()).map(a => a.value)
  const bounds = computeBounds(values)
  emit('boundsChange', bounds)

  if (countyLayer) {
    map.removeLayer(countyLayer)
  }

  countyLayer = L.geoJSON(countiesGeoJson, {
    style: (feature) => styleFeature(feature, aggregated, 'GEOID', bounds),
    onEachFeature: (feature, layer) => addInteraction(layer, feature, aggregated, 'GEOID'),
  }).addTo(map)
}

function updateLayers() {
  if (!map) return
  const zoom = map.getZoom()
  const newLevel = zoom < ZOOM_THRESHOLD ? 'state' : 'county'

  if (newLevel !== currentZoomLevel) {
    currentZoomLevel = newLevel
    emit('levelChange', newLevel)
    return // Parent will fetch new data, which triggers the metrics watcher
  }

  if (zoom < ZOOM_THRESHOLD) {
    if (countyLayer) {
      map.removeLayer(countyLayer)
      countyLayer = null
    }
    renderStateLayer()
  } else {
    if (stateLayer) {
      map.removeLayer(stateLayer)
      stateLayer = null
    }
    renderCountyLayer()
  }
}

onMounted(async () => {
  if (!mapContainer.value) return

  await loadGeoData()

  map = L.map(mapContainer.value, {
    center: [39.8, -98.5],
    zoom: 4,
    zoomControl: false,
    attributionControl: false,
  })

  L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION }).addTo(map)

  L.control.zoom({ position: 'topright' }).addTo(map)
  L.control.attribution({ position: 'bottomright' }).addTo(map)

  map.on('zoomend', updateLayers)

  updateLayers()
})

watch(() => props.metrics, () => {
  if (!map) return
  const zoom = map.getZoom()
  if (zoom < ZOOM_THRESHOLD) {
    if (countyLayer) { map.removeLayer(countyLayer); countyLayer = null }
    renderStateLayer()
  } else {
    if (stateLayer) { map.removeLayer(stateLayer); stateLayer = null }
    renderCountyLayer()
  }
}, { deep: true })

onUnmounted(() => {
  if (map) {
    map.remove()
    map = null
  }
})
</script>

<template>
  <div class="choropleth-container">
    <div ref="mapContainer" class="map"></div>
  </div>
</template>

<style scoped>
.choropleth-container {
  position: relative;
  width: 100%;
}

.map {
  width: 100%;
  height: 500px;
  background: var(--bg-page);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  overflow: hidden;
}
</style>

<style>
/* Popup styles (global because Leaflet injects popups outside component scope) */
.leaflet-popup-content-wrapper {
  background: var(--bg-surface, #161b22) !important;
  border: 1px solid var(--accent, #58a6ff) !important;
  border-radius: 6px !important;
  color: var(--text-primary, #c9d1d9) !important;
  font-family: var(--font-mono, monospace) !important;
}

.leaflet-popup-tip {
  background: var(--bg-surface, #161b22) !important;
  border: 1px solid var(--accent, #58a6ff) !important;
}

.map-popup .popup-title {
  font-size: 12px;
  color: #58a6ff;
  font-weight: 600;
  margin-bottom: 4px;
}

.map-popup .popup-body {
  font-size: 10px;
  color: #8b949e;
  line-height: 1.7;
}

.map-popup .popup-value {
  color: #ffa657;
}
</style>
