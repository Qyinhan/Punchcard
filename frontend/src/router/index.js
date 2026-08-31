import { createRouter, createWebHistory } from 'vue-router'

import MainLayout from '../layout/MainLayout.vue'
import { useAuth } from '../store/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '概览' } },
      { path: 'accounts', name: 'accounts', component: () => import('../views/Accounts.vue'), meta: { title: '账户管理' } },
      { path: 'schedules', name: 'schedules', component: () => import('../views/Schedules.vue'), meta: { title: '任务设置' } },
      { path: 'plugins', name: 'plugins', component: () => import('../views/Plugins.vue'), meta: { title: '平台插件' } },
      { path: 'logs', name: 'logs', component: () => import('../views/Logs.vue'), meta: { title: '签到日志' } },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const { user, setupRequired } = useAuth()
  if (to.meta.public) {
    // 已登录访问登录页 → 回首页；未配置系统时 /login 展示首次设置表单
    if (user.value && to.path === '/login') return { path: '/' }
    return true
  }
  if (!user.value) {
    return { path: '/login' }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} - PunchCard` : 'PunchCard'
})

export default router
