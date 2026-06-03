<template>
  <Teleport to="body">
    <div v-if="visible" class="lightbox" @wheel.prevent="onWheel" @mousedown="onDragStart" @mousemove="onDragMove" @mouseup="onDragEnd" @dblclick="resetZoom" @click="close">
      <img :src="src" @click.stop
        :style="{ transform: `translate(${panX}px, ${panY}px) scale(${scale})` }" />
      <div class="zoom-hint" v-if="scale > 1">{{ Math.round(scale * 100) }}%</div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ visible: Boolean, src: String })
const emit = defineEmits(['close'])

const scale = ref(1)
const panX = ref(0)
const panY = ref(0)
const dragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const panStartX = ref(0)
const panStartY = ref(0)

function close() {
  resetZoom()
  emit('close')
}

function onWheel(e) {
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  scale.value = Math.max(0.5, Math.min(5, scale.value + delta))
}

function onDragStart(e) {
  if (scale.value <= 1) return
  e.preventDefault()
  dragging.value = true
  dragStartX.value = e.clientX
  dragStartY.value = e.clientY
  panStartX.value = panX.value
  panStartY.value = panY.value
}

function onDragMove(e) {
  if (!dragging.value) return
  panX.value = panStartX.value + (e.clientX - dragStartX.value)
  panY.value = panStartY.value + (e.clientY - dragStartY.value)
}

function onDragEnd() {
  dragging.value = false
}

function resetZoom() {
  scale.value = 1
  panX.value = 0
  panY.value = 0
}
</script>

<style scoped>
.lightbox {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.9); display: flex; align-items: center; justify-content: center;
  z-index: 9999; cursor: zoom-out; user-select: none;
}
.lightbox img {
  max-width: 90%; max-height: 90%; object-fit: contain;
  transition: transform 0.1s ease;
  cursor: grab;
}
.zoom-hint {
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  background: rgba(0,0,0,0.7); color: #fff; padding: 4px 12px;
  border-radius: 4px; font-size: 13px;
}
</style>
