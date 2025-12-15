const BACKEND = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
export const androidApiBase = `${BACKEND}/device-manager/android`

export async function listAvds() {
  const res = await fetch(`${androidApiBase}/avds`)
  return res.json()
}

export async function listAvdStatuses() {
  const res = await fetch(`${androidApiBase}/avds/status`)
  return res.json()
}

export async function listEmulators() {
  const res = await fetch(`${androidApiBase}/emulators`)
  return res.json()
}

export async function listSystemImages() {
  const res = await fetch(`${androidApiBase}/system-images`)
  return res.json()
}

export async function createAvd({ name, pkg, device_profile }) {
  const res = await fetch(`${androidApiBase}/avd/create?name=${encodeURIComponent(name)}&package=${encodeURIComponent(pkg)}&device_profile=${encodeURIComponent(device_profile)}`, { method: 'POST' })
  return res.json()
}

export async function deleteAvd(name) {
  const res = await fetch(`${androidApiBase}/avd/delete?name=${encodeURIComponent(name)}`, { method: 'DELETE' })
  return res.json()
}

export async function startEmulator(avd_name) {
  const res = await fetch(`${androidApiBase}/emulator/start?avd_name=${encodeURIComponent(avd_name)}`, { method: 'POST' })
  return res.json()
}

export async function stopEmulator(avd_name) {
  const res = await fetch(`${androidApiBase}/emulator/stop?avd_name=${encodeURIComponent(avd_name)}`, { method: 'POST' })
  return res.json()
}

export async function installApp({ avd_name, app_path }) {
  const res = await fetch(`${androidApiBase}/emulator/install-app?avd_name=${encodeURIComponent(avd_name)}&app_path=${encodeURIComponent(app_path)}`, { method: 'POST' })
  return res.json()
}

export async function getDeviceInfo(avd_name) {
  const res = await fetch(`${androidApiBase}/device-info?avd_name=${encodeURIComponent(avd_name)}`)
  return res.json()
}

export function openLogStream(avd_name) {
  const protocol = BACKEND.startsWith('https') ? 'wss:' : 'ws:'
  const host = BACKEND.replace(/^https?:\/\//, '')
  const url = `${protocol}//${host}/device-manager/android/logs/${encodeURIComponent(avd_name)}`
  console.log('[AndroidLogs] Opening WS', { url, avd_name })
  const ws = new WebSocket(url)
  ws.addEventListener('open', () => console.log('[AndroidLogs] WS open'))
  ws.addEventListener('message', (ev) => console.log('[AndroidLogs] WS message', ev.data))
  ws.addEventListener('error', (err) => console.error('[AndroidLogs] WS error', err))
  ws.addEventListener('close', (ev) => console.log('[AndroidLogs] WS close', { code: ev.code, reason: ev.reason }))
  return ws
}

export function openVideoStream(avd_name, onBinaryFrame) {
  const protocol = BACKEND.startsWith('https') ? 'wss:' : 'ws:'
  const host = BACKEND.replace(/^https?:\/\//, '')
  const url = `${protocol}//${host}/device-manager/android/stream/${encodeURIComponent(avd_name)}`
  console.log('[AndroidStream] Opening WS', { url, avd_name })
  const ws = new WebSocket(url)
  ws.binaryType = 'arraybuffer'
  if (typeof onBinaryFrame === 'function') {
    ws.onmessage = (event) => {
      const size = event?.data ? (event.data.byteLength || event.data.size || 0) : 0
      console.log('[AndroidStream] forwarding frame to UI', { size })
      try {
        onBinaryFrame(event.data)
      } catch (e) {
        console.error('[AndroidStream] onBinaryFrame error', e)
      }
    }
  }
  ws.addEventListener('open', () => {
    console.log('[AndroidStream] WS open')
  })
  ws.addEventListener('message', (ev) => {
    const size = ev?.data ? (ev.data.byteLength || ev.data.size || 0) : 0
    console.log('[AndroidStream] WS message', { size, type: typeof ev.data })
  })
  ws.addEventListener('error', (err) => {
    console.error('[AndroidStream] WS error', err)
  })
  ws.addEventListener('close', (ev) => {
    console.log('[AndroidStream] WS close', { code: ev.code, reason: ev.reason })
  })
  return ws
}
