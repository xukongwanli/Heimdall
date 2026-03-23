// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-05-15',
  devtools: { enabled: true },

  css: [
    '~/assets/styles/main.css',
    'leaflet/dist/leaflet.css',
  ],

  app: {
    head: {
      title: 'Heimdall — Real Estate Intelligence',
      meta: [
        { name: 'theme-color', content: '#0d1117' },
        { name: 'description', content: 'Global real estate data aggregation platform' },
      ],
      link: [
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap',
        },
      ],
    },
  },

  runtimeConfig: {
    apiBase: process.env.API_BASE || 'http://localhost:8000',
  },
})
