<template>
  <div class="generate-view">
    <PromptInput @generate="startGenerate" :disabled="taskStatus === 'running'" />

    <div class="generate-body">
      <ProgressPanel
        :nodes="store.nodes"
        :progress="store.progress"
        :expandedPreview="store.expandedPreview"
      />
      <ResultDisplay
        :imageUrl="store.finalImageUrl"
        @lightbox="showLightbox = $event"
      />
    </div>

    <InteractiveMenu
      :visible="taskStatus === 'waiting_user'"
      :disabled="taskStatus === 'running'"
      @select="handleInteract"
      @done="handleDone"
    />

    <!-- 交互描述输入弹窗 -->
    <div v-if="showDescInput" class="modal-overlay" @click.self="showDescInput = false">
      <div class="modal-box">
        <h3>{{ currentActionLabel }}</h3>
        <input
          v-model="descText"
          type="text"
          :placeholder="descPlaceholder"
          @keyup.enter="submitInteract"
          ref="descInput"
        />
        <div class="modal-actions">
          <button @click="showDescInput = false">取消</button>
          <button class="primary" @click="submitInteract" :disabled="!descText.trim()">确定</button>
        </div>
      </div>
    </div>

    <ImageLightbox :visible="!!showLightbox" :src="showLightbox" @close="showLightbox = null" />
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { useTaskStore } from '../stores/taskStore'
import { generate, interact, markDone } from '../api/client'
import { connectSSE } from '../api/sse'
import PromptInput from '../components/PromptInput.vue'
import ProgressPanel from '../components/ProgressPanel.vue'
import ResultDisplay from '../components/ResultDisplay.vue'
import InteractiveMenu from '../components/InteractiveMenu.vue'
import ImageLightbox from '../components/ImageLightbox.vue'

const store = useTaskStore()
const taskStatus = computed(() => store.status)

const showDescInput = ref(false)
const currentAction = ref('')
const descText = ref('')
const descInput = ref(null)
const showLightbox = ref(null)

const actionLabels = {
  lighting: '换光线', scene: '换场景', character: '微调角色',
  pose: '换姿态', style: '换风格',
}
const currentActionLabel = computed(() => actionLabels[currentAction.value] || '')
const descPlaceholder = computed(() => {
  const placeholders = {
    lighting: '例如：黄昏的暖光、金色斜阳...',
    scene: '例如：换成海边、换成咖啡馆...',
    character: '例如：短发、戴眼镜、换白色连衣裙...',
    pose: '例如：站立回头、手托腮、伸手...',
    style: '例如：水彩风格、线稿风格...',
  }
  return placeholders[currentAction.value] || '描述你想要的变化...'
})

async function startGenerate(userInput) {
  store.resetNodes()
  store.status = 'running'
  store.errorMessage = ''

  try {
    const { task_id } = await generate(userInput)
    store.currentTaskId = task_id

    connectSSE(task_id)
      .on('progress', (data) => store.handleProgress(data))
      .on('grid', (data) => {
        store.gridImageUrl = data.grid_url
        store.gridImageUrls = data.image_urls || []
      })
      .on('interactive', (data) => {
        console.log('[DEBUG] interactive event data:', JSON.stringify(data))
        store.status = 'waiting_user'
        store.finalImageUrl = data.image_url
        store.progress = 100
        console.log('[DEBUG] finalImageUrl set to:', store.finalImageUrl)
      })
      .on('complete', () => {
        if (store.status === 'running') store.status = 'done'
      })
      .on('error', (data) => {
        store.status = 'error'
        store.errorMessage = data.message || '未知错误'
      })
  } catch (e) {
    store.status = 'error'
    store.errorMessage = e.message
  }
}

function handleInteract(action) {
  currentAction.value = action
  descText.value = ''
  showDescInput.value = true
  nextTick(() => descInput.value?.focus())
}

async function submitInteract() {
  if (!descText.value.trim()) return
  showDescInput.value = false
  store.status = 'running'

  try {
    await interact(store.currentTaskId, currentAction.value, descText.value.trim())

    // 场景变化需要走完整管线，注册所有事件类型
    if (currentAction.value === 'scene') {
      store.resetNodes()
      connectSSE(store.currentTaskId)
        .on('progress', (data) => store.handleProgress(data))
        .on('grid', (data) => {
          store.gridImageUrl = data.grid_url
          store.gridImageUrls = data.image_urls || []
        })
        .on('interactive', (data) => {
          store.status = 'waiting_user'
          store.finalImageUrl = data.image_url
          store.progress = 100
        })
        .on('error', (data) => {
          store.status = 'error'
          store.errorMessage = data.message || '交互失败'
        })
    } else {
      connectSSE(store.currentTaskId)
        .on('interactive', (data) => {
          store.status = 'waiting_user'
          store.finalImageUrl = data.image_url
        })
        .on('error', (data) => {
          store.status = 'error'
          store.errorMessage = data.message || '交互失败'
        })
    }
  } catch (e) {
    store.status = 'error'
    store.errorMessage = e.message
  }
}

async function handleDone() {
  store.status = 'done'
  try { await markDone(store.currentTaskId) } catch (e) { console.error(e) }
}
</script>

<style scoped>
.generate-view { display: flex; flex-direction: column; gap: 10px; height: 100%; }
.generate-body { display: flex; gap: 16px; flex: 1; min-height: 0; }

.modal-overlay {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal-box {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 12px; padding: 20px; min-width: 360px;
}
.modal-box h3 { margin-bottom: 10px; font-size: var(--font-lg); }
.modal-actions { display: flex; gap: 8px; margin-top: 10px; justify-content: flex-end; }
</style>
