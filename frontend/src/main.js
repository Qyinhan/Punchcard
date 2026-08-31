import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import App from './App.vue'
import router from './router'
import { useAuth } from './store/auth'
import './style.css'

/**
 * 前端应用入口：负责创建 Vue 实例、挂载路由以及全局注册 UI 组件库。
 * 挂载前先检查登录状态 / 是否首次部署，路由守卫据此决定进入登录页还是后台。
 */
async function bootstrap() {
  await useAuth().init()
  createApp(App).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
}

bootstrap()
