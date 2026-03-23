export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const query = getQuery(event)

  if (!query.q) {
    throw createError({ statusCode: 400, statusMessage: 'Missing query parameter: q' })
  }

  const params = new URLSearchParams({ q: String(query.q) })
  const url = `${config.apiBase}/api/search?${params.toString()}`
  return await $fetch(url)
})
