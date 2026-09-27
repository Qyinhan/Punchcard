<template>
  <div>
    <div class="page-head">
      <div>
        <div class="page-title">平台插件</div>
        <div class="page-sub">管理各平台的签到插件：支持安装、启停与卸载。卸载插件前请先删除关联账户</div>
      </div>
      <div class="toolbar">
        <el-button @click="reload">重新加载</el-button>
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" plain @click="triggerInstall">
          <el-icon><Upload /></el-icon>&nbsp;安装插件
        </el-button>
      </div>
    </div>

    <input ref="fileInput" type="file" accept=".zip" style="display: none" @change="onFileSelected" />

    <div v-loading="loading" class="grid">
      <div v-for="row in plugins" :key="row.platform" class="plug card" :class="{ off: row.enabled === false }">
        <div class="plug-top">
          <div class="plug-avatar" :class="{ on: row.enabled !== false }">
            {{ platformShort(plugins, row.platform) }}
          </div>
          <div class="plug-title">
            <div class="plug-name">{{ row.name }}</div>
            <div class="plug-key mono">{{ row.platform }}</div>
          </div>
          <el-switch v-model="row.enabled" @change="(v) => toggle(row, v)" />
        </div>

        <p class="plug-desc">{{ row.description || '暂无描述' }}</p>

        <div class="plug-foot">
          <span class="plug-status" :class="row.enabled === false ? 'off' : 'on'">
            <span class="dot" :class="row.enabled === false ? 'off' : 'ok'"></span>
            {{ row.enabled === false ? '已停用' : '已启用' }}
          </span>
          <el-button size="small" type="danger" plain @click="remove(row)">卸载</el-button>
        </div>
      </div>

      <div v-if="!loading && !plugins.length" class="empty card">
        <p>暂无插件</p>
        <p class="empty-sub">点击右上角「安装插件」，上传插件 ZIP 包</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { getPlugins, updatePlugin, installPlugin, reloadPlugins, uninstallPlugin } from '../api'
import { platformShort } from '../utils/format'
import { confirmAction } from '../utils/confirm'

const plugins = ref([])
const loading = ref(false)
const fileInput = ref(null)

const load = async () => {
  loading.value = true
  try {
    plugins.value = await getPlugins()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

const toggle = async (row, val) => {
  try {
    await updatePlugin(row.platform, val)
    row.enabled = val
    ElMessage.success(val ? `已启用「${row.name}」` : `已停用「${row.name}」`)
  } catch (e) {
    row.enabled = !val
    ElMessage.error(e.message)
  }
}

const triggerInstall = () => {
  fileInput.value?.click()
}

const onFileSelected = async (e) => {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  try {
    const info = await installPlugin(file)
    ElMessage.success(`插件「${info.name}」(${info.platform}) 安装成功`)
    load()
  } catch (err) {
    ElMessage.error(err.message)
  }
}

const reload = async () => {
  try {
    await reloadPlugins()
    ElMessage.success('已重新扫描插件目录')
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const remove = async (row) => {
  await confirmAction(
    `确定卸载插件「${row.name}」(${row.platform})？若有关联账户，需先将其删除。`,
    async () => { await uninstallPlugin(row.platform); load() },
    '已卸载',
  )
}

onMounted(load)
</script>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  min-height: 120px;
  align-items: stretch;
}

.plug {
  padding: 18px;
  display: flex;
  flex-direction: column;
  transition: box-shadow 0.15s ease, opacity 0.15s ease;
}

.plug:hover {
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.08);
}

.plug.off {
  opacity: 0.62;
}

.plug-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.plug-avatar {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  background: #e5e7eb;
  color: var(--ink-3);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
  flex: none;
}

.plug-avatar.on {
  background: var(--brand-soft);
  color: var(--brand);
}

.plug-title {
  flex: 1;
  min-width: 0;
}

.plug-name {
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 6px;
}

.plug-key {
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--ink-3);
}

.plug-desc {
  margin: 14px 0 16px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.6;
  flex: 1;
}

.plug-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px dashed var(--line);
  padding-top: 12px;
}

.plug-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink-3);
}

.plug-status.on {
  color: var(--ok);
}

.empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 40px 0;
  color: var(--ink-2);
}

.empty-sub {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--ink-3);
}
</style>
