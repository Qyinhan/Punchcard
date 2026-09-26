<template>
  <div class="qr-login">
    <el-form-item label="扫码登录">
      <div v-if="stage === 'qr'" class="qr-wrap">
        <img v-if="qrImage" :src="qrImage" class="qr-img" alt="登录二维码" />
        <el-icon v-else class="qr-loading" :size="32"><Loading /></el-icon>
      </div>
      <div v-else-if="stage === 'initializing'" class="qr-wrap">
        <el-icon class="qr-loading" :size="32"><Loading /></el-icon>
      </div>
      <div class="qr-actions">
        <el-button v-if="stage !== 'code'" type="primary"
          :loading="busy && stage === 'initializing'" @click="$emit('refresh')">
          {{ stage === 'qr' ? '刷新二维码' : '获取登录二维码' }}
        </el-button>
        <el-button v-if="stage" plain @click="$emit('cancel')">取消</el-button>
        <span v-if="hint" class="ops-hint">{{ hint }}</span>
      </div>
      <span class="ops-hint ops-tip">打开手机客户端扫码登录，登录成功后将自动保存凭证</span>
    </el-form-item>

    <el-form-item v-if="stage === 'code'" label="短信验证码" required>
      <el-input v-model="code" placeholder="输入手机上收到的验证码" maxlength="6" />
    </el-form-item>
    <el-form-item v-if="stage === 'code'">
      <el-button type="primary" :loading="busy" @click="$emit('submit-code')">确认登录</el-button>
    </el-form-item>
  </div>
</template>

<script setup>
import { Loading } from '@element-plus/icons-vue'

defineProps({
  stage: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  hint: { type: String, default: '' },
  qrImage: { type: String, default: '' },
})

const code = defineModel('smsCode', { type: String, default: '' })

defineEmits(['refresh', 'cancel', 'submit-code'])
</script>

<style scoped>
.qr-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 200px;
  height: 200px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px;
}

.qr-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.qr-loading {
  color: var(--ink-3);
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.qr-actions {
  display: flex;
  align-items: center;
  margin-top: 12px;
}

.ops-hint {
  margin-left: 8px;
  color: var(--ink-3);
  font-size: 12px;
}

.ops-tip {
  display: block;
  margin: 8px 0 0;
}
</style>
