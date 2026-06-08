import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useTaskStore = defineStore('task', () => {
  const currentTaskId = ref(null)
  const status = ref('idle')
  const progress = ref(0)
  const nodes = ref([
    { name: '场景扩写', status: 'pending' },
    { name: 'SDXL提示词生成', status: 'pending' },
    { name: 'Blender脚本生成', status: 'pending' },
    { name: '场景渲染', status: 'pending' },
    { name: 'AI 图像生成', status: 'pending' },
  ])
  const finalImageUrl = ref('')
  const gridImageUrl = ref('')
  const gridImageUrls = ref([])
  const expandedPreview = ref('')
  const errorMessage = ref('')

  function resetNodes() {
    nodes.value.forEach(n => n.status = 'pending')
    progress.value = 0
    finalImageUrl.value = ''
    gridImageUrl.value = ''
    gridImageUrls.value = []
    expandedPreview.value = ''
    errorMessage.value = ''
  }

  function setNodeStatus(name, s) {
    const node = nodes.value.find(n => n.name === name)
    if (node) node.status = s
  }

  function handleProgress(data) {
    if (data.status === 'running') {
      setNodeStatus(data.node, 'running')
    } else if (data.status === 'done') {
      setNodeStatus(data.node, 'done')
    }
    if (data.progress) progress.value = data.progress
    if (data.preview) expandedPreview.value = data.preview
  }

  return {
    currentTaskId, status, progress, nodes,
    finalImageUrl, gridImageUrl, gridImageUrls,
    expandedPreview, errorMessage,
    resetNodes, setNodeStatus, handleProgress,
  }
})
