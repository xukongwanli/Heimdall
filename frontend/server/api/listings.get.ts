export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const query = getQuery(event)
  const params = new URLSearchParams()

  for (const [key, val] of Object.entries(query)) {
    if (val != null) params.set(key, String(val))
  }

  const url = `${config.apiBase}/api/listings?${params.toString()}`
  return await $fetch(url)
})
