<template>
  <div class="prompt-input">
    <input
      v-model="text"
      type="text"
      placeholder="描述你想要生成的场景，例如：夕阳下的教室中，一位女孩靠窗发呆"
      @keyup.enter="$emit('generate', text)"
      :disabled="disabled"
    />
    <button
      class="primary"
      @click="$emit('generate', text)"
      :disabled="disabled || !text.trim()"
    >
      🚀 开始生成
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue'
defineProps({ disabled: Boolean })
defineEmits(['generate'])
const text = ref('')
</script>

<style scoped>
.prompt-input {
  display: flex; gap: 10px; align-items: center; flex-shrink: 0;
  padding: 10px 14px; background: var(--bg-secondary);
  border-radius: var(--radius); border: 1px solid var(--border);
}
.prompt-input input { flex: 1; font-size: var(--font-base); }
.prompt-input button {
  white-space: nowrap; font-weight: 600;
  padding: 8px 20px; font-size: var(--font-base);
}
</style>
