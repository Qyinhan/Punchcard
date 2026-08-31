<template>
  <div class="sms-login">
    <el-form-item v-if="stage === 'captcha' && geetestParams" label="人机验证">
      <div class="geetest-wrap">
        <p class="captcha-tip">请完成下方滑块验证后自动发送短信</p>
        <div :ref="setContainerRef" class="geetest-container"></div>
      </div>
    </el-form-item>

    <el-form-item v-if="stage === 'code'" label="短信验证码" required>
      <el-input v-model="code" placeholder="输入收到的6位短信验证码" maxlength="6" />
    </el-form-item>

    <el-form-item>
      <el-button type="primary" plain
        :loading="busy && stage === 'initializing'"
        @click="$emit('send')">获取验证码</el-button>
      <el-button v-if="stage === 'code'" :loading="busy" @click="$emit('submit-code')">登录</el-button>
      <el-button v-if="stage" plain @click="$emit('cancel')">取消登录</el-button>
      <span v-if="hint" class="ops-hint">{{ hint }}</span>
    </el-form-item>
  </div>
</template>

<script setup>
const props = defineProps({
  stage: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  hint: { type: String, default: '' },
  geetestParams: { type: Object, default: null },
  // 极验容器 ref 由外部（composable）持有，组件仅负责把 DOM 挂上去
  containerRef: { type: Object, default: null },
})

const code = defineModel('smsCode', { type: String, default: '' })

defineEmits(['send', 'cancel', 'submit-code'])

const setContainerRef = (el) => {
  if (el && props.containerRef) props.containerRef.value = el
}
</script>

<style scoped>
.geetest-wrap {
  width: 100%;
}

.captcha-tip {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--ink-3);
}

.geetest-container {
  max-width: 360px;
  min-height: 44px;
}

.ops-hint {
  margin-left: 8px;
  color: var(--ink-3);
  font-size: 12px;
}
</style>
