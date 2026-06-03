<template>
  <div class="result-display" :class="{ empty: !imageUrl }">
    <div v-if="imageUrl" class="image-wrapper">
      <img :src="imageUrl" :alt="alt" @click="$emit('lightbox', imageUrl)" />
      <div class="image-actions">
        <a :href="imageUrl" download>⬇ 下载</a>
        <button @click="$emit('lightbox', imageUrl)">🔍 放大</button>
      </div>
    </div>
    <div v-else class="placeholder">
      <div class="placeholder-icon">🖼️</div>
      <div class="placeholder-text">生成结果将在这里展示</div>
    </div>
  </div>
</template>

<script setup>
import { watch } from 'vue'
const props = defineProps({ imageUrl: String, alt: { type: String, default: '' } })
defineEmits(['lightbox'])
watch(() => props.imageUrl, (val) => {
  console.log('[DEBUG] ResultDisplay imageUrl changed:', val)
})
</script>

<style scoped>
.result-display {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden; position: relative;
  flex: 1; min-height: 0;
}
.result-display.empty { background: var(--bg-primary); }
.image-wrapper {
  width: 100%; height: 100%; position: absolute; top: 0; left: 0;
  display: flex; align-items: center; justify-content: center;
}
.image-wrapper img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 4px; cursor: pointer; }
.placeholder { text-align: center; color: var(--text-secondary); }
.placeholder-icon { font-size: 40px; margin-bottom: 6px; }
.placeholder-text { font-size: var(--font-sm); }
.image-actions {
  position: absolute; bottom: 8px; right: 8px;
  display: flex; gap: 8px;
}
.image-actions a, .image-actions button {
  background: rgba(0,0,0,0.7); color: #fff; font-size: 12px;
  padding: 4px 10px; border-radius: 4px; border: none;
}
.placeholder { text-align: center; color: var(--text-secondary); }
.placeholder-icon { font-size: 48px; margin-bottom: 8px; }
.placeholder-text { font-size: 14px; }
</style>
