<template>
  <div>
    <div class="page-head">
      <div>
        <div class="page-title">签到日志</div>
        <div class="page-sub">全部执行记录，可按平台、状态筛选</div>
      </div>
    </div>

    <div class="card">
      <div class="toolbar">
        <el-select v-model="filters.platform" clearable placeholder="按平台筛选" style="width: 160px">
          <el-option v-for="p in plugins" :key="p.platform" :label="p.name" :value="p.platform" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="按状态筛选" style="width: 140px">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
        </el-select>
        <span class="spacer"></span>
        <el-button type="primary" @click="load(1)">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-button type="danger" plain @click="clearAll">清空日志</el-button>
      </div>

      <el-table :data="logs" empty-text="暂无日志" v-loading="loading" style="width: 100%">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            <span class="mono">{{ fmtDateTime(row.executed_at, { invalid: row.executed_at, withSeconds: true }) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="account_name" label="账户" min-width="120" />
        <el-table-column label="平台" width="100">
          <template #default="{ row }">
            <span class="plat-tag">{{ platformName(plugins, row.platform) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="触发方式" width="80">
          <template #default="{ row }">
            <span class="src" :class="row.source">
              {{ row.source === 'auto' ? '定时' : '手动' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <span class="status" :class="row.status">
              <span class="dot" :class="row.status"></span>
              {{ row.status === 'success' ? '成功' : '失败' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">
            <span class="mono dur">{{ row.duration_ms }}ms</span>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="信息" show-overflow-tooltip min-width="200" />
      </el-table>

      <div class="pager">
        <el-pagination background layout="total, prev, pager, next" :total="total"
          :page-size="pageSize" v-model:current-page="page" @current-change="(p) => load(p)" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getLogs, getPlugins, clearLogs } from '../api'
import { platformName, fmtDateTime } from '../utils/format'

const logs = ref([])
const plugins = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const filters = reactive({ platform: '', status: '' })

const load = async (p = page.value) => {
  loading.value = true
  try {
    const params = { page: p, page_size: pageSize }
    if (filters.platform) params.platform = filters.platform
    if (filters.status) params.status = filters.status
    const data = await getLogs(params)
    logs.value = data.items
    total.value = data.total
    page.value = p
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

const resetFilters = () => {
  filters.platform = ''
  filters.status = ''
  load(1)
}

const clearAll = async () => {
  try {
    await ElMessageBox.confirm('确定清空所有签到日志？此操作不可恢复。', '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await clearLogs()
    ElMessage.success('已清空')
    load(1)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(async () => {
  try {
    plugins.value = await getPlugins()
  } catch (e) {
    ElMessage.error(e.message)
  }
  load(1)
})
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.plat-tag {
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
}

.src {
  font-size: 12px;
  color: var(--ink-2);
}

.src.auto {
  color: var(--ok);
}

.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
}

.status.success {
  color: var(--ok);
}

.status.failed {
  color: var(--bad);
}

.dur {
  font-size: 12px;
  color: var(--ink-3);
}

.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
