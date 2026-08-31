<template>
  <div>
    <div class="page-head">
      <div>
        <div class="page-title">账户管理</div>
        <div class="page-sub">管理各平台签到账户：配置登录凭证、签到时间与目标</div>
      </div>
      <div class="toolbar">
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>&nbsp;新增账户
        </el-button>
      </div>
    </div>

    <div v-loading="loading" class="list">
      <div v-for="row in accounts" :key="row.id" class="row-card card" :class="{ off: !row.enabled }">
        <div class="row-acct">
          <div class="acct-avatar" :style="{ background: platformColor(row.platform) }">
            {{ platformShort(plugins, row.platform) }}
          </div>
          <div class="acct-title">
            <div class="acct-name">{{ row.name }}</div>
            <div class="acct-sub">
              {{ platformName(plugins, row.platform) }}
              <span class="acct-key mono">{{ row.platform }}</span>
            </div>
          </div>
        </div>

        <div class="row-meta">
          <span class="lbl">每日签到时间</span>
          <span class="val mono">{{ row.schedule_time }}</span>
        </div>

        <div class="row-meta">
          <span class="lbl">上次签到</span>
          <span class="val mono" :class="{ none: !row.last_checkin_at }">
            {{ row.last_checkin_at ? fmtDateTime(row.last_checkin_at, { invalid: row.last_checkin_at }) : '从未' }}
          </span>
        </div>

        <div class="row-meta" v-if="row.credential_keys.length">
          <span class="lbl">已配置凭证</span>
          <span class="val mono cred">{{ row.credential_keys.join('、') }}</span>
        </div>

        <div class="row-switch">
          <span class="lbl">启用</span>
          <el-switch v-model="row.enabled" @change="(v) => toggle(row, v)" />
        </div>

        <div class="row-ops">
          <el-button size="small" type="primary" :loading="row._checking" @click="checkin(row)">
            立即签到
          </el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </div>
      </div>

      <div v-if="!loading && !accounts.length" class="empty card">
        <p>还没有账户</p>
        <p class="empty-sub">点击右上角「新增账户」，选择平台并配置凭证</p>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑账户' : '新增账户'" width="560px" destroy-on-close>
      <el-form :model="form" label-width="110px">
        <el-form-item label="平台" required>
          <el-select v-model="form.platform" :disabled="!!editingId" style="width: 100%" @change="onPlatformChange">
            <el-option v-for="p in enabledPlugins" :key="p.platform" :label="p.name" :value="p.platform" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="给这个账户起个名字" />
        </el-form-item>

        <template v-if="currentPlugin">
          <template v-if="currentPlugin.platform === 'douyin'">
            <el-divider content-position="left">抖音登录</el-divider>

            <el-form-item label="扫码登录">
              <div v-if="loginStage === 'qr'" class="qr-wrap" style="margin-bottom: 12px;">
                <img v-if="qrImage" :src="qrImage" class="qr-img" alt="登录二维码" />
                <el-icon v-else class="qr-loading" :size="32"><Loading /></el-icon>
              </div>
              <div class="qr-actions">
                <el-button type="primary" :loading="loginBusy && loginStage === 'initializing'" @click="doQrLogin">
                  {{ loginStage === 'qr' ? '刷新二维码' : '获取登录二维码' }}
                </el-button>
                <el-button v-if="loginStage" plain @click="doLoginCancel">取消</el-button>
                <span v-if="loginHint" class="ops-hint" style="margin-left: 10px;">{{ loginHint }}</span>
              </div>
              <span class="ops-hint" style="display:block;margin-top:8px;">打开手机抖音 APP，扫一扫即可登录（免验证码，登录后自动保存 Cookie）</span>
            </el-form-item>

            <el-form-item v-if="loginStage === 'code'" label="短信验证码" required>
              <el-input v-model="smsCode" placeholder="输入手机上收到的验证码" maxlength="6" />
            </el-form-item>

            <el-form-item v-if="loginStage === 'code'">
              <el-button :loading="loginBusy" @click="doLoginCode">登录</el-button>
            </el-form-item>

            <el-form-item label="Cookie">
              <el-input v-model="form.credentials.cookies" type="textarea" :rows="3"
                placeholder="扫码登录后自动保存，可留空；也可直接粘贴浏览器导出的 Cookie 字符串（name=value; ...）" />
            </el-form-item>
          </template>

          <template v-else-if="currentPlugin.platform === 'bilibili'">
            <el-divider content-position="left">B站登录</el-divider>
            <el-form-item label="登录手机号">
              <el-input v-model="form.credentials.phone" placeholder="手机号，用于短信验证码登录" />
            </el-form-item>

            <el-form-item v-if="loginStage === 'captcha' && geetestParams" label="人机验证">
              <div class="geetest-wrap">
                <p class="captcha-tip">请完成下方滑块验证后自动发送短信</p>
                <div ref="geetestContainerRef" class="geetest-container"></div>
              </div>
            </el-form-item>

            <el-form-item v-if="loginStage === 'code'" label="短信验证码" required>
              <el-input v-model="smsCode" placeholder="输入收到的6位短信验证码" maxlength="6" />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" plain
                :loading="loginBusy && loginStage === 'initializing'"
                @click="doBiliLoginStart">获取验证码</el-button>
              <el-button v-if="loginStage === 'code'" :loading="loginBusy" @click="doLoginCode">登录</el-button>
              <el-button v-if="loginStage" plain @click="doLoginCancel">取消登录</el-button>
              <span v-if="loginHint" class="ops-hint">{{ loginHint }}</span>
            </el-form-item>

            <el-divider content-position="left">凭证信息</el-divider>
            <el-form-item label="SESSDATA">
              <el-input v-model="form.credentials.sessdata" type="password" show-password
                :placeholder="editingId ? '登录后自动保存，留空则不修改' : '手动填写 SESSDATA Cookie；或使用手机号登录自动获取'" />
            </el-form-item>
          </template>

          <template v-else>
            <el-divider content-position="left">凭证信息</el-divider>
            <el-form-item v-for="f in currentPlugin.credential_fields" :key="f.key" :label="f.label"
              :required="f.required && !editingId">
              <el-input v-if="f.type === 'textarea'" v-model="form.credentials[f.key]" type="textarea" :rows="3"
                :placeholder="editingId ? '留空则不修改' : f.placeholder" />
              <el-input v-else-if="f.type === 'password'" v-model="form.credentials[f.key]" type="password" show-password
                :placeholder="editingId ? '留空则不修改' : f.placeholder" />
              <el-input v-else v-model="form.credentials[f.key]"
                :placeholder="editingId ? '留空则不修改' : f.placeholder" />
            </el-form-item>

            <template v-if="currentPlugin.config_fields.length">
              <el-divider content-position="left">附加配置</el-divider>
              <el-form-item v-for="f in currentPlugin.config_fields" :key="f.key" :label="f.label">
                <el-input v-if="f.type === 'textarea'" v-model="form.extra_config[f.key]" type="textarea" :rows="2"
                  :placeholder="f.placeholder" />
                <el-input v-else-if="f.type === 'number'" v-model="form.extra_config[f.key]" type="number"
                  :placeholder="f.placeholder" />
                <el-input v-else v-model="form.extra_config[f.key]" :placeholder="f.placeholder" />
              </el-form-item>
            </template>
          </template>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Loading } from '@element-plus/icons-vue'
import {
  getPlugins, getAccounts, createAccount, updateAccount, deleteAccount, triggerCheckin,
  loginStart, loginStatus, loginCode, loginCaptcha, loginCancel, qrLogin,
} from '../api'
import { platformName, platformShort, platformColor, fmtDateTime } from '../utils/format'

const accounts = ref([])
const plugins = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)

const loginStage = ref('')          // '' | initializing | captcha | code | success | failed
const loginBusy = ref(false)
const loginHint = ref('')
// 已提交验证码、正在等登录结果：期间状态会短暂停留在 code，需持续轮询直到成功/失败
const codePending = ref(false)
const smsCode = ref('')
const qrImage = ref('')
const geetestParams = ref(null)
const geetestContainerRef = ref(null)
let geetestObj = null
let loginPollTimer = null

const form = reactive({ platform: '', name: '', credentials: {}, extra_config: {}, schedule_time: '08:00' })

// 当前表单所选平台的插件定义；注意 credentials/extra_config 由平台字段驱动动态渲染
const currentPlugin = computed(() => plugins.value.find((p) => p.platform === form.platform))
// 下拉框只展示已启用的平台
const enabledPlugins = computed(() => plugins.value.filter((p) => p.enabled !== false))

const load = async () => {
  loading.value = true
  try {
    const [accs, pls] = await Promise.all([getAccounts(), getPlugins()])
    accounts.value = accs
    plugins.value = pls
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

const resetForm = (p = '') => {
  form.platform = p
  form.name = ''
  form.credentials = {}
  form.extra_config = {}
  form.schedule_time = '08:00'
}

const onPlatformChange = () => {
  form.credentials = {}
  form.extra_config = {}
  resetLoginOps()
  if (currentPlugin.value) {
    form.schedule_time = currentPlugin.value.default_schedule_time
  }
}

const resetLoginOps = () => {
  clearTimeout(loginPollTimer)
  loginPollTimer = null
  codePending.value = false
  loginStage.value = ''
  loginBusy.value = false
  loginHint.value = ''
  qrImage.value = ''
  geetestParams.value = null
  if (geetestObj) {
    try { geetestObj.destroy() } catch {}
    geetestObj = null
  }
  smsCode.value = ''
}

const clearOps = () => {
  resetLoginOps()
}

watch(dialogVisible, (v) => {
  if (!v) {
    // 关对话框时若登录还在进行，取消服务器会话，避免残留导致下次登录 409。
    // 无条件调用（无会话时后端 404，doLoginCancel 已静默吞掉）
    if (editingId.value) {
      doLoginCancel()
    } else {
      clearOps()
    }
    load()
  }
})

const openCreate = () => {
  editingId.value = null
  clearOps()
  resetForm(plugins.value[0]?.platform || '')
  onPlatformChange()
  dialogVisible.value = true
}

const openEdit = (row) => {
  editingId.value = row.id
  clearOps()
  resetForm(row.platform)
  form.name = row.name
  form.schedule_time = row.schedule_time
  // 编辑时仅回显非敏感凭证（如手机号等）；敏感字段后端不返回，留空表示不修改
  form.credentials = { ...(row.credentials || {}) }
  dialogVisible.value = true
}

// 延迟 1.5s 后轮询一次登录会话状态（登录各阶段都是异步推进的）
const scheduleLoginPoll = () => {
  clearTimeout(loginPollTimer)
  loginPollTimer = setTimeout(pollLogin, 1500)
}

// 轮询登录会话状态，按 stage 分支渲染对应交互区（滑块/验证码/成功/失败）
const pollLogin = async () => {
  if (!editingId.value) return
  try {
    const s = await loginStatus(editingId.value)
    if (s.stage === 'captcha') {
      loginStage.value = 'captcha'
      loginBusy.value = false
      // B站：加载极验组件
      if (s.geetest) {
        geetestParams.value = s.geetest
        loginHint.value = '请完成下方滑块验证'
        await nextTick()
        loadGeetest(s.geetest)
      }
    } else if (s.stage === 'code') {
      if (codePending.value) {
        // 验证码已提交、后端仍在处理（可能持续几十秒），继续等待。
        // 后端收到 code 命令后才会切状态，期间轮询到的仍是旧的
        // device_code 状态，必须以本地 codePending 为准，避免退回输入框
        loginStage.value = 'initializing'
        loginBusy.value = true
        loginHint.value = '正在验证登录…'
        scheduleLoginPoll()
      } else if (s.device_code) {
        // 设备授权第二步：输入手机上收到的授权验证码
        loginStage.value = 'code'
        loginHint.value = '设备授权验证码已发送，请输入手机上收到的验证码'
        loginBusy.value = false
        smsCode.value = ''
      } else {
        loginStage.value = 'code'
        loginHint.value = s.sent ? '验证码已发送，请输入短信验证码' : '请输入短信验证码'
        loginBusy.value = false
      }
    } else if (s.stage === 'success') {
      codePending.value = false
      loginStage.value = 'success'
      loginBusy.value = false
      loginHint.value = ''
      ElMessage.success('登录成功，Cookie 已保存')
      load()
    } else if (s.stage === 'failed') {
      codePending.value = false
      loginStage.value = 'failed'
      loginBusy.value = false
      loginHint.value = s.error || '登录失败'
      ElMessage.error(s.error || '登录失败')
    } else if (s.stage === 'qr') {
      // 扫码登录：展示二维码，等待用户手机扫码；已扫码则提示去手机确认
      loginStage.value = 'qr'
      loginBusy.value = true
      if (s.scanned) {
        loginHint.value = s.message || '二维码已扫码，请在手机抖音 APP 中完成确认登录…'
      } else {
        loginHint.value = '请用手机抖音 APP 扫码，扫码后确认登录'
        if (s.qr_image) qrImage.value = 'data:image/png;base64,' + s.qr_image
      }
      scheduleLoginPoll()
    } else if (s.stage === 'device_confirm') {
      // 抖音"新设备登录"二次验证：需要用户在手机抖音 APP 中确认
      codePending.value = false
      loginStage.value = 'device_confirm'
      loginBusy.value = true
      loginHint.value = s.message
        ? `请在手机「抖音」APP 中确认登录（${s.message}）`
        : '请在手机「抖音」APP 中确认登录，确认后会自动完成…'
      scheduleLoginPoll()
    } else {
      loginStage.value = 'initializing'
      scheduleLoginPoll()
    }
  } catch (e) {
    codePending.value = false
    loginBusy.value = false
    loginHint.value = e.message
    if (String(e.message).includes('无登录会话')) {
      loginStage.value = ''
    } else {
      scheduleLoginPoll()
    }
  }
}

const doQrLogin = async () => {
  const id = await ensureSavedAccount()
  if (!id) return
  loginBusy.value = true
  loginStage.value = 'initializing'
  loginHint.value = '正在获取登录二维码…'
  try {
    await qrLogin(id)
    scheduleLoginPoll()
  } catch (e) {
    loginBusy.value = false
    loginStage.value = ''
    loginHint.value = ''
    ElMessage.error(e.message)
  }
}

const doLoginCode = async () => {
  if (!smsCode.value) {
    ElMessage.warning('请输入短信验证码')
    return
  }
  codePending.value = true
  loginBusy.value = true
  loginStage.value = 'initializing'
  loginHint.value = '正在验证登录…'
  try {
    await loginCode(editingId.value, smsCode.value)
    scheduleLoginPoll()
  } catch (e) {
    codePending.value = false
    loginBusy.value = false
    loginHint.value = ''
    ElMessage.error(e.message)
  }
}

const doLoginCancel = async () => {
  try {
    if (editingId.value) await loginCancel(editingId.value)
  } catch (e) { /* 忽略取消失败 */ }
  resetLoginOps()
}

// ---- B站登录 ----

// B 站流程：先获取极验参数（send_code），前端完成后端发短信（captcha），再输验证码（code）
const doBiliLoginStart = async () => {
  if (!form.credentials.phone) {
    ElMessage.warning('请先填写登录手机号')
    return
  }
  const id = await ensureSavedAccount()
  if (!id) return
  loginBusy.value = true
  loginStage.value = 'initializing'
  loginHint.value = '正在获取极验参数…'
  try {
    await loginStart(id, form.credentials.phone)
    scheduleLoginPoll()
  } catch (err) {
    loginBusy.value = false
    loginHint.value = ''
    ElMessage.error(err.message)
  }
}

// 按需加载极验组件（window.initGeetest），首次使用才注入官方脚本
const loadGeetest = (params) => {
  const doInit = () => {
    if (!geetestContainerRef.value) return
    window.initGeetest({
      gt: params.gt,
      challenge: params.challenge,
      offline: false,
      new_captcha: true,
      product: 'bind',
      width: '100%',
    }, (captcha) => {
      geetestObj = captcha
      captcha.appendTo(geetestContainerRef.value)
      captcha.onSuccess(async () => {
        const result = captcha.getValidate()
        loginBusy.value = true
        loginStage.value = 'initializing'
        loginHint.value = '正在发送短信验证码…'
        try {
          await loginCaptcha(editingId.value, {
            validate: result.geetest_validate,
            seccode: result.geetest_seccode,
            challenge: result.geetest_challenge,
            token: params.token,
          })
          scheduleLoginPoll()
        } catch (err) {
          loginBusy.value = false
          loginHint.value = ''
          ElMessage.error(err.message)
        }
      })
    })
  }
  if (window.initGeetest) {
    doInit()
  } else {
    const script = document.createElement('script')
    script.src = 'https://static.geetest.com/static/js/gt.0.4.9.js'
    script.onload = doInit
    // SDK 加载失败（如外网 CDN 不可达）时给出明确提示，避免按钮无响应
    script.onerror = () => {
      loginBusy.value = false
      loginHint.value = ''
      ElMessage.error('极验 SDK 加载失败，请检查网络后重试')
    }
    document.head.appendChild(script)
  }
}

const submitAccount = async (closeAfter) => {
  if (!form.platform || !form.name) {
    ElMessage.warning('请填写平台和名称')
    return null
  }
  saving.value = true
  try {
    const payload = {
      platform: form.platform,
      name: form.name,
    }
    if (editingId.value) {
      // 编辑时：仅提交有值的字段（合并语义，避免覆盖留空的敏感字段）
      const filledCreds = Object.fromEntries(
        Object.entries(form.credentials).filter(([, v]) => v !== '' && v !== null && v !== undefined)
      )
      if (Object.keys(filledCreds).length) payload.credentials = filledCreds
      if (Object.keys(form.extra_config).length) payload.extra_config = form.extra_config
    } else {
      // 新建时：提交全部表单字段
      payload.credentials = form.credentials
      payload.extra_config = form.extra_config
    }

    let account = { id: editingId.value }
    if (editingId.value) {
      await updateAccount(editingId.value, payload)
    } else {
      account = await createAccount(payload)
      editingId.value = account.id
    }
    if (closeAfter) {
      ElMessage.success('保存成功')
      dialogVisible.value = false
    }
    load()
    return account
  } catch (e) {
    ElMessage.error(e.message)
    return null
  } finally {
    saving.value = false
  }
}

const save = () => submitAccount(true)

// 确保账户已落库：新建账户时若尚未保存，则先创建（登录需要账户 ID）
const ensureSavedAccount = async () => {
  if (editingId.value) return editingId.value
  const acc = await submitAccount(false)
  return acc ? acc.id : null
}

const toggle = async (row, val) => {
  try {
    await updateAccount(row.id, { enabled: val })
    ElMessage.success(val ? '已启用' : '已停用')
  } catch (e) {
    row.enabled = !val
    ElMessage.error(e.message)
  }
}

const checkin = async (row) => {
  row._checking = true
  try {
    const r = await triggerCheckin(row.id)
    ElMessage[r.status === 'success' ? 'success' : 'warning'](r.message || r.status)
    load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    row._checking = false
  }
}

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除账户「${row.name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteAccount(row.id)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 120px;
}

.row-card {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 16px 20px;
  transition: box-shadow 0.15s ease, opacity 0.15s ease;
}

.row-card:hover {
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.08);
}

.row-card.off {
  opacity: 0.62;
}

.row-acct {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.acct-avatar {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  flex: none;
}

.acct-title {
  min-width: 0;
}

.acct-name {
  font-size: 14.5px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.acct-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  font-size: 12px;
  color: var(--ink-3);
}

.acct-key {
  font-size: 11px;
  background: #f1f3f7;
  padding: 0 6px;
  border-radius: 5px;
  color: var(--ink-2);
}

.row-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: none;
  min-width: 96px;
}

.row-switch {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: none;
}

.lbl {
  font-size: 12px;
  color: var(--ink-3);
}

.val {
  font-size: 13.5px;
  color: var(--ink-2);
}

.val.none {
  color: var(--ink-3);
}

.val.cred {
  font-size: 12.5px;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-ops {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.empty {
  text-align: center;
  padding: 40px 0;
  color: var(--ink-2);
}

.empty-sub {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--ink-3);
}

.ops-hint {
  margin-left: 8px;
  color: var(--ink-3);
  font-size: 12px;
}

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

.captcha-wrap {
  width: 100%;
}

.captcha-tip {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--ink-3);
}

.captcha-img-wrap {
  position: relative;
  display: inline-block;
  cursor: crosshair;
  user-select: none;
  border-radius: 8px;
  overflow: hidden;
}

.captcha-img-wrap:hover {
  box-shadow: 0 0 0 2px var(--brand);
}

.captcha-img {
  display: block;
  max-width: 320px;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.captcha-guide {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: rgba(79, 107, 255, 0.75);
  pointer-events: none;
  transform: translateX(-50%);
  box-shadow: 0 0 6px rgba(79, 107, 255, 0.5);
}

.geetest-wrap {
  width: 100%;
}

.geetest-container {
  max-width: 360px;
  min-height: 44px;
}
</style>
