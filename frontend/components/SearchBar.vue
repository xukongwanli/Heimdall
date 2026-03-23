<script setup lang="ts">
const emit = defineEmits<{
  search: [query: string]
}>()

const input = ref('')

function onInput(e: Event) {
  const value = (e.target as HTMLInputElement).value
  input.value = value
  emit('search', value)
}
</script>

<template>
  <div class="search-section">
    <div class="search-tagline label">Global Real Estate Intelligence</div>
    <div class="search-wrapper">
      <div class="search-box">
        <span class="search-icon">&#128269;</span>
        <input
          type="text"
          placeholder="Search city, state, or ZIP code..."
          :value="input"
          @input="onInput"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-section {
  padding: 40px 24px 24px;
  text-align: center;
}

.search-tagline {
  margin-bottom: 12px;
  letter-spacing: 3px;
}

.search-wrapper {
  max-width: 600px;
  margin: 0 auto;
}

.search-box {
  display: flex;
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border-interactive);
  border-radius: 8px;
  overflow: hidden;
}

.search-icon {
  padding: 12px 16px;
  color: var(--text-muted);
}

.search-box input {
  flex: 1;
  padding: 12px 0;
  font-size: 13px;
}

.search-box input::placeholder {
  color: var(--text-muted);
}
</style>
