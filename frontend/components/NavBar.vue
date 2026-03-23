<script setup lang="ts">
const { unit, toggleUnit, unitLabel } = useUnits()
</script>

<template>
  <nav class="navbar">
    <div class="navbar-logo">HEIMDALL</div>
    <div class="navbar-right">
      <button class="unit-toggle" @click="toggleUnit">
        <span :class="{ active: unit === 'sqft' }">$/sqft</span>
        <span :class="{ active: unit === 'sqm' }">$/m²</span>
      </button>
      <div class="navbar-links">
        <a href="/" class="active">Dashboard</a>
        <a href="#">About</a>
      </div>
    </div>
  </nav>
</template>

<style scoped>
.navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-surface);
}

.navbar-logo {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 3px;
  color: var(--accent);
}

.navbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.unit-toggle {
  display: flex;
  background: var(--bg-page);
  border: 1px solid var(--border-interactive);
  border-radius: 6px;
  overflow: hidden;
  font-size: 11px;
}

.unit-toggle span {
  padding: 5px 10px;
  color: var(--text-secondary);
  transition: background 0.2s, color 0.2s;
}

.unit-toggle span.active {
  background: var(--active);
  color: #fff;
}

.navbar-links {
  display: flex;
  gap: 16px;
  font-size: 13px;
}

.navbar-links a {
  color: var(--text-secondary);
}

.navbar-links a.active {
  color: var(--accent);
}
</style>
