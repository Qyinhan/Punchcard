<template>
  <div class="shell">
    <aside class="side">
      <div class="brand">
        <div class="brand-badge">
          <el-icon :size="20"><Stamp /></el-icon>
        </div>
        <div class="brand-text">
          <span class="brand-name">PunchCard</span>
          <span class="brand-sub">自动签到台</span>
        </div>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in navs"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: $route.path === item.path }"
        >
          <el-icon :size="17"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="side-foot">
        <div class="mono now">{{ now }}</div>
        <div class="date">{{ dateStr }}</div>
      </div>
    </aside>

    <div class="body">
      <header class="topbar">
        <div class="crumbs">
          <span class="crumbs-main">{{ $route.meta.title }}</span>
          <span class="crumbs-sub">PunchCard · 多平台自动签到</span>
        </div>
        <div class="top-status">
          <span class="live"><span class="dot ok"></span>调度运行中</span>
          <span class="user">
            <el-icon :size="15"><User /></el-icon>
            <span>{{ auth.user.value?.username || '' }}</span>
            <el-button link type="danger" size="small" @click="doLogout">退出</el-button>
          </span>
        </div>
      </header>

      <main class="main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Stamp, DataAnalysis, User, Clock, Grid, Document } from '@element-plus/icons-vue'
import { useAuth } from '../store/auth'
import { pad2, WEEK_NAMES } from '../utils/format'

const auth = useAuth()
const router = useRouter()

const doLogout = async () => {
  await auth.logout()
  router.push('/login')
}

const navs = [
  { path: '/dashboard', label: '概览', icon: DataAnalysis },
  { path: '/accounts', label: '账户管理', icon: User },
  { path: '/schedules', label: '任务设置', icon: Clock },
  { path: '/plugins', label: '平台插件', icon: Grid },
  { path: '/logs', label: '签到日志', icon: Document },
]

const now = ref('')
const dateStr = ref('')
let timer = null

// 每秒刷新侧栏时钟（时间 + 中文日期）
const tick = () => {
  const d = new Date()
  now.value = `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
  const week = WEEK_NAMES[d.getDay()]
  dateStr.value = `${d.getFullYear()} / ${pad2(d.getMonth() + 1)} / ${pad2(d.getDate())} 周${week}`
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 1000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.side {
  width: 208px;
  flex: none;
  background: var(--card);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  padding: 20px 14px 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px;
  margin-bottom: 26px;
}

.brand-badge {
  width: 38px;
  height: 38px;
  border-radius: 11px;
  background: linear-gradient(135deg, #5c79ff 0%, #4f6bff 55%, #3d56cc 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 14px rgba(79, 107, 255, 0.35);
}

.brand-name {
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.01em;
  display: block;
  line-height: 1.15;
}

.brand-sub {
  font-size: 11px;
  color: var(--ink-3);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  color: var(--ink-2);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: background 0.15s ease, color 0.15s ease;
}

.nav-item:hover {
  background: #f2f4fb;
  color: var(--ink);
}

.nav-item.active {
  background: var(--brand-soft);
  color: var(--brand);
  font-weight: 600;
}

.side-foot {
  padding: 12px 10px 4px;
  border-top: 1px solid var(--line);
}

.now {
  font-size: 19px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--ink);
}

.date {
  margin-top: 3px;
  font-size: 12px;
  color: var(--ink-3);
}

.body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  height: 58px;
  flex: none;
  background: var(--card);
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
}

.crumbs-main {
  font-size: 15px;
  font-weight: 700;
}

.crumbs-sub {
  margin-left: 10px;
  font-size: 12px;
  color: var(--ink-3);
}

.top-status {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12.5px;
  color: var(--ink-2);
}

.user {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.live {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fafbfd;
}

.live .dot {
  width: 7px;
  height: 7px;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18);
}

.main {
  flex: 1;
  overflow-y: auto;
  padding: 26px 28px 40px;
}
</style>
