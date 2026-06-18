<template>
  <div style="height: 100%; display: flex; flex-direction: column;">
    <!-- 工具栏：缩放控件 -->
    <div style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center;" v-if="pages.length">
      <span style="font-size:12px; color:#909399;">{{ currentPage }}/{{ pages.length }} 页</span>
      <el-slider v-model="zoom" :min="20" :max="200" style="width: 150px;" size="small" />
      <span style="font-size:12px; color:#909399;">{{ zoom }}%</span>
    </div>

    <!-- 可视化面板 -->
    <div style="flex:1; overflow:auto; background:#f0f0f0; border-radius:4px; display:flex; justify-content:center;"
         ref="scrollContainer">
      <div v-for="(page, pi) in pages" :key="pi" v-show="pi + 1 === currentPage"
           style="position:relative; display:inline-block; box-shadow: 0 2px 8px rgba(0,0,0,.15);"
           :style="pageStyle(page)">
        <!-- 原图 -->
        <img :src="'data:image/jpeg;base64,' + page.image" style="display:block; width:100%; height:auto;" />
        <!-- 文字层（绝对定位） -->
        <div style="position:absolute; top:0; left:0; width:100%; height:100%;">
          <span v-for="(item, idx) in page.lines" :key="idx"
                :style="lineStyle(item)"
                :title="item.text + ' (' + Math.round(item.score * 100) + '%)'">
            {{ item.text }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  ocrData: { type: Array, default: () => [] }  // [{ dt_polys, rec_texts, rec_scores, ocrImage, width, height }]
})

const zoom = ref(100)
const currentPage = ref(1)

// 解析数据：每页转为 { image, lines: [{text, poly, score, left, top, w, h}] }
const pages = computed(() => {
  return props.ocrData.map(page => {
    const texts = page.rec_texts || []
    const polys = page.dt_polys || []
    const scores = page.rec_scores || []
    const lines = []
    for (let i = 0; i < Math.min(texts.length, polys.length); i++) {
      const p = polys[i]
      const xs = p.flatMap(([x]) => [x])
      const ys = p.flatMap(([, y]) => [y])
      const left = Math.min(...xs)
      const top = Math.min(...ys)
      const w = Math.max(...xs) - left
      const h = Math.max(...ys) - top
      if (w > 0 && h > 0) {
        lines.push({ text: texts[i] || '', poly: p, score: scores[i] ?? 1, left, top, w, h })
      }
    }
    return {
      image: page.ocrImage || '',
      width: page.width || 800,
      height: page.height || 600,
      lines
    }
  }).filter(p => p.image || p.lines.length)
})

function pageStyle(page) {
  const s = zoom.value / 100
  return { width: (page.width * s) + 'px', height: 'auto' }
}

function lineStyle(item) {
  if (!pages.value.length) return {}
  const page = pages.value[currentPage.value - 1] || pages.value[0]
  const s = zoom.value / 100
  // 文字框相对于原图的比例，映射到缩放后容器
  const leftPct = item.left / page.width * 100
  const topPct = item.top / page.height * 100
  const wPct = item.w / page.width * 100
  const hPct = item.h / page.height * 100
  // 字号 = 文字框高度 * 缩放 * 0.75（中文略小于框高）
  const fontSize = Math.max(6, item.h * s * 0.75)
  return {
    position: 'absolute',
    left: leftPct + '%',
    top: topPct + '%',
    width: wPct + '%',
    height: hPct + '%',
    fontSize: fontSize + 'px',
    lineHeight: item.h * s + 'px',
    color: 'transparent',
    background: 'transparent',
    cursor: 'default',
    whiteSpace: 'nowrap',
  }
}
</script>

<style scoped>
/* hover 时显示文字 */
span:hover {
  color: inherit !important;
  background: rgba(255, 255, 200, 0.85) !important;
}
</style>
