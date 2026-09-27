import { ref } from 'vue'
import { getSetupState, getMe, login as loginApi, logout as logoutApi, setupAuth } from '../api'

const user = ref(null)
const setupRequired = ref(false)
const checked = ref(false)

export function useAuth() {
  const init = async () => {
    try {
      const st = await getSetupState()
      setupRequired.value = st.setup_required
      if (!st.setup_required) {
        try {
          user.value = await getMe()
        } catch (e) {
          user.value = null
        }
      }
    } catch (e) {
      // 后端不可达等场景：放行，让具体页面报错
    }
    checked.value = true
  }

  const _afterAuth = async () => {
    user.value = await getMe()
    setupRequired.value = false
  }

  const login = async (username, password) => {
    await loginApi({ username, password })
    await _afterAuth()
  }

  const setup = async (username, password) => {
    await setupAuth({ username, password })
    await _afterAuth()
  }

  const logout = async () => {
    try {
      await logoutApi()
    } catch (e) {
      // 忽略登出接口异常，本地状态照常清理
    }
    user.value = null
  }

  return { user, setupRequired, checked, init, login, setup, logout }
}
