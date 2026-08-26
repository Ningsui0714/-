import { configureDesktopApi } from './api'

export interface DesktopRuntime {
  available: boolean
  ready: boolean
  apiBaseUrl?: string
  desktopToken?: string
  startupError?: string
}

let runtime: DesktopRuntime = { available: false, ready: false }

function isTauriWindow() {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

async function waitForSidecar(apiBaseUrl: string) {
  const healthUrl = `${apiBaseUrl.replace(/\/api\/?$/, '')}/health`
  let lastError: unknown
  // A one-file PyInstaller sidecar may need to unpack its embedded Python
  // runtime on the first launch.  Fifteen seconds was too short on real
  // desktop builds and left the UI pointed at a port that was not ready yet.
  for (let attempt = 0; attempt < 180; attempt += 1) {
    try {
      const response = await fetch(healthUrl)
      if (response.ok) return
      lastError = new Error(`本地服务返回 HTTP ${response.status}`)
    } catch (error) {
      lastError = error
    }
    await new Promise(resolve => window.setTimeout(resolve, 500))
  }
  const detail = lastError instanceof Error ? `：${lastError.message}` : ''
  throw new Error(`本地服务启动超时（90 秒）${detail}`)
}

export async function initializeDesktopRuntime(): Promise<DesktopRuntime> {
  if (!isTauriWindow()) return runtime
  runtime = { available: true, ready: false }
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    const config = await invoke<{ apiBaseUrl: string; desktopToken: string }>('desktop_runtime_config')
    configureDesktopApi(config.apiBaseUrl, config.desktopToken)
    await waitForSidecar(config.apiBaseUrl)
    runtime = {
      available: true,
      ready: true,
      apiBaseUrl: config.apiBaseUrl,
      desktopToken: config.desktopToken,
    }
    document.documentElement.dataset.learnflowDesktop = 'true'
  } catch (error) {
    runtime = {
      available: true,
      ready: false,
      startupError: error instanceof Error ? error.message : '桌面本地服务启动失败',
    }
  }
  window.dispatchEvent(new CustomEvent('learnflow:desktop-runtime-changed'))
  return runtime
}

export function getDesktopRuntime() {
  return runtime
}

export async function chooseWorkspaceDirectory() {
  if (!runtime.available || !runtime.ready) return null
  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({ directory: true, multiple: false })
  return typeof selected === 'string' ? selected : null
}
