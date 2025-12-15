const BACKEND = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
export const iosApiBase = `${BACKEND}/device-manager/ios`

export async function listDevices() {
  const res = await fetch(`${iosApiBase}/devices`)
  return res.json()
}

export async function listDeviceTypes() {
  const res = await fetch(`${iosApiBase}/device-types`)
  return res.json()
}

export async function listRuntimes() {
  const res = await fetch(`${iosApiBase}/runtimes`)
  return res.json()
}

export async function createSimulator({ name, device_type, runtime }) {
  const res = await fetch(`${iosApiBase}/simulator/create?name=${encodeURIComponent(name)}&device_type=${encodeURIComponent(device_type)}&runtime=${encodeURIComponent(runtime)}`, { method: 'POST' })
  return res.json()
}

export async function deleteSimulator(udid) {
  const res = await fetch(`${iosApiBase}/simulator/delete?udid=${encodeURIComponent(udid)}`, { method: 'DELETE' })
  return res.json()
}

export async function startSimulator(udid) {
  const res = await fetch(`${iosApiBase}/simulator/start?udid=${encodeURIComponent(udid)}`, { method: 'POST' })
  return res.json()
}

export async function stopSimulator(udid) {
  const res = await fetch(`${iosApiBase}/simulator/stop?udid=${encodeURIComponent(udid)}`, { method: 'POST' })
  return res.json()
}

export async function installApp({ udid, app_path }) {
  const res = await fetch(`${iosApiBase}/simulator/install-app?udid=${encodeURIComponent(udid)}&app_path=${encodeURIComponent(app_path)}`, { method: 'POST' })
  return res.json()
}

export function openLogStream(udid) {
  const protocol = BACKEND.startsWith('https') ? 'wss:' : 'ws:'
  const host = BACKEND.replace(/^https?:\/\//, '')
  const url = `${protocol}//${host}/device-manager/ios/logs/${encodeURIComponent(udid)}`
  return new WebSocket(url)
}

export function openVideoStream(udid, onData) {
  const protocol = BACKEND.startsWith('https') ? 'wss:' : 'ws:'
  const host = BACKEND.replace(/^https?:\/\//, '')
  const url = `${protocol}//${host}/device-manager/ios/stream/${encodeURIComponent(udid)}`
  const ws = new WebSocket(url)
  ws.binaryType = 'arraybuffer'
  // Forward binary frame data to the provided callback
  ws.onmessage = (ev) => {
    if (typeof onData === 'function') {
      onData(ev.data)
    }
  }
  ws.onerror = (err) => {
    // Keep it quiet but log for debugging purposes
    console.debug('iOS video ws error', err)
  }
  return ws
}

export async function getDeviceInfo(udid) {
  const res = await fetch(`${iosApiBase}/device-info?udid=${encodeURIComponent(udid)}`)
  return res.json()
}
