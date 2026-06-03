<template>
  <div class="progress-panel">
    <div class="label">生成进度</div>
    <div class="nodes">
      <div
        v-for="node in nodes"
        :key="node.name"
        class="node"
        :class="node.status"
      >
        <span class="node-icon">
          {{ node.status === 'done' ? '✓' : node.status === 'running' ? '◉' : '○' }}
        </span>
        <span class="node-name">{{ node.name }}</span>
      </div>
    </div>
    <div class="progress-bar-track">
      <div class="progress-bar-fill" :style="{ width: progress + '%' }"></div>
    </div>
    <div v-if="expandedPreview" class="preview-box">
      <div class="label" style="margin-bottom:4px;">当前预览</div>
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
</script>

<style scoped>
.progress-panel {
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px;
  flex: 0 0 240px; display: flex; flex-direction: column;
  overflow: hidden;
}
.label { font-size: 11px; text-transform: uppercase; color: var(--text-secondary); margin-bottom: 8px; letter-spacing: 0.5px; }
.nodes { flex-shrink: 0; }
.node { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: var(--font-sm); }
.node.pending { color: var(--text-secondary); }
.node.running { color: var(--accent); }
.node.done { color: var(--accent-green); }
.node-icon { width: 16px; text-align: center; font-size: 13px; }
.progress-bar-track {
  background: var(--bg-tertiary); border-radius: 3px; height: 4px; margin: 8px 0; flex-shrink: 0;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-green));
  border-radius: 3px; transition: width 0.3s;
}
.preview-box { flex: 1; overflow: hidden; padding: 8px; background: var(--bg-primary); border-radius: 4px; min-height: 0; }
.preview-text { font-size: var(--font-sm); color: var(--text-secondary); line-height: 1.5; overflow-y: auto; max-height: 100%; }
</style>
