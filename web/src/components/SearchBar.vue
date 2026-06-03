<template>
  <div class="search-bar">
    <input v-model="query" type="text" placeholder="🔍 搜索提示词或描述..." @keyup.enter="search" />
    <button @click="search">搜索</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
const emit = defineEmits(['search'])
const query = ref('')
function search() { emit('search', query.value) }
</script>

<style scoped>
.search-bar { display: flex; gap: 8px; }
.search-bar input { flex: 1; }
.search-bar button { white-space: nowrap; }
</style>
