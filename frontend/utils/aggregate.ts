/**
 * Aggregates ZIP-level MetricPoint data to state or county level
 * using listing_count-weighted averages.
 */

export interface MetricPoint {
  postal_code: string
  lat: number | null
  lng: number | null
  value: number | null
  region: string
  listing_count: number
}

export interface AggregatedMetric {
  key: string
  value: number
  totalListings: number
}

export function aggregateByState(points: MetricPoint[]): Map<string, AggregatedMetric> {
  const groups = new Map<string, { weightedSum: number; totalWeight: number }>()

  for (const p of points) {
    if (p.value == null || p.listing_count === 0) continue
    const key = p.region.toUpperCase()
    const existing = groups.get(key) ?? { weightedSum: 0, totalWeight: 0 }
    existing.weightedSum += p.value * p.listing_count
    existing.totalWeight += p.listing_count
    groups.set(key, existing)
  }

  const result = new Map<string, AggregatedMetric>()
  for (const [key, { weightedSum, totalWeight }] of groups) {
    result.set(key, {
      key,
      value: weightedSum / totalWeight,
      totalListings: totalWeight,
    })
  }
  return result
}

export function aggregateByCounty(
  points: MetricPoint[],
  zipToCounty: Record<string, string>,
): Map<string, AggregatedMetric> {
  const groups = new Map<string, { weightedSum: number; totalWeight: number }>()

  for (const p of points) {
    if (p.value == null || p.listing_count === 0) continue
    const fips = zipToCounty[p.postal_code] ?? zipToCounty[p.postal_code.slice(0, 3)]
    if (!fips) continue
    const existing = groups.get(fips) ?? { weightedSum: 0, totalWeight: 0 }
    existing.weightedSum += p.value * p.listing_count
    existing.totalWeight += p.listing_count
    groups.set(fips, existing)
  }

  const result = new Map<string, AggregatedMetric>()
  for (const [key, { weightedSum, totalWeight }] of groups) {
    result.set(key, {
      key,
      value: weightedSum / totalWeight,
      totalListings: totalWeight,
    })
  }
  return result
}
