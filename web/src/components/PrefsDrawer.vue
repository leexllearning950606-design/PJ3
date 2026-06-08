<template>
  <Teleport to="body">
    <!-- 遮罩 -->
    <Transition name="fade">
      <div v-if="visible" class="drawer-overlay" @click.self="$emit('close')" />
    </Transition>

    <!-- 抽屉 -->
    <Transition name="slide">
      <div v-if="visible" class="prefs-drawer">
        <div class="drawer-header">
          <h2>🎨 审美偏好</h2>
          <span class="drawer-hint">影响生成时的光线、色调、风格等</span>
          <button class="drawer-close" @click="$emit('close')">✕</button>
        </div>

        <div class="drawer-body">
          <!-- 偏好分类 -->
          <div v-for="cat in store.categories" :key="cat.key" class="pref-section">
            <h3 class="section-title">{{ cat.label }}</h3>
            <div class="tag-list">
              <TransitionGroup name="tag-pop">
                <span
                  v-for="tag in getTags(cat.key)"
                  :key="tag"
                  class="tag-chip"
                  :style="{ borderColor: catColor(cat.key) }"
                >
                  <span class="tag-dot" :style="{ background: catColor(cat.key) }"></span>
                  {{ store.getDisplayLabel(tag) }}
                  <button class="tag-x" @click="removeTag(cat.key, tag)">×</button>
                </span>
              </TransitionGroup>
              <span v-if="!getTags(cat.key).length" class="empty-hint">暂无偏好</span>
            </div>
            <div class="add-row">
              <input
                v-model="newTags[cat.key]"
                type="text"
                :placeholder="`添加${cat.label}标签...`"
                @keyup.enter="addTag(cat.key)"
              />
              <button class="add-btn" @click="addTag(cat.key)">+</button>
            </div>
          </div>

          <!-- 不喜欢的标签 -->
          <div class="pref-section dislike-block">
            <h3 class="section-title dislike-title">👎 不喜欢的标签</h3>
            <div class="tag-list">
              <span
                v-for="tag in dislikedTags"
                :key="tag"
                class="tag-chip dislike-chip"
              >
                {{ store.getDisplayLabel(tag) }}
                <button class="tag-x" @click="removeDisliked(tag)">×</button>
              </span>
              <span v-if="!dislikedTags.length" class="empty-hint">暂无</span>
            </div>
            <div class="add-row">
              <input
                v-model="newDislike"
                type="text"
                placeholder="添加不喜欢的标签..."
                @keyup.enter="addDisliked"
              />
              <button class="add-btn dislike-add" @click="addDisliked">+</button>
            </div>
          </div>
        </div>

        <!-- 底部 -->
        <div class="drawer-footer">
          <button class="danger" @click="handleReset">🔄 重置所有偏好</button>
          <span class="footer-status" v-if="saved">✅ 已保存</span>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { usePrefsStore } from '../stores/prefsStore'

const props = defineProps({ visible: Boolean })
defineEmits(['close'])

const store = usePrefsStore()
const newTags = reactive({})
const newDislike = ref('')
const saved = ref(false)

const dislikedTags = computed(() => store.data?.disliked_tags || [])

// 分类颜色映射
const catColors = {
  color_tone: '#f9ae58',
  lighting: '#e8c84c',
  style: '#7ec699',
  mood: '#c084fc',
  composition: '#60a5fa',
  quality: '#f472b6',
}
function catColor(key) { return catColors[key] || '#888' }

function getTags(catKey) {
  return store.data?.liked_tags?.[catKey] || []
}

async function addTag(catKey) {
  const t = (newTags[catKey] || '').trim()
  if (!t) return
  await store.addTags(catKey, [t])
  newTags[catKey] = ''
  flashSaved()
}

async function removeTag(catKey, tag) {
  const current = getTags(catKey).filter(t => t !== tag)
  await store.addTags(catKey, current)
  flashSaved()
}

async function addDisliked() {
  const t = newDislike.value.trim()
  if (!t) return
  await store.addDisliked([t])
  newDislike.value = ''
  flashSaved()
}

async function removeDisliked(tag) {
  const current = dislikedTags.value.filter(t => t !== tag)
  await store.addDisliked(current)
  flashSaved()
}

async function handleReset() {
  if (confirm('确定要重置所有偏好吗？此操作不可撤销。')) {
    await store.reset()
    flashSaved()
  }
}

let _timer = null
function flashSaved() {
  saved.value = true
  clearTimeout(_timer)
  _timer = setTimeout(() => { saved.value = false }, 2000)
}

onMounted(() => store.load())
</script>

<style scoped>
/* ── 遮罩 ── */
.drawer-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(2px);
}

/* ── 抽屉主体 ── */
.prefs-drawer {
  position: fixed; top: 0; right: 0; bottom: 0; z-index: 201;
  width: 420px; max-width: 90vw;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  box-shadow: -8px 0 30px rgba(0, 0, 0, 0.5);
}

/* ── 头部 ── */
.drawer-header {
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border);
  position: relative;
}
.drawer-header h2 { font-size: var(--font-lg); margin-bottom: 4px; }
.drawer-hint { font-size: var(--font-sm); color: var(--text-secondary); }
.drawer-close {
  position: absolute; top: 16px; right: 16px;
  background: none; border: none; color: var(--text-secondary);
  font-size: 20px; width: 36px; height: 36px; display: flex;
  align-items: center; justify-content: center; border-radius: 50%;
  cursor: pointer; transition: all 0.15s;
}
.drawer-close:hover { background: var(--bg-tertiary); color: var(--text-primary); }

/* ── 内容区 ── */
.drawer-body {
  flex: 1; overflow-y: auto;
  padding: 16px 24px;
  display: flex; flex-direction: column; gap: 20px;
}

/* ── 分类区块 ── */
.pref-section { }
.section-title {
  font-size: var(--font-sm);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
  font-weight: 600;
}

/* ── 标签 ── */
.tag-list {
  display: flex; flex-wrap: wrap; gap: 6px;
  min-height: 28px; align-items: center;
}
.tag-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 20px;
  background: var(--bg-tertiary); border: 1px solid var(--border);
  font-size: var(--font-sm); transition: all 0.15s;
}
.tag-chip:hover { background: #2a3040; }
.tag-dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
}
.tag-x {
  background: none; border: none; color: var(--text-secondary);
  font-size: 15px; padding: 0; margin-left: 2px; line-height: 1;
  cursor: pointer; border-radius: 50%; width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
}
.tag-x:hover { color: var(--accent-red); background: rgba(224, 82, 82, 0.15); }
.empty-hint { font-size: var(--font-sm); color: var(--text-secondary); font-style: italic; }

/* ── 添加行 ── */
.add-row { display: flex; gap: 6px; margin-top: 8px; }
.add-row input {
  flex: 1; padding: 6px 10px; font-size: var(--font-sm);
  border-radius: 6px;
}
.add-btn {
  width: 32px; height: 32px; padding: 0;
  font-size: 18px; font-weight: 600;
  border-radius: 6px; display: flex; align-items: center; justify-content: center;
  background: var(--bg-tertiary); border: 1px solid var(--border);
  color: var(--accent-green); cursor: pointer; flex-shrink: 0;
}
.add-btn:hover { background: #2a4030; }

/* ── 不喜欢区块 ── */
.dislike-block {
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.dislike-title { color: var(--accent-red) !important; }
.dislike-chip {
  background: rgba(224, 82, 82, 0.1); border-color: rgba(224, 82, 82, 0.3);
}
.dislike-add { color: var(--accent-red) !important; }
.dislike-add:hover { background: #3a1a1a !important; }

/* ── 底部 ── */
.drawer-footer {
  padding: 14px 24px;
  border-top: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.footer-status {
  font-size: var(--font-sm); color: var(--accent-green);
  animation: fadeIn 0.3s ease;
}

/* ── 过渡动画 ── */
.fade-enter-active, .fade-leave-active { transition: opacity 0.25s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.slide-enter-active { transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.slide-leave-active { transition: transform 0.2s cubic-bezier(0.4, 0, 1, 1); }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }

.tag-pop-enter-active { transition: all 0.2s ease; }
.tag-pop-leave-active { transition: all 0.15s ease; }
.tag-pop-enter-from { opacity: 0; transform: scale(0.8); }
.tag-pop-leave-to { opacity: 0; transform: scale(0.8); }

@keyframes fadeIn {
  from { opacity: 0; } to { opacity: 1; }
}

/* 滚动条 */
.drawer-body::-webkit-scrollbar { width: 4px; }
.drawer-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
</style>
