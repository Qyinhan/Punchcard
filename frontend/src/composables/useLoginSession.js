import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { loginStart, loginStatus, loginCode, loginCaptcha, loginCancel, qrLogin } from '../api'

/**
 * 交互式登录会话状态机（平台无关）。
 *
 * 前端不感知平台，只消费后端登录会话返回的 stage 数据：
 * - initializing / qr / captcha / code / success / failed / device_confirm
 * - 各 stage 的交互数据（qr_image、geetest、device_code、sent）由后端会话驱动
 *
 * @param {object} opts
 * @param {() => Promise<number|null>} opts.getAccountId  确保账户已落库，返回账户 ID
 * @param {() => void} [opts.onSuccess]  登录成功后的回调（如刷新账户列表）
 */
export function useLoginSession({ getAccountId, onSuccess }) {
  const loginStage = ref('') // '' | initializing | qr | captcha | code | device_confirm | success | failed
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

  // 延迟 1.5s 后轮询一次登录会话状态（登录各阶段都是异步推进的）
  const scheduleLoginPoll = () => {
    clearTimeout(loginPollTimer)
    loginPollTimer = setTimeout(pollLogin, 1500)
  }

  // 轮询登录会话状态，按 stage 分支渲染对应交互区（滑块/验证码/成功/失败）
  const pollLogin = async () => {
    const accountId = await getAccountId()
    if (!accountId) return
    try {
      const s = await loginStatus(accountId)
      if (s.stage === 'captcha') {
        loginStage.value = 'captcha'
        loginBusy.value = false
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
        onSuccess?.()
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
          loginHint.value = '请用手机 APP 扫码，扫码后确认登录'
          if (s.qr_image) qrImage.value = 'data:image/png;base64,' + s.qr_image
        }
        scheduleLoginPoll()
      } else if (s.stage === 'device_confirm') {
        // 新设备登录二次验证：需要用户在手机 APP 中确认
        codePending.value = false
        loginStage.value = 'device_confirm'
        loginBusy.value = true
        loginHint.value = s.message
          ? `请在手机「APP」中确认登录（${s.message}）`
          : '请在手机 APP 中确认登录，确认后会自动完成…'
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
    const id = await getAccountId()
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

  // B 站流程：先获取极验参数（send_code），前端完成后端发短信（captcha），再输验证码（code）
  const doSmsLoginStart = async (phone) => {
    if (!phone) {
      ElMessage.warning('请先填写登录手机号')
      return
    }
    const id = await getAccountId()
    if (!id) return
    loginBusy.value = true
    loginStage.value = 'initializing'
    loginHint.value = '正在获取极验参数…'
    try {
      await loginStart(id, phone)
      scheduleLoginPoll()
    } catch (err) {
      loginBusy.value = false
      loginHint.value = ''
      ElMessage.error(err.message)
    }
  }

  const doLoginCode = async (accountId) => {
    if (!smsCode.value) {
      ElMessage.warning('请输入短信验证码')
      return
    }
    codePending.value = true
    loginBusy.value = true
    loginStage.value = 'initializing'
    loginHint.value = '正在验证登录…'
    try {
      await loginCode(accountId, smsCode.value)
      scheduleLoginPoll()
    } catch (e) {
      codePending.value = false
      loginBusy.value = false
      loginHint.value = ''
      ElMessage.error(e.message)
    }
  }

  const doLoginCancel = async (accountId) => {
    try {
      if (accountId) await loginCancel(accountId)
    } catch (e) { /* 忽略取消失败 */ }
    resetLoginOps()
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
            const accountId = await getAccountId()
            if (!accountId) return
            await loginCaptcha(accountId, {
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

  return {
    loginStage, loginBusy, loginHint, smsCode, qrImage,
    geetestParams, geetestContainerRef,
    pollLogin, scheduleLoginPoll, doQrLogin, doSmsLoginStart, doLoginCode, doLoginCancel, resetLoginOps,
  }
}
