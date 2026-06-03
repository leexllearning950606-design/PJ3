<template>
  <div class="detail-view" v-if="task">
    <button @click="$router.push('/history')" class="back-btn">← 返回画廊</button>
    <div class="detail-layout">
      <div class="detail-image">
        <img :src="task.final_image_url" v-if="task.final_image_url" @click="showLightbox = task.final_image_url" />
        <div v-else class="no-img">暂无图片</div>
      </div>
      <div class="detail-info">
        <h3>原始输入</h3>
        <p>{{ task.user_input }}</p>
        <h3>SDXL 提示词</h3>
        <code>{{ task.sdxl_prompt }}</code>
        <h3>负向提示词</h3>
        <code>{{ task.sdxl_negative_prompt }}</code>
        <h3>参数</h3>
        <pre>{{ JSON.stringify(task.params, null, 2) }}</pre>
        <h3>交互历史</h3>
        <ul v-if="task.interactions?.length">
          <li v-for="(i, idx) in task.interactions" :key="idx">
            {{ i.action }} → {{ i.description }}
          </li>
        </ul>
        <p v-else>无交互记录</p>
        <h3>生成时间</h3>
        <p>{{ task.created_at }}</p>
      </div>
    </div>
    <ImageLightbox :visible="!!showLightbox" :src="showLightbox" @close="showLightbox = null" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { fetchTask } from '../api/client'
import ImageLightbox from '../components/ImageLightbox.vue'

const route = useRoute()
const task = ref(null)
const showLightbox = ref(null)

onMounted(async () => {
  try { task.value = await fetchTask(route.params.id) } catch (e) { console.error(e) }
})
</script>

<style scoped>
.detail-view { display: flex; flex-direction: column; gap: 16px; }
.back-btn { align-self: flex-start; }
.detail-layout { display: flex; gap: 24px; }
.detail-image { flex: 1; }
.detail-image img { max-width: 100%; border-radius: var(--radius); cursor: pointer; }
.detail-info { flex: 1; display: flex; flex-direction: column; gap: 8px; }
.detail-info h3 { font-size: 13px; color: var(--text-secondary); margin-top: 12px; margin-bottom: 2px; }
.detail-info code { font-size: 12px; background: var(--bg-tertiary); padding: 6px 10px; border-radius: 4px; word-break: break-all; display: block; }
.detail-info pre { font-size: 11px; background: var(--bg-tertiary); padding: 8px; border-radius: 4px; overflow-x: auto; }
.no-img { font-size: 32px; color: var(--text-secondary); }
</style>
