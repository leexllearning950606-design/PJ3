<template>
  <div class="compare-view">
    <h2>多图对比</h2>
    <p class="subtitle">从历史中选择 2-4 张图片并排比较</p>
    <div class="slot-controls">
      <button @click="addSlot" :disabled="slots.length >= 4">+ 添加对比格</button>
      <button @click="removeSlot" :disabled="slots.length <= 2">- 移除对比格</button>
    </div>
    <div class="compare-grid" :class="'cols-' + slots.length">
      <div v-for="(slot, i) in slots" :key="i" class="slot">
        <div v-if="!slot" class="slot-empty" @click="showPickerFor = i">
          + 选择图片
        </div>
        <div v-else class="slot-filled">
          <img :src="slot.final_image_url" />
          <button class="slot-remove" @click="slots[i] = null">×</button>
          <div class="slot-info">{{ slot.sdxl_prompt?.slice(0, 60) }}...</div>
        </div>
      </div>
    </div>

    <div class="picker" v-if="showPickerFor !== null">
      <h3>选择图片添加到第 {{ showPickerFor + 1 }} 格</h3>
      <div class="picker-grid">
        <div
          v-for="task in tasks" :key="task.id"
          class="picker-item"
          @click="selectForSlot(task)"
          :class="{ selected: selectedId === task.id }"
        >
          <img :src="task.final_image_url" v-if="task.final_image_url" />
          <div class="picker-prompt">{{ task.sdxl_prompt?.slice(0, 40) }}</div>
        </div>
      </div>
      <button @click="showPickerFor = null">取消</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchTasks } from '../api/client'

const slots = ref([null, null])
const tasks = ref([])
const showPickerFor = ref(null)
const selectedId = ref(null)

async function loadTasks() {
  try { const r = await fetchTasks('', 1, 50); tasks.value = r.tasks } catch (e) { console.error(e) }
}

function selectForSlot(task) {
  slots.value[showPickerFor.value] = task
  showPickerFor.value = null
}

function addSlot() { if (slots.value.length < 4) slots.value.push(null) }
function removeSlot() { if (slots.value.length > 2) slots.value.pop() }

onMounted(loadTasks)
</script>

<style scoped>
.compare-view { display: flex; flex-direction: column; gap: 16px; }
.subtitle { color: var(--text-secondary); font-size: 14px; }
.slot-controls { display: flex; gap: 8px; }
.compare-grid { display: grid; gap: 12px; }
.compare-grid.cols-2 { grid-template-columns: 1fr 1fr; }
.compare-grid.cols-3 { grid-template-columns: 1fr 1fr 1fr; }
.compare-grid.cols-4 { grid-template-columns: 1fr 1fr 1fr 1fr; }
.slot { aspect-ratio: 1; background: var(--bg-secondary); border: 2px dashed var(--border); border-radius: var(--radius); display: flex; align-items: center; justify-content: center; position: relative; }
.slot-empty { font-size: 18px; color: var(--text-secondary); cursor: pointer; }
.slot-filled { width: 100%; height: 100%; }
.slot-filled img { width: 100%; height: 100%; object-fit: cover; border-radius: var(--radius); }
.slot-remove { position: absolute; top: 4px; right: 4px; background: rgba(0,0,0,0.7); border: none; color: #fff; width: 24px; height: 24px; border-radius: 50%; font-size: 16px; display: flex; align-items: center; justify-content: center; cursor: pointer; }
.slot-info { position: absolute; bottom: 0; left: 0; right: 0; padding: 6px; background: rgba(0,0,0,0.7); font-size: 11px; color: #ddd; border-radius: 0 0 var(--radius) var(--radius); }
.picker { margin-top: 16px; padding: 16px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: var(--radius); }
.picker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; margin: 12px 0; max-height: 300px; overflow-y: auto; }
.picker-item { cursor: pointer; border: 2px solid transparent; border-radius: 4px; overflow: hidden; }
.picker-item.selected { border-color: var(--accent); }
.picker-item img { width: 100%; aspect-ratio: 1; object-fit: cover; }
.picker-prompt { font-size: 10px; padding: 4px; color: var(--text-secondary); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
</style>
