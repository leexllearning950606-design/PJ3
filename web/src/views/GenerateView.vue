<template>
  <div class="generate-view">
    <div class="top-bar">
      <PromptInput @generate="startGenerate" :disabled="taskStatus === 'running'" />
      <button class="prefs-trigger" @click="showPrefs = true" title="审美偏好">
        🎨 偏好
      </button>
    </div>

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
      @dislike="handleDislike"
      @done="handleDone"
    />

    <!-- 偏好抽屉 -->
    <PrefsDrawer :visible="showPrefs" @close="showPrefs = false" />

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

    <!-- 保存成功提示 -->
    <div v-if="showToast" class="toast">{{ toastMsg }}</div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { useTaskStore } from '../stores/taskStore'
import { generate, interact, markDone, markDislike } from '../api/client'
import { connectSSE } from '../api/sse'
import PromptInput from '../components/PromptInput.vue'
import ProgressPanel from '../components/ProgressPanel.vue'
import ResultDisplay from '../components/ResultDisplay.vue'
import InteractiveMenu from '../components/InteractiveMenu.vue'
import ImageLightbox from '../components/ImageLightbox.vue'
import PrefsDrawer from '../components/PrefsDrawer.vue'

const store = useTaskStore()
const taskStatus = computed(() => store.status)

const showPrefs = ref(false)
const showDescInput = ref(false)
const currentAction = ref('')
const descText = ref('')
const descInput = ref(null)
const showLightbox = ref(null)
const showToast = ref(false)
const toastMsg = ref('')
let _toastTimer = null

function toast(msg, ms = 2500) {
  toastMsg.value = msg
  showToast.value = true
  clearTimeout(_toastTimer)
  _toastTimer = setTimeout(() => { showToast.value = false }, ms)
}

const actionLabels = {
  lighting: '换光线', scene: '换场景', character: '微调角色',
  pose: '换姿态', style: '换风格', dislike: '不喜欢',
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
  if (currentAction.value === 'dislike') return '哪里不满意？光线太刺眼？颜色不对？...'
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

function handleDislike() {
  currentAction.value = 'dislike'
  descText.value = ''
  showDescInput.value = true
  nextTick(() => descInput.value?.focus())
}

async function submitInteract() {
  if (!descText.value.trim()) return
  showDescInput.value = false
  store.status = 'running'

  // 不喜欢：记录偏好 + 重新生成
  if (currentAction.value === 'dislike') {
    try {
      await markDislike(store.currentTaskId, descText.value.trim())
      // 连接 SSE 接收重新生成的图片
      connectSSE(store.currentTaskId)
        .on('progress', (data) => store.handleProgress(data))
        .on('interactive', (data) => {
          store.status = 'waiting_user'
          store.finalImageUrl = data.image_url
          store.progress = 100
        })
        .on('error', (data) => {
          store.status = 'error'
          store.errorMessage = data.message || '重新生成失败'
        })
    } catch (e) {
      store.status = 'error'
      store.errorMessage = e.message
    }
    return
  }

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
  try { await markDone(store.currentTaskId) } catch (e) { console.error(e) }
  store.status = 'done'
  toast('✅ 已保存到历史记录')
  // 延迟回到初始界面
  setTimeout(() => {
    store.resetNodes()
    store.status = 'idle'
    store.currentTaskId = null
    store.gridImageUrl = ''
    store.gridImageUrls = []
  }, 1500)
}
</script>

<style scoped>
.generate-view { display: flex; flex-direction: column; gap: 10px; height: 100%; }
.top-bar { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
.top-bar :deep(.prompt-input) { flex: 1; }
.generate-body { display: flex; gap: 16px; flex: 1; min-height: 0; }

.prefs-trigger {
  white-space: nowrap; font-weight: 500;
  padding: 10px 16px; font-size: var(--font-base);
  border: 1px solid var(--accent); color: var(--accent);
  background: rgba(249, 174, 88, 0.08); border-radius: var(--radius);
  cursor: pointer; transition: all 0.2s; flex-shrink: 0;
}
.prefs-trigger:hover {
  background: rgba(249, 174, 88, 0.18);
  box-shadow: 0 0 12px rgba(249, 174, 88, 0.15);
}

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

.toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: var(--accent-green); color: #fff; padding: 10px 24px;
  border-radius: 8px; font-size: var(--font-base); z-index: 200;
  animation: fadeInUp 0.3s ease;
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateX(-50%) translateY(12px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
</style>
