import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchPreferences, updatePreferences, resetPreferences } from '../api/client'

export const usePrefsStore = defineStore('prefs', () => {
  const data = ref({ liked_tags: {}, disliked_tags: [] })
  const loading = ref(false)

  const categories = [
    { key: 'color_tone', label: '色调' },
    { key: 'lighting', label: '光线' },
    { key: 'style', label: '风格' },
    { key: 'mood', label: '氛围' },
    { key: 'composition', label: '构图' },
    { key: 'quality', label: '质量' },
  ]

  async function load() {
    loading.value = true
    try { data.value = await fetchPreferences() } catch (e) { console.error(e) }
    finally { loading.value = false }
  }

  async function addTags(category, tags) {
    data.value = await updatePreferences(category, tags)
  }

  async function reset() {
    data.value = await resetPreferences()
  }

  return { data, loading, categories, load, addTags, reset }
})
