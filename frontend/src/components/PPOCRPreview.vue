<template>
  <div style="height: 100%; display: flex; flex-direction: column;">
    <!-- 工具栏 -->
    <div style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center;" v-if="pages.length">
      <span style="font-size:12px; color:#909399;">{{ currentPage }}/{{ pages.length }} 页</span>
      <el-slider v-model="zoom" :min="20" :max="200" style="width: 120px;" size="small" />
      <span style="font-size:12px; color:#909399;">{{ zoom }}%</span>
    </div>

    <!-- 左右并排双面板：左原图 | 右文字层 -->
    <div style="flex:1; display:flex; gap:4px; overflow:hidden;"
         @scroll.passive="syncScroll">
      <!-- 左：纯净原图 -->
      <div ref="imgPanel" style="flex:1; overflow:auto; display:flex; justify-content:center; background:#f5f5f5; border-radius:4px;">
        <div v-for="(page, pi) in pages" :key="'img'+pi" v-show="pi + 1 === currentPage"
             :style="panelStyle(page)">
          <img :src="'data:image/jpeg;base64,' + page.image"
               style="display:block; width:100%; height:auto;" />
        </div>
      </div>

      <!-- 右：文字层（白底，按坐标定位，文字始终可见） -->
      <div ref="textPanel" style="flex:1; overflow:auto; display:flex; justify-content:center; background:#fff; border-radius:4px;">
        <div v-for="(page, pi) in pages" :key="'txt'+pi" v-show="pi + 1 === currentPage"
             style="position:relative;"
             :style="panelStyle(page)">
          <span v-for="(item, idx) in page.lines" :key="idx"
                :style="lineStyle(page, item)"
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
  ocrData: { type: Array, default: () => [] }
})

const zoom = ref(100)
const currentPage = ref(1)
const imgPanel = ref(null)
const textPanel = ref(null)

// 双向滚动同步
function syncScroll(e) {
  const src = e.target
  const dst = src === imgPanel.value ? textPanel.value : imgPanel.value
  if (!dst) return
  if (src.scrollLeft !== dst.scrollLeft) dst.scrollLeft = src.scrollLeft
  if (src.scrollTop !== dst.scrollTop) dst.scrollTop = src.scrollTop
}

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

function panelStyle(page) {
  const s = zoom.value / 100
  return { width: (page.width * s) + 'px', height: 'auto', flexShrink: 0 }
}

function lineStyle(page, item) {
  const s = zoom.value / 100
  const fontSize = Math.max(8, item.h * s * 0.72)
  return {
    position: 'absolute',
    left: (item.left / page.width * 100) + '%',
    top: (item.top / page.height * 100) + '%',
    width: (item.w / page.width * 100) + '%',
    height: (item.h / page.height * 100) + '%',
    fontSize: fontSize + 'px',
    lineHeight: (item.h * s) + 'px',
    color: '#303133',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'default',
    transition: 'background .15s',
  }
}
</script>

<style scoped>
span:hover {
  background: rgba(64, 158, 255, 0.12) !important;
  z-index: 1;
}
</style>
