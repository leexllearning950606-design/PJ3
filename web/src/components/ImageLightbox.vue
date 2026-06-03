<template>
  <Teleport to="body">
    <div v-if="visible" class="lightbox" @click="close">
      <img :src="src" @click.stop />
    </div>
  </Teleport>
</template>

<script setup>
defineProps({ visible: Boolean, src: String })
const emit = defineEmits(['close'])
function close() { emit('close') }
</script>

<style scoped>
.lightbox {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%;
  background: rgba(0,0,0,0.9); display: flex; align-items: center; justify-content: center;
  z-index: 9999; cursor: zoom-out;
}
.lightbox img { max-width: 90%; max-height: 90%; object-fit: contain; }
</style>
