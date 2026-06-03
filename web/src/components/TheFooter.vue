<template>
  <footer class="footer">
    <span class="status-item" :class="{ online: status.comfyui?.online }">
      <span class="dot"></span>
      ComfyUI {{ status.comfyui?.online ? '在线' : '离线' }}
    </span>
    <span class="status-item">
      Blender {{ status.blender ? '✓' : '✗' }}
    </span>
    <span class="status-item">
      {{ status.sampler }} · {{ status.steps }} steps · CFG {{ status.cfg }}
    </span>
  </footer>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchStatus } from '../api/client'

const status = ref({
  comfyui: { online: false, url: '' },
  blender: '', sampler: '', steps: '', cfg: '',
})

onMounted(async () => {
  try { status.value = await fetchStatus() } catch (e) { console.error(e) }
  setInterval(async () => {
    try { status.value = await fetchStatus() } catch (_) {}
  }, 30000)
})
</script>

<style scoped>
.footer {
  display: flex; gap: 20px; align-items: center;
  padding: 8px 24px; background: var(--bg-secondary);
  border-top: 1px solid var(--border); font-size: 12px; color: var(--text-secondary);
}
.status-item { display: flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-red); }
.online .dot { background: var(--accent-green); }
</style>
