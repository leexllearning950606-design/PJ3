<template>
  <TheNav />
  <main class="main-content">
    <RouterView />
  </main>
</template>

<script setup>
import TheNav from './components/TheNav.vue'
</script>

<style scoped>
.main-content {
  flex: 1;
  padding: 20px 24px;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
}
</style>
