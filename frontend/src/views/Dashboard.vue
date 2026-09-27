<template>
  <div>
    <div class="greet card">
      <div class="greet-left">
        <div class="greet-hi">{{ greeting }} <span class="greet-emoji">👋</span></div>
        <div class="greet-date mono">{{ today }}</div>
        <p class="greet-msg">
          {{ todayStatsText }}
        </p>
      </div>
      <div class="greet-right">
        <button class="punch" :class="{ done: allDone && accounts.length > 0 }" @click="goCheckin">
          <el-icon :size="16" class="punch-icon"><component :is="allDone ? CircleCheckFilled : Aim" /></el-icon>
          <span>{{ allDone && accounts.length > 0 ? '今日已全部完成' : '去签到' }}</span>
        </button>
      </div>
    </div>

    <div class="stats">
      <div class="stat card" v-for="s in statsList" :key="s.label">
        <div class="stat-num mono" :style="{ color: s.color }">{{ s.value }}</div>
        <div class="stat-label">{{ s.label }}</div>
      </div>
    </div>

    <div class="row2">
      <div class="card tl">
        <div class="card-head">
          <span class="card-title">最近签到动态</span>
          <span class="card-sub">最新 8 条执行记录</span>
        </div>

        <div v-if="timeline.length" class="tl-list">
          <div v-for="(item, i) in timeline" :key="i" class="tl-item">
            <div class="tl-time mono">{{ fmtDateTime(item.executed_at) }}</div>
            <div class="tl-rail">
              <span class="tl-dot" :class="item.status === 'success' ? 'ok' : 'bad'"></span>
              <span v-if="i < timeline.length - 1" class="tl-line"></span>
            </div>
            <div class="tl-body">
              <div class="tl-head">
                <span class="tl-name">{{ item.account_name }}</span>
                <span class="tl-tag">{{ platformName(plugins, item.platform) }}</span>
                <span class="tl-src" :class="item.source">{{ item.source === 'auto' ? '定时' : '手动' }}</span>
              </div>
              <div class="tl-msg">{{ item.message || (item.status === 'success' ? '签到成功' : '签到失败') }}</div>
            </div>
          </div>
        </div>
        <div v-else class="empty">
          <p>还没有签到记录</p>
          <p class="empty-sub">添加账户并执行签到（自动定时或手动触发）后，这里会展示执行记录</p>
        </div>
      </div>

      <div class="card week">
        <div class="card-head">
          <span class="card-title">运行概况</span>
          <span class="card-sub">今日与近 7 天</span>
        </div>
        <div class="week-grid">
          <div class="week-cell">
            <div class="week-val mono ok">{{ stats.today_success ?? 0 }}</div>
            <div class="week-label">今日成功</div>
          </div>
          <div class="week-cell">
            <div class="week-val mono bad">{{ stats.today_failed ?? 0 }}</div>
            <div class="week-label">今日失败</div>
          </div>
          <div class="week-cell">
            <div class="week-val mono">{{ stats.week_success ?? 0 }}</div>
            <div class="week-label">近 7 天成功</div>
          </div>
          <div class="week-cell">
            <div class="week-val mono" style="color: var(--brand)">{{ stats.plugin_count ?? 0 }}</div>
            <div class="week-label">已装插件</div>
          </div>
        </div>
        <div class="week-bar">
          <div class="week-bar-in" :style="{ width: enabledRate + '%' }"></div>
          <span class="week-bar-label">账户启用率 {{ enabledRate }}%</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CircleCheckFilled, Aim } from '@element-plus/icons-vue'
import { getStats, getLogs, getPlugins, getAccounts } from '../api'
import { platformName, fmtDateTime, WEEK_NAMES } from '../utils/format'

const router = useRouter()

const stats = ref({})
const timeline = ref([])
const plugins = ref([])
const accounts = ref([])

// 依据当前小时生成问候语
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 18) return '下午好'
  return '晚上好'
})

// 生成「XXXX 年 X 月 X 日 · 周X」格式的今天日期
const today = computed(() => {
  const d = new Date()
  const week = WEEK_NAMES[d.getDay()]
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日 · 周${week}`
})

// 顶部四个统计卡片
const statsList = computed(() => [
  { label: '账户总数', value: stats.value.account_total ?? 0, color: 'var(--brand)' },
  { label: '已启用账户', value: stats.value.account_enabled ?? 0, color: 'var(--ok)' },
  { label: '今日签到成功', value: stats.value.today_success ?? 0, color: 'var(--ok)' },
  { label: '今日签到失败', value: stats.value.today_failed ?? 0, color: 'var(--bad)' },
])

// 账户启用率（0~100），无账户时为 0
const enabledRate = computed(() => {
  const t = stats.value.account_total ?? 0
  if (!t) return 0
  return Math.round(((stats.value.account_enabled ?? 0) / t) * 100)
})

// 「今日已全部完成」判断：有已启用账户，且今日成功数 >= 已启用账户数，且无失败记录
const allDone = computed(() => {
  const enabledCount = stats.value.account_enabled ?? 0
  const successCount = stats.value.today_success ?? 0
  const failedCount = stats.value.today_failed ?? 0
  return enabledCount > 0 && successCount >= enabledCount && failedCount === 0
})

// 展示用的今日执行摘要文案（无账户时给引导提示）
const todayStatsText = computed(() => {
  const s = stats.value
  const all = s.account_total ?? 0
  if (!all) return '还没有账户，先去「账户管理」添加第一个平台的账户吧。'
  return `当前共管理 ${all} 个账户（已启用 ${s.account_enabled ?? 0} 个），今日执行 ${s.today_total ?? 0} 次签到，成功 ${s.today_success ?? 0} 次。`
})

// 平台 key -> 插件展示名；未知平台回退显示 key 本身（复用通用工具）
const goCheckin = () => router.push('/accounts')

// 并行拉取统计、最近日志、插件与账户，任一失败统一提示
const load = async () => {
  try {
    const [s, logsPage, pls, accs] = await Promise.all([
      getStats(),
      getLogs({ page_size: 8 }),
      getPlugins(),
      getAccounts(),
    ])
    stats.value = s
    timeline.value = logsPage.items
    plugins.value = pls
    accounts.value = accs
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.greet {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  background: linear-gradient(135deg, #ffffff 0%, #f4f6ff 100%);
  padding: 24px 26px;
}

.greet-hi {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.wave {
  cursor: default;
}

.greet-emoji {
  font-size: 24px;
  vertical-align: -2px;
}

.greet-date {
  margin-top: 6px;
  font-size: 13px;
  color: var(--ink-3);
}

.greet-msg {
  margin-top: 10px;
  font-size: 13.5px;
  color: var(--ink-2);
  max-width: 520px;
  line-height: 1.6;
}

.punch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 11px 22px;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, #5c79ff 0%, #4f6bff 100%);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(79, 107, 255, 0.32);
  transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}

.punch:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 26px rgba(79, 107, 255, 0.42);
}

.punch.done {
  background: linear-gradient(135deg, #34d399 0%, #10b981 100%);
  box-shadow: 0 8px 20px rgba(16, 185, 129, 0.3);
}

.punch.done:hover {
  box-shadow: 0 12px 26px rgba(16, 185, 129, 0.4);
}

.punch-icon {
  flex: none;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.stat {
  padding: 18px 20px;
}

.stat-num {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
}

.stat-label {
  margin-top: 6px;
  font-size: 13px;
  color: var(--ink-3);
}

.row2 {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 16px;
  margin-top: 16px;
  align-items: start;
}

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 16px;
}

.card-title {
  font-size: 15px;
  font-weight: 700;
}

.card-sub {
  font-size: 12px;
  color: var(--ink-3);
}

.tl-list {
  display: flex;
  flex-direction: column;
}

.tl-item {
  display: grid;
  grid-template-columns: 96px 24px 1fr;
  align-items: start;
  padding: 8px 0;
}

.tl-time {
  font-size: 12px;
  color: var(--ink-3);
  line-height: 20px;
  padding-top: 2px;
  text-align: right;
  white-space: nowrap;
}

.tl-rail {
  position: relative;
  display: flex;
  justify-content: center;
  height: 100%;
  padding-top: 6px;
}

.tl-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  z-index: 1;
}

.tl-dot.ok {
  background: var(--ok);
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18);
}

.tl-dot.bad {
  background: var(--bad);
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.16);
}

.tl-line {
  position: absolute;
  top: 18px;
  bottom: -10px;
  width: 2px;
  background: var(--line);
}

.tl-body {
  min-width: 0;
  padding: 0 0 16px 4px;
  border-bottom: 1px dashed var(--line);
}

.tl-item:last-child .tl-body {
  border-bottom: none;
}

.tl-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tl-name {
  font-size: 14px;
  font-weight: 600;
}

.tl-tag {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
}

.tl-src {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  background: #f1f3f7;
  color: var(--ink-2);
}

.tl-src.auto {
  background: #e8f7f1;
  color: var(--ok);
}

.tl-msg {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty {
  text-align: center;
  padding: 34px 0;
  color: var(--ink-2);
  font-size: 14px;
}

.empty-sub {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.week-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.week-cell {
  text-align: center;
}

.week-val {
  font-size: 24px;
  font-weight: 700;
}

.week-label {
  margin-top: 3px;
  font-size: 12px;
  color: var(--ink-3);
}

.week-bar {
  position: relative;
  margin-top: 18px;
  height: 8px;
  border-radius: 999px;
  background: #eef0f4;
  overflow: hidden;
}

.week-bar-in {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #5c79ff, var(--brand));
  transition: width 0.5s ease;
}

.week-bar-label {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-3);
}

@media (max-width: 1100px) {
  .row2 {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .tl-item {
    grid-template-columns: 80px 20px 1fr;
  }

  .tl-time {
    font-size: 11px;
  }
}
</style>
