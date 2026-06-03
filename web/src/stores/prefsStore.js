import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchPreferences, updatePreferences, resetPreferences } from '../api/client'

// 英文 Danbooru 标签 → 中文显示名映射
const TAG_CN = {
  // 色调
  'warm atmosphere': '暖色调', 'warm color': '暖色', 'warm tone': '暖调',
  'cool atmosphere': '冷色调', 'cool color': '冷色', 'cool tone': '冷调',
  'muted colors': '低饱和色', 'vivid colors': '鲜艳色彩',
  'pastel colors': '粉彩色', 'monochrome': '单色',
  'sepia': '复古棕', 'high saturation': '高饱和',
  'low saturation': '低饱和', 'desaturated': '去饱和',
  // 光线
  'soft lighting': '柔光', 'harsh lighting': '强光',
  'sunlight': '阳光', 'backlighting': '逆光', 'backlight': '逆光',
  'golden hour': '日落暖光', 'sunset': '日落', 'dusk': '黄昏',
  'night': '夜晚', 'moonlight': '月光', 'morning': '清晨',
  'god rays': '丁达尔光', 'lens flare': '镜头光晕',
  'cinematic lighting': '电影感布光', 'dramatic lighting': '戏剧性光影',
  'warm light': '暖光', 'cold light': '冷光',
  'overcast': '阴天', 'cloudy': '多云', 'rainy': '雨天',
  'dappled light': '斑驳光', 'rim lighting': '轮廓光',
  'dim lighting': '暗光', 'bright': '明亮',
  // 风格
  'watercolor': '水彩', 'cel shading': '赛璐珞', 'line art': '线稿',
  'flat color': '平涂', 'painterly': '油画风', 'sketch': '素描',
  'oil painting': '油画', 'ink wash': '水墨', 'gouache': '水粉',
  'thick outlines': '粗线条', 'no lines': '无线条',
  'anime style': '动漫风', 'semi-realistic': '半写实', 'realistic': '写实',
  'minimalist': '极简', 'detailed': '细腻',
  // 氛围
  'peaceful': '平静', 'calm': '安宁', 'serene': '静谧',
  'sad': '悲伤', 'melancholy': '忧郁', 'lonely': '孤独',
  'energetic': '活力', 'dynamic': '动感', 'tense': '紧张',
  'daydreaming': '出神', 'nostalgic': '怀旧', 'romantic': '浪漫',
  'mysterious': '神秘', 'gloomy': '阴郁', 'dark': '黑暗',
  'cheerful': '欢快', 'cozy': '温馨', 'ethereal': '空灵',
  'bittersweet': '苦涩', 'hopeful': '希望',
  // 构图
  'close-up': '特写', 'medium shot': '中景',
  'wide shot': '远景', 'full body': '全身',
  'from above': '俯视', 'from below': '仰视',
  'from side': '侧面', 'facing camera': '正对镜头',
  'looking away': '看向别处', 'looking at viewer': '看向观众',
  'centered': '居中', 'off-center': '偏置',
  'rule of thirds': '三分构图', 'symmetrical': '对称',
  'negative space': '留白', 'depth of field': '景深',
  'blurry background': '虚化背景', 'bokeh': '光斑虚化',
  'portrait': '竖幅', 'landscape': '横幅',
  // 质量
  'highly detailed': '高细节', 'intricate details': '精致细节',
  'simple background': '简单背景', 'detailed background': '详细背景',
  '4k': '4K画质', '8k': '8K画质', 'hd': '高清',
  'sharp focus': '锐利对焦', 'soft focus': '柔焦',
  'clean lines': '干净线条', 'rough': '粗犷',
}

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

  function getDisplayLabel(tag) {
    return TAG_CN[tag] || tag
  }

  function getEnglishTag(label) {
    for (const [en, cn] of Object.entries(TAG_CN)) {
      if (cn === label) return en
    }
    return label
  }

  async function load() {
    loading.value = true
    try { data.value = await fetchPreferences() } catch (e) { console.error(e) }
    finally { loading.value = false }
  }

  async function addTags(category, tags) {
    // 用户输入中文 → 转英文存储
    const eng = tags.map(t => getEnglishTag(t))
    data.value = await updatePreferences(category, eng)
  }

  async function reset() {
    data.value = await resetPreferences()
  }

  return { data, loading, categories, getDisplayLabel, load, addTags, reset }
})
