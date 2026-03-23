/**
 * Debounced search against /api/search.
 */

export interface SearchResult {
  city: string | null
  region: string
  avg_buy_price_per_sqft: number | null
  avg_rent_per_sqft: number | null
  rent_to_price_ratio: number | null
  listing_count: number
}

export function useSearch() {
  const query = ref('')
  const results = ref<SearchResult[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  async function doSearch(q: string) {
    if (!q.trim()) {
      results.value = []
      return
    }

    loading.value = true
    error.value = null
    try {
      const data = await $fetch<SearchResult[]>('/api/search', {
        params: { q: q.trim() },
      })
      results.value = data
    } catch (e: any) {
      error.value = e.message ?? 'Search failed'
      results.value = []
    } finally {
      loading.value = false
    }
  }

  function search(q: string) {
    query.value = q
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => doSearch(q), 300)
  }

  function clear() {
    query.value = ''
    results.value = []
    if (debounceTimer) clearTimeout(debounceTimer)
  }

  return {
    query: readonly(query),
    results: readonly(results),
    loading: readonly(loading),
    error: readonly(error),
    search,
    clear,
  }
}
