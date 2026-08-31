<template>
  <div class="auth-wrap">
    <div class="auth-card card">
      <div class="brand">
        <div class="brand-badge">
          <el-icon :size="22"><Stamp /></el-icon>
        </div>
        <div class="brand-text">
          <span class="brand-name">PunchCard</span>
          <span class="brand-sub">多平台自动签到</span>
        </div>
      </div>

      <h1 class="auth-title">{{ setupRequired ? '初始化系统' : '登录' }}</h1>
      <p v-if="setupRequired" class="auth-desc">
        首次部署：创建管理员账户，之后用它登录后台
      </p>

      <el-form label-position="top" @submit.prevent>
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" autocomplete="username" placeholder="管理员用户名" />
        </el-form-item>
        <el-form-item label="密码" required>
          <el-input v-model="form.password" type="password" show-password
            autocomplete="current-password" :placeholder="setupRequired ? '至少 8 位' : '输入密码'" />
        </el-form-item>
        <el-form-item v-if="setupRequired" label="确认密码" required>
          <el-input v-model="form.confirm" type="password" show-password
            autocomplete="new-password" placeholder="再次输入密码" />
        </el-form-item>
        <el-button type="primary" class="auth-btn" :loading="loading" @click="submit">
          {{ setupRequired ? '创建并进入' : '登录' }}
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Stamp } from '@element-plus/icons-vue'
import { useAuth } from '../store/auth'

const router = useRouter()
const { setupRequired, init, login, setup } = useAuth()

const form = ref({ username: '', password: '', confirm: '' })
const loading = ref(false)

const submit = async () => {
  const username = form.value.username.trim()
  if (!username) return ElMessage.warning('请填写用户名')
  if (!form.value.password) return ElMessage.warning('请填写密码')
  if (setupRequired.value) {
    if (form.value.password.length < 8) return ElMessage.warning('密码至少 8 位')
    if (form.value.password !== form.value.confirm) return ElMessage.warning('两次输入的密码不一致')
  }
  loading.value = true
  try {
    if (setupRequired.value) {
      await setup(username, form.value.password)
      ElMessage.success('管理员创建成功')
    } else {
      await login(username, form.value.password)
      ElMessage.success('登录成功')
    }
    router.push('/')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!useAuth().checked.value) await init()
})
</script>

<style scoped>
.auth-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: radial-gradient(1200px 500px at 70% -10%, #eef1ff 0%, transparent 60%),
    linear-gradient(180deg, #f7f8fc 0%, #eef0f7 100%);
}

.auth-card {
  width: 380px;
  max-width: 100%;
  padding: 32px 30px 26px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 22px;
}

.brand-badge {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, #5c79ff 0%, #4f6bff 55%, #3d56cc 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 14px rgba(79, 107, 255, 0.35);
}

.brand-name {
  font-size: 18px;
  font-weight: 800;
  display: block;
  line-height: 1.15;
}

.brand-sub {
  font-size: 12px;
  color: var(--ink-3);
}

.auth-title {
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 6px;
}

.auth-desc {
  margin: 0 0 18px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.auth-btn {
  width: 100%;
  margin-top: 4px;
}
</style>
