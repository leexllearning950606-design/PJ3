<template>
  <div class="card" @click="$emit('click')">
    <div class="card-img">
      <img v-if="imageUrl" :src="imageUrl" :alt="prompt" />
      <div v-else class="no-img">📷</div>
    </div>
    <div class="card-body">
      <div class="card-date">{{ date }}</div>
      <div class="card-prompt">{{ prompt || userInput }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  imageUrl: String, prompt: String, userInput: String, date: String,
})
defineEmits(['click'])
</script>

<style scoped>
.card {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden; cursor: pointer;
  transition: border-color 0.15s;
}
.card:hover { border-color: var(--accent); }
.card-img { aspect-ratio: 1; overflow: hidden; background: var(--bg-primary); display: flex; align-items: center; justify-content: center; }
.card-img img { width: 100%; height: 100%; object-fit: cover; }
.no-img { font-size: 32px; color: var(--text-secondary); }
.card-body { padding: 10px; }
.card-date { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.card-prompt { font-size: 12px; color: var(--text-primary); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
