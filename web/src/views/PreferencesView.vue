<template>
  <div class="prefs-view">
    <h2>用户偏好管理</h2>
    <div class="prefs-grid">
      <div v-for="cat in store.categories" :key="cat.key" class="pref-card">
        <h3>{{ cat.label }}</h3>
        <div class="tags">
          <span v-for="tag in getTags(cat.key)" :key="tag" class="tag">
            {{ store.getDisplayLabel(tag) }}
            <button class="tag-remove" @click="removeTag(cat.key, tag)">×</button>
          </span>
          <span v-if="!getTags(cat.key).length" class="empty-tag">暂无偏好</span>
        </div>
        <div class="add-tag">
          <input v-model="newTag[cat.key]" type="text" placeholder="添加标签..." @keyup.enter="addTag(cat.key)" />
          <button @click="addTag(cat.key)">+</button>
        </div>
      </div>
    </div>

    <!-- 不喜欢的标签 -->
    <div class="dislike-section" v-if="dislikedTags.length">
      <h3>👎 不喜欢</h3>
      <div class="tags">
        <span v-for="tag in dislikedTags" :key="tag" class="tag dislike-tag">
          {{ store.getDisplayLabel(tag) }}
          <button class="tag-remove" @click="removeDisliked(tag)">×</button>
        </span>
      </div>
    </div>
    <div class="add-dislike">
      <input v-model="newDislike" type="text" placeholder="添加不喜欢的标签..." @keyup.enter="addDisliked" />
      <button @click="addDisliked">+</button>
    </div>

    <button class="danger" @click="handleReset" style="margin-top:16px;">🔄 重置所有偏好</button>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, computed } from 'vue'
import { usePrefsStore } from '../stores/prefsStore'

const store = usePrefsStore()
const newTag = reactive({})

function getTags(catKey) {
  return store.data?.liked_tags?.[catKey] || []
}

async function addTag(catKey) {
  const t = (newTag[catKey] || '').trim()
  if (!t) return
  await store.addTags(catKey, [t])
  newTag[catKey] = ''
}

async function removeTag(catKey, tag) {
  const current = getTags(catKey).filter(t => t !== tag)
  if (store.data?.liked_tags) {
    store.data.liked_tags[catKey] = current
    await store.addTags(catKey, [])
  }
}

const newDislike = ref('')
const dislikedTags = computed(() => store.data?.disliked_tags || [])

async function addDisliked() {
  const t = newDislike.value.trim()
  if (!t) return
  await store.addDisliked([t])
  newDislike.value = ''
}

async function removeDisliked(tag) {
  const current = dislikedTags.value.filter(t => t !== tag)
  if (store.data) {
    store.data.disliked_tags = current
    await store.addDisliked([])
  }
}

async function handleReset() {
  if (confirm('确定要重置所有偏好吗？')) {
    await store.reset()
  }
}

onMounted(() => store.load())
</script>

<style scoped>
.prefs-view { display: flex; flex-direction: column; }
.prefs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; margin-top: 16px; }
.pref-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
.pref-card h3 { margin-bottom: 8px; color: var(--accent); font-size: 14px; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.tag { background: var(--bg-tertiary); padding: 3px 8px; border-radius: 4px; font-size: 12px; display: flex; align-items: center; gap: 4px; }
.tag-remove { background: none; border: none; color: var(--text-secondary); font-size: 14px; padding: 0; cursor: pointer; }
.tag-remove:hover { color: var(--accent-red); }
.empty-tag { font-size: 12px; color: var(--text-secondary); }
.add-tag { display: flex; gap: 4px; }
.add-tag input { padding: 5px 8px; font-size: 12px; }
.add-tag button { padding: 4px 10px; font-size: 14px; }

.dislike-section { margin-top: 20px; padding: 14px; background: var(--bg-secondary); border: 1px solid var(--accent-red); border-radius: var(--radius); }
.dislike-section h3 { color: var(--accent-red); margin-bottom: 8px; font-size: var(--font-base); }
.dislike-tag { background: #3a1a1a; color: #f87171; }
.add-dislike { display: flex; gap: 4px; margin-top: 8px; }
.add-dislike input { padding: 5px 8px; font-size: 12px; }
.add-dislike button { padding: 4px 10px; font-size: 14px; }
</style>
