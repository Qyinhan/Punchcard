<template>
  <div>
    <div class="page-head">
      <div>
        <div class="page-title">任务设置</div>
        <div class="page-sub">设置各账户的每日签到时间与目标好友，定时自动执行对应平台插件</div>
      </div>
      <div class="toolbar">
        <el-button @click="load">刷新</el-button>
      </div>
    </div>

    <div v-loading="loading" class="list">
      <div v-for="row in accounts" :key="row.id" class="row-card card" :class="{ off: !row.enabled }">
        <div class="row-main">
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

          <div class="row-time">
            <span class="lbl">每日签到时间</span>
            <el-time-select v-model="row.schedule_time" start="00:00" end="23:59" step="00:01"
              placeholder="选择时间" style="width: 140px" @change="(v) => saveTime(row, v)" />
            <span v-if="row.extra_config?.base_schedule_time" class="jitter-hint"
              :title="`基准时间 ${row.extra_config.base_schedule_time}，每天上下随机浮动 ${row.extra_config.random_offset || 10} 分钟`">
              浮动 ±{{ row.extra_config.random_offset || 10 }}m
            </span>
          </div>

          <div class="row-last">
            <span class="lbl">上次签到</span>
            <span class="val mono" :class="{ none: !row.last_checkin_at }">
              {{ row.last_checkin_at ? fmtDateTime(row.last_checkin_at, { invalid: row.last_checkin_at }) : '从未' }}
            </span>
          </div>

          <div class="row-switch">
            <span class="lbl">启用</span>
            <el-switch v-model="row.enabled" @change="(v) => saveEnabled(row, v)" />
          </div>
        </div>

        <div v-if="supportsFriends(row)" class="row-targets">
          <span class="lbl">目标好友</span>
          <el-select v-model="row._targets" multiple filterable popper-class="friend-dropdown"
            :placeholder="friendCount(row) ? '选择目标好友（支持多选）' : '请先点击右侧「同步好友列表」'" class="targets-select">
            <el-option v-for="f in (row.extra_config?.friends || [])" :key="f" :label="f" :value="f" />
          </el-select>
          <el-button size="small" plain :loading="row._syncing" @click="syncFriends(row)">
            {{ friendCount(row) ? '重新同步好友' : '同步好友列表' }}
          </el-button>
          <el-button type="primary" size="small" @click="saveTargets(row)">保存</el-button>
          <span v-if="row._syncHint" class="hint">{{ row._syncHint }}</span>
        </div>
      </div>

      <div v-if="!loading && !accounts.length" class="empty card">
        <p>还没有账户</p>
        <p class="empty-sub">到「账户管理」新增账户后，即可在这里设置签到时间与任务对象</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAccounts, getPlugins, updateAccount, startSyncFriends, getJobStatus } from '../api'
import { platformName, platformShort, platformColor, fmtDateTime } from '../utils/format'

const accounts = ref([])
const plugins = ref([])
const loading = ref(false)

// 该平台是否支持同步好友（据此显示目标好友编辑区）
const supportsFriends = (row) =>
  !!plugins.value.find((p) => p.platform === row.platform)?.friends_supported
const friendCount = (row) => (row.extra_config?.friends || []).length

const load = async () => {
  loading.value = true
  try {
    const [accs, pls] = await Promise.all([getAccounts(), getPlugins()])
    accounts.value = accs.map((a) => {
      a._targets = [...(a.extra_config?.targets || [])]
      return a
    })
    plugins.value = pls
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

const saveTime = async (row, val) => {
  try {
    const updated = await updateAccount(row.id, { schedule_time: val })
    row.schedule_time = updated.schedule_time
    row.extra_config = updated.extra_config
    const jitterText = updated.extra_config?.base_schedule_time ? '（已启用上下随机浮动）' : ''
    ElMessage.success(`已设置「${row.name}」签到时间为 ${val}${jitterText}`)
  } catch (e) {
    ElMessage.error(e.message)
    load()
  }
}

const saveEnabled = async (row, val) => {
  try {
    await updateAccount(row.id, { enabled: val })
    ElMessage.success(val ? `已启用「${row.name}」` : `已停用「${row.name}」`)
  } catch (e) {
    row.enabled = !val
    ElMessage.error(e.message)
  }
}

// 轮询好友同步任务（每 500ms 一次，最多 2 分钟）；成功后把拉取到的好友写入 extra_config.friends
const pollJob = async (row, jobId) => {
  for (let i = 0; i < 240; i++) {
    await new Promise((r) => setTimeout(r, 500))
    let job
    try {
      job = await getJobStatus(jobId)
    } catch (e) {
      break
    }
    if (job.status === 'running') continue
    row._syncing = false
    if (job.status === 'success') {
      const friends = job.result?.friends || []
      row.extra_config = { ...(row.extra_config || {}), friends }
      row._targets = [...(row.extra_config.targets || [])]
      row._syncHint = friends.length ? `共获取到 ${friends.length} 个好友` : '未获取到好友（请确认账号是否有会话记录）'
    } else {
      row._syncHint = ''
      ElMessage.error('同步好友失败：' + (job.error || '未知错误'))
    }
    return
  }
  row._syncing = false
  row._syncHint = ''
  ElMessage.error('同步好友超时')
}

const syncFriends = async (row) => {
  row._syncing = true
  row._syncHint = '正在启动…'
  try {
    const { job_id } = await startSyncFriends(row.id)
    row._syncHint = '正在滚动好友列表，请稍候…'
    pollJob(row, job_id)
  } catch (e) {
    row._syncing = false
    row._syncHint = ''
    ElMessage.error(e.message)
  }
}

const saveTargets = async (row) => {
  const targets = Array.isArray(row._targets) ? [...row._targets] : []
  try {
    await updateAccount(row.id, { extra_config: { ...(row.extra_config || {}), targets } })
    row.extra_config = { ...(row.extra_config || {}), targets }
    ElMessage.success(`已保存「${row.name}」的目标好友（${targets.length} 个）`)
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
  flex-direction: column;
  gap: 14px;
  padding: 16px 20px;
  transition: box-shadow 0.15s ease;
}

.row-card:hover {
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.08);
}

.row-card.off {
  opacity: 0.62;
}

.row-main {
  display: flex;
  align-items: center;
  gap: 24px;
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

.row-time,
.row-last {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: none;
  min-width: 96px;
}

.jitter-hint {
  font-size: 11px;
  color: var(--brand);
  background: var(--brand-soft);
  padding: 1px 6px;
  border-radius: 4px;
  display: inline-block;
  width: fit-content;
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

.row-targets {
  border-top: 1px dashed var(--line);
  padding-top: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.targets-select {
  flex: 1;
  min-width: 180px;
}

.targets-select :deep(.el-select__caret) {
  display: none;
}

.targets-select :deep(.el-select__selection) {
  gap: 6px;
}

.targets-select :deep(.el-select__selected-item) {
  margin-right: 4px;
}

.hint {
  font-size: 12px;
  color: var(--ink-3);
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

@media (max-width: 900px) {
  .row-main {
    flex-wrap: wrap;
    gap: 14px;
  }

  .targets-select {
    min-width: 100%;
  }
}
</style>
