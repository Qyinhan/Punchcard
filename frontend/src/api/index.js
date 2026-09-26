import axios from 'axios'

/**
 * 全局 HTTP 客户端（axios 实例）。
 * 统一以 /api 为前缀并设 60s 超时；响应拦截器直接返回 data，
 * 错误时把后端 detail / err.message 转为 Error 抛出，供各页面统一提示。
 */
const http = axios.create({
  baseURL: '/api',
  timeout: 60000,
  withCredentials: true,
})

// 登录/初始化接口自身的 401 表示"密码错误"等，不应触发跳转登录页
const AUTH_EXEMPT = ['/auth/login', '/auth/setup', '/auth/setup-state']

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (err.response?.status === 401 && !AUTH_EXEMPT.includes(err.config?.url || '')) {
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    let msg = '请求失败'
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') {
      msg = detail
    } else if (Array.isArray(detail) && detail.length > 0) {
      msg = detail.map((d) => d.msg || d.message || JSON.stringify(d)).join('；')
    } else if (detail && typeof detail === 'object') {
      msg = detail.msg || detail.message || JSON.stringify(detail)
    } else if (err.message) {
      msg = err.message
    }
    return Promise.reject(new Error(msg))
  }
)

export const getPlugins = () => http.get('/plugins')
export const updatePlugin = (platform, enabled) => http.put(`/plugins/${platform}`, { enabled })
export const installPlugin = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return http.post('/plugins/install', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}
export const reloadPlugins = () => http.post('/plugins/reload')
export const uninstallPlugin = (platform) => http.delete(`/plugins/${platform}`)
export const getAccounts = () => http.get('/accounts')
export const createAccount = (data) => http.post('/accounts', data)
export const updateAccount = (id, data) => http.put(`/accounts/${id}`, data)
export const deleteAccount = (id) => http.delete(`/accounts/${id}`)
export const triggerCheckin = (id) => http.post(`/accounts/${id}/checkin`)
export const loginStart = (id, phone) => http.post(`/accounts/${id}/login`, { phone })
export const qrLogin = (id) => http.post(`/accounts/${id}/login/qr`)
export const loginStatus = (id) => http.get(`/accounts/${id}/login`)
export const loginCaptcha = (id, payload) => http.post(`/accounts/${id}/login/captcha`, payload)
export const loginCode = (id, code) => http.post(`/accounts/${id}/login/code`, { code })
export const loginCancel = (id) => http.delete(`/accounts/${id}/login`)
export const startSyncFriends = (id) => http.post(`/accounts/${id}/sync-friends`)
export const getJobStatus = (jobId) => http.get(`/jobs/${jobId}`)
export const getLogs = (params) => http.get('/logs', { params })
export const clearLogs = (accountId) => http.delete('/logs', { params: accountId ? { account_id: accountId } : {} })
export const getStats = () => http.get('/dashboard/stats')
export const getSetupState = () => http.get('/auth/setup-state')
export const setupAuth = (data) => http.post('/auth/setup', data)
export const login = (data) => http.post('/auth/login', data)
export const logout = () => http.post('/auth/logout')
export const getMe = () => http.get('/auth/me')

export default http
