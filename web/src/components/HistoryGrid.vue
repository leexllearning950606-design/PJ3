<template>
  <div class="history-grid">
    <HistoryCard
      v-for="task in tasks" :key="task.id"
      :imageUrl="task.final_image_url"
      :prompt="task.sdxl_prompt"
      :userInput="task.user_input"
      :date="formatDate(task.created_at)"
      @click="$emit('click', task.id)"
    />
  </div>
</template>

<script setup>
import HistoryCard from './HistoryCard.vue'
defineProps({ tasks: Array })
defineEmits(['click'])

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' })
}
</script>

<style scoped>
.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
</style>
