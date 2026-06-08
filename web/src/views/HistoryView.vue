<template>
  <div class="history-view">
    <h2>历史画廊</h2>
    <SearchBar @search="handleSearch" />
    <HistoryGrid :tasks="tasks" @click="goDetail" @delete="handleDelete" />
    <div class="pagination" v-if="total > limit">
      <button :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span>{{ page }} / {{ Math.ceil(total / limit) }}</span>
      <button :disabled="page >= Math.ceil(total / limit)" @click="goPage(page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchTasks, deleteTask } from '../api/client'
import SearchBar from '../components/SearchBar.vue'
import HistoryGrid from '../components/HistoryGrid.vue'

const router = useRouter()
const tasks = ref([])
const total = ref(0)
const page = ref(1)
const searchQuery = ref('')
const limit = 20

async function loadTasks() {
  try {
    const result = await fetchTasks(searchQuery.value, page.value, limit)
    tasks.value = result.tasks
    total.value = result.total
  } catch (e) { console.error(e) }
}

function handleSearch(query) {
  searchQuery.value = query
  page.value = 1
  loadTasks()
}

function goPage(p) { page.value = p; loadTasks() }
function goDetail(id) { router.push(`/history/${id}`) }

async function handleDelete(taskId) {
  if (!confirm('确定要删除这条记录吗？')) return
  try {
    await deleteTask(taskId)
    loadTasks()
  } catch (e) { console.error(e) }
}

onMounted(loadTasks)
</script>

<style scoped>
.history-view { display: flex; flex-direction: column; gap: 16px; }
.pagination { display: flex; gap: 12px; align-items: center; justify-content: center; margin-top: 16px; }
</style>
