/**
 * Converts pre-aggregated MetricPoint data from the API
 * into a Map keyed by code for choropleth rendering.
 */

export interface MetricPoint {
  level: string
  code: string
  name: string
  lat: number | null
  lng: number | null
  value: number | null
  region: string
  listing_count: number
}

export interface AggregatedMetric {
  key: string
  name: string
  value: number
  totalListings: number
}

export function aggregateByCode(points: MetricPoint[]): Map<string, AggregatedMetric> {
  const result = new Map<string, AggregatedMetric>()

  for (const p of points) {
    if (p.value == null || p.listing_count === 0) continue
    result.set(p.code.toUpperCase(), {
      key: p.code,
      name: p.name,
      value: p.value,
      totalListings: p.listing_count,
    })
  }

  return result
}
