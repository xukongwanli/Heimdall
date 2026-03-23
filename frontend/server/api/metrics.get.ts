export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const query = getQuery(event)
  const params = new URLSearchParams()

  if (query.metric) params.set('metric', String(query.metric))
  if (query.region) params.set('region', String(query.region))

  const url = `${config.apiBase}/api/metrics?${params.toString()}`
  return await $fetch(url)
})
