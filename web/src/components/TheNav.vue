<template>
  <nav class="nav">
    <div class="nav-brand">🎨 Anime Generator</div>
    <div class="nav-links">
      <RouterLink to="/">生成</RouterLink>
      <RouterLink to="/history">历史</RouterLink>
      <RouterLink to="/preferences">偏好</RouterLink>
      <RouterLink to="/compare">对比</RouterLink>
    </div>
  </nav>
</template>

<script setup>
import { RouterLink } from 'vue-router'
</script>

<style scoped>
.nav {
  display: flex; align-items: center; gap: 24px;
  padding: 12px 24px; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}
.nav-brand { font-weight: 700; font-size: 16px; }
.nav-links { display: flex; gap: 16px; }
.nav-links a { color: var(--text-secondary); font-size: 14px; padding: 4px 8px; border-radius: 4px; }
.nav-links a:hover { color: var(--text-primary); text-decoration: none; }
.nav-links a.router-link-exact-active { color: var(--accent); background: var(--bg-tertiary); }
</style>
