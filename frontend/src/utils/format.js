// 通用格式化工具：平台展示名/缩写/配色、日期时间格式化。
// 在多个视图（概览/账户/任务设置/日志）中复用，避免各页面重复实现。

const pad2 = (n) => String(n).padStart(2, '0')

// 平台 key -> 插件展示名；未知平台回退显示 key 本身
export const platformName = (plugins, key) =>
  plugins.find((p) => p.platform === key)?.name || key

// 平台 key -> 单字缩写（用于头像占位）
export const platformShort = (plugins, key) =>
  (platformName(plugins, key) || key).slice(0, 1).toUpperCase()

// 平台 key -> 稳定配色：按 key 哈希从调色板取值，同一平台颜色恒定
export const platformColor = (key) => {
  const palette = ['#4f6bff', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4']
  let h = 0
  for (const c of String(key)) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return palette[h % palette.length]
}

/**
 * 把 ISO 时间格式化为「MM-DD HH:MM[:SS]」。
 *
 * @param {string} iso - ISO 时间字符串
 * @param {object} options - 可选参数
 * @param {string} [options.empty='--:--'] - 空值时的占位文案
 * @param {string|null} [options.invalid=null] - 无法解析时的返回值（缺省回退到 empty）
 * @param {boolean} [options.withSeconds=false] - 是否附带秒
 * @returns {string} 格式化后的时间字符串
 */
export const fmtDateTime = (iso, { empty = '--:--', invalid = null, withSeconds = false } = {}) => {
  if (!iso) return empty
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return invalid ?? empty
  const date = `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
  const time = withSeconds
    ? `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
    : `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
  return `${date} ${time}`
}
