<template>
  <div class="progress-panel">
    <div class="label">生成流水线</div>
    <div class="pipeline">
      <div
        v-for="(node, i) in nodes"
        :key="node.name"
        class="pipe-node"
        :class="node.status"
      >
        <div class="pipe-dot">
          <span v-if="node.status === 'done'">✓</span>
          <span v-else-if="node.status === 'running'">●</span>
          <span v-else>○</span>
        </div>
        <div class="pipe-body">
          <div class="pipe-name">{{ node.name }}</div>
          <div class="pipe-status">{{ statusText(node.status) }}</div>
        </div>
        <div v-if="i < nodes.length - 1" class="pipe-line" :class="lineClass(node, nodes[i + 1])"></div>
      </div>
    </div>
    <div class="pipeline-bar">
      <div class="pipeline-bar-fill" :style="{ width: progress + '%' }"></div>
    </div>
    <div v-if="expandedPreview" class="preview-box">
      <div class="label">预览</div>
      <p class="preview-text">{{ expandedPreview }}</p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  nodes: Array,
  progress: Number,
  expandedPreview: String,
})

function statusText(s) {
  if (s === 'done') return '完成'
  if (s === 'running') return '处理中...'
  return '等待中'
}

function lineClass(current, next) {
  if (current.status === 'done') return 'active'
  return ''
}
</script>

<style scoped>
.progress-panel {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px;
  flex: 0 0 250px; display: flex; flex-direction: column;
  overflow: hidden;
}
.label { font-size: 11px; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 10px; letter-spacing: 0.5px; }

.pipeline { flex-shrink: 0; position: relative; }
.pipe-node { display: flex; align-items: flex-start; gap: 10px; position: relative; padding-bottom: 18px; }
.pipe-node:last-child { padding-bottom: 0; }

.pipe-dot {
  width: 22px; height: 22px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700;
  border: 2px solid var(--border);
  color: var(--text-secondary);
  background: var(--bg-primary);
  transition: all 0.3s;
  position: relative; z-index: 1;
}
.pipe-node.running .pipe-dot {
  border-color: var(--accent); color: var(--accent); background: #2a1f0e;
  animation: pulse 1s ease-in-out infinite;
}
.pipe-node.done .pipe-dot {
  border-color: var(--accent-green); color: var(--accent-green); background: #0e2a1a;
}

.pipe-line {
  position: absolute; left: 10px; top: 24px; bottom: 2px;
  width: 2px; background: var(--border); z-index: 0;
  transition: background 0.3s;
}
.pipe-line.active { background: var(--accent-green); }

.pipe-body { flex: 1; min-width: 0; }
.pipe-name { font-size: var(--font-sm); font-weight: 500; line-height: 1.3; }
.pipe-status { font-size: 11px; color: var(--text-secondary); margin-top: 1px; }
.pipe-node.running .pipe-name { color: var(--accent); }
.pipe-node.done .pipe-name { color: var(--accent-green); }
.pipe-node.running .pipe-status { color: var(--accent); }

.pipeline-bar {
  margin: 10px 0; height: 4px; background: var(--bg-tertiary);
  border-radius: 2px; overflow: hidden; flex-shrink: 0;
}
.pipeline-bar-fill {
  height: 100%; border-radius: 2px;
  background: linear-gradient(90deg, var(--accent), var(--accent-green));
  transition: width 0.4s;
}

.preview-box { flex: 1; overflow: hidden; padding: 10px; background: var(--bg-primary); border-radius: 4px; min-height: 0; }
.preview-text { font-size: var(--font-sm); color: var(--text-secondary); line-height: 1.6; overflow-y: auto; max-height: 100%; }

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(249, 174, 88, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(249, 174, 88, 0); }
}
</style>
