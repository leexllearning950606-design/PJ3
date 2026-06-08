<template>
  <div class="card" @click="$emit('click')">
    <div class="card-img">
      <img v-if="imageUrl" :src="imageUrl" :alt="userInput" />
      <div v-else class="no-img">📷</div>
      <button class="delete-btn" @click.stop="$emit('delete')" title="删除">✕</button>
    </div>
    <div class="card-body">
      <div class="card-date">{{ date }}</div>
      <div class="card-text">{{ userInput || '(无描述)' }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  imageUrl: String, userInput: String, date: String,
})
defineEmits(['click', 'delete'])
</script>

<style scoped>
.card {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden; cursor: pointer;
  transition: border-color 0.15s; position: relative;
}
.card:hover { border-color: var(--accent); }
.card-img { aspect-ratio: 1; overflow: hidden; background: var(--bg-primary); display: flex; align-items: center; justify-content: center; position: relative; }
.card-img img { width: 100%; height: 100%; object-fit: cover; }
.no-img { font-size: 32px; color: var(--text-secondary); }
.delete-btn {
  position: absolute; top: 6px; right: 6px;
  width: 24px; height: 24px; padding: 0;
  border: none; border-radius: 50%;
  background: rgba(0,0,0,0.6); color: #fff;
  font-size: 13px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  opacity: 0; transition: opacity 0.15s;
}
.card:hover .delete-btn { opacity: 1; }
.delete-btn:hover { background: var(--accent-red); }
.card-body { padding: 10px; }
.card-date { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.card-text { font-size: 12px; color: var(--text-primary); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
