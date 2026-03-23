/**
 * Global unit preference (sqft or m²).
 * Persists to localStorage. Provides convert() helper.
 */

const SQFT_TO_SQM_FACTOR = 10.764

type Unit = 'sqft' | 'sqm'

const unit = ref<Unit>('sqft')

// Hydrate from localStorage on client
if (import.meta.client) {
  const stored = localStorage.getItem('heimdall-unit')
  if (stored === 'sqm') unit.value = 'sqm'
}

export function useUnits() {
  function toggleUnit() {
    unit.value = unit.value === 'sqft' ? 'sqm' : 'sqft'
    if (import.meta.client) {
      localStorage.setItem('heimdall-unit', unit.value)
    }
  }

  function convert(valuePerSqft: number | null | undefined): number | null {
    if (valuePerSqft == null) return null
    return unit.value === 'sqm'
      ? Math.round(valuePerSqft * SQFT_TO_SQM_FACTOR * 100) / 100
      : Math.round(valuePerSqft * 100) / 100
  }

  const unitLabel = computed(() => unit.value === 'sqft' ? '$/sqft' : '$/m²')

  return { unit: readonly(unit), toggleUnit, convert, unitLabel }
}
