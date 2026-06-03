<template>
  <div class="interactive-menu" v-if="visible">
    <span class="menu-label">调整生成：</span>
    <button v-for="opt in options" :key="opt.action"
      @click="$emit('select', opt.action)" :disabled="disabled">
      {{ opt.emoji }} {{ opt.label }}
    </button>
    <button class="primary" @click="$emit('done')" style="margin-left:auto;" :disabled="disabled">
      ✅ 满意保存
    </button>
  </div>
</template>

<script setup>
defineProps({
  visible: Boolean,
  disabled: Boolean,
})
defineEmits(['select', 'done'])

const options = [
  { action: 'lighting', emoji: '☀️', label: '换光线' },
  { action: 'scene', emoji: '🎨', label: '换场景' },
  { action: 'character', emoji: '✏️', label: '微调角色' },
  { action: 'pose', emoji: '🔄', label: '换姿态' },
  { action: 'style', emoji: '🖼️', label: '换风格' },
]
</script>

<style scoped>
.interactive-menu {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap; flex-shrink: 0;
  padding: 12px 16px; background: var(--bg-secondary);
  border: 1px solid var(--border); border-radius: var(--radius);
}
.menu-label { font-size: var(--font-base); color: var(--text-secondary); margin-right: 4px; }
</style>
