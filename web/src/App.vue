<template>
  <TheNav />
  <main class="main-content">
    <RouterView />
  </main>
  <TheFooter />
</template>

<script setup>
import TheNav from './components/TheNav.vue'
import TheFooter from './components/TheFooter.vue'
</script>

<style scoped>
.main-content {
  flex: 1; min-height: 0;
  padding: 14px 20px;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
  overflow: hidden;
}
</style>
