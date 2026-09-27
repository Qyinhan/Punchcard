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
          <span class="val mono">
            {{ row.schedule_time }}
            <span v-if="row.extra_config?.next_schedule_time || row.extra_config?.random_offset !== undefined" class="jitter-tag"
              :title="`基准时间 ${row.schedule_time}，每天上下随机浮动 ${row.extra_config?.random_offset ?? 10} 分钟（下次预计 ${row.extra_config?.next_schedule_time || row.schedule_time}）`">
              ±{{ row.extra_config?.random_offset ?? 10 }}m
            </span>
          </span>
        </div>

        <div class="row-meta">
          <span class="lbl">上次签到</span>
          <span class="val mono" :class="{ none: !row.last_checkin_at }">
            {{ row.last_checkin_at ? fmtDateTime(row.last_checkin_at, { invalid: row.last_checkin_at }) : '从未' }}
          </span>
        </div>

        <div class="row-meta" v-if="row.has_credentials">
          <span class="lbl">已配置凭证</span>
          <span class="val mono cred">
            {{ row.credential_keys.length ? row.credential_keys.join('、') : '已保存' }}
          </span>
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
          <template v-if="currentPlugin.login_mode === 'qr'">
            <el-divider content-position="left">扫码登录</el-divider>
            <QrLoginPanel v-model:smsCode="smsCode" :stage="loginStage" :busy="loginBusy"
              :hint="loginHint" :qr-image="qrImage" @refresh="doQrLogin"
              @cancel="doLoginCancel" @submit-code="doLoginCode" />
          </template>

          <template v-else-if="currentPlugin.login_mode === 'geetest_sms'">
            <SmsLoginPanel v-model:smsCode="smsCode" :stage="loginStage" :busy="loginBusy"
              :hint="loginHint" :geetest-params="geetestParams" :container-ref="geetestContainerRef"
              @send="doSmsLoginStart" @cancel="doLoginCancel" @submit-code="doLoginCode" />
          </template>

          <el-divider content-position="left">凭证信息</el-divider>
          <el-form-item v-for="f in currentPlugin.credential_fields" :key="f.key" :label="f.label"
            :required="f.required && !editingId">
            <el-input v-if="f.type === 'textarea'" v-model="form.credentials[f.key]" type="textarea" :rows="3"
              :placeholder="editingId ? '留空则不修改' : f.placeholder" style="width: 100%" />
            <el-input v-else-if="f.type === 'password'" v-model="form.credentials[f.key]" type="password" show-password
              :placeholder="editingId ? '留空则不修改' : f.placeholder" style="width: 100%" />
            <el-input v-else v-model="form.credentials[f.key]"
              :placeholder="editingId ? '留空则不修改' : f.placeholder" style="width: 100%" />
            <div v-if="f.hint" class="field-hint">{{ f.hint }}</div>
          </el-form-item>
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
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import {
  getPlugins, getAccounts, createAccount, updateAccount, deleteAccount, triggerCheckin,
} from '../api'
import { useLoginSession } from '../composables/useLoginSession'
import QrLoginPanel from '../components/login/QrLoginPanel.vue'
import SmsLoginPanel from '../components/login/SmsLoginPanel.vue'
import { platformName, platformShort, platformColor, fmtDateTime } from '../utils/format'

const accounts = ref([])
const plugins = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)

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

const clearOps = () => {
  resetLoginOps()
}

watch(dialogVisible, (v) => {
  if (!v) {
    // 关对话框时若登录还在进行，取消服务器会话，避免残留导致下次登录 409。
    // 无条件调用（无会话时后端 404，doLoginCancel 已静默吞掉）
    if (editingId.value) {
      doLoginCancel(editingId.value)
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

// 交互式登录（平台无关，由插件 login_mode 驱动）：
// 状态机在 ensureSavedAccount 定义后初始化，见脚本下方

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
      // 编辑时：仅提交有值的凭证字段（合并语义，避免覆盖留空的敏感字段）
      const filledCreds = Object.fromEntries(
        Object.entries(form.credentials).filter(([, v]) => v !== '' && v !== null && v !== undefined)
      )
      if (Object.keys(filledCreds).length) payload.credentials = filledCreds
    } else {
      // 新建时：提交凭证字段
      payload.credentials = form.credentials
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

// 交互式登录状态机：依赖 ensureSavedAccount 定义之后才能初始化
const {
  loginStage, loginBusy, loginHint, smsCode, qrImage,
  geetestParams, geetestContainerRef,
  doQrLogin, doSmsLoginStart, doLoginCode, doLoginCancel, resetLoginOps,
} = useLoginSession({
  getAccountId: ensureSavedAccount,
  onSuccess: load,
})

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
    await ElMessageBox.confirm(`确定删除账户「${row.name}」？删除后该账户的凭证及配置将被彻底清除。`, '提示', { type: 'warning' })
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

.jitter-tag {
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--brand-soft);
  color: var(--brand);
  margin-left: 4px;
  vertical-align: 1px;
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

.field-hint {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 5px;
  line-height: 1.4;
  width: 100%;
}

:deep(.el-dialog__body .el-divider--horizontal) {
  margin: 18px 0 16px;
}
</style>
