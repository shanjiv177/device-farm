import JMuxer from 'jmuxer'
const BACKEND = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'

export function createAndroidJMuxer(videoElementId = 'player') {
  console.log('[JMuxer] Creating instance', { videoElementId })
  const jmuxer = new JMuxer({
    node: videoElementId,
    mode: 'video',
    flushingTime: 0,
    fps: 60,
    debug: false,
    onError: function (data) {
      console.log('JMuxer buffer error', data)
    }
  })
  console.log('[JMuxer] Instance created')
  return jmuxer
}

export function openAndroidStream(avd_name, onBinaryFrame) {
  const protocol = BACKEND.startsWith('https') ? 'wss:' : 'ws:'
  const host = BACKEND.replace(/^https?:\/\//, '')
  const url = `${protocol}//${host}/device-manager/android/stream/${encodeURIComponent(avd_name)}`
  console.log('[AndroidStream] Opening WS', { url, avd_name })
  const ws = new WebSocket(url)
  ws.binaryType = 'arraybuffer'
  ws.onopen = () => console.log('[AndroidStream] WS open')
  ws.onmessage = (event) => {
    const size = event?.data ? (event.data.byteLength || event.data.size || 0) : 0
    console.log('[AndroidStream] onmessage', { size })
    try {
      onBinaryFrame(event.data)
    } catch (e) {
      console.error('[AndroidStream] onBinaryFrame error', e)
    }
  }
  ws.onerror = (err) => console.error('[AndroidStream] WS error', err)
  ws.onclose = (ev) => console.log('[AndroidStream] WS close', { code: ev.code, reason: ev.reason })
  return ws
}

export function openIosStream(udid, onBinaryFrame) {
  const protocol = BACKEND.startsWith('https') ? 'wss:' : 'ws:'
  const host = BACKEND.replace(/^https?:\/\//, '')
  const url = `${protocol}//${host}/device-manager/ios/stream/${encodeURIComponent(udid)}`
  console.log('[iOSStream] Opening WS', { url, udid })
  const ws = new WebSocket(url)
  ws.binaryType = 'arraybuffer'
  ws.onopen = () => console.log('[iOSStream] WS open')
  ws.onmessage = (event) => {
    const size = event?.data ? (event.data.byteLength || event.data.size || 0) : 0
    console.log('[iOSStream] onmessage', { size })
    try {
      onBinaryFrame(event.data)
    } catch (e) {
      console.error('[iOSStream] onBinaryFrame error', e)
    }
  }
  ws.onerror = (err) => console.error('[iOSStream] WS error', err)
  ws.onclose = (ev) => console.log('[iOSStream] WS close', { code: ev.code, reason: ev.reason })
  return ws
}
