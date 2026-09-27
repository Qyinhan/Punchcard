// 确认弹框 + 操作执行的通用封装。
// 统一处理「用户取消」（catch 静默返回）和「操作失败」（ElMessage.error）两种分支，
// 避免在各视图中重复写双层 try/catch 模式。

import { ElMessage, ElMessageBox } from 'element-plus'

/**
 * 弹出确认对话框，确认后执行操作，成功则显示成功提示。
 *
 * @param {string} message - 确认框内容文案
 * @param {Function} action - 确认后执行的异步操作
 * @param {string} successMsg - 操作成功后显示的提示文案
 * @param {string} [title='提示'] - 确认框标题
 */
export async function confirmAction(message, action, successMsg, title = '提示') {
  try {
    await ElMessageBox.confirm(message, title, { type: 'warning' })
  } catch {
    return
  }
  try {
    await action()
    ElMessage.success(successMsg)
  } catch (e) {
    ElMessage.error(e.message)
  }
}
