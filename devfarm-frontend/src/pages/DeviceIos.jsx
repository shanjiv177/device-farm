import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { openLogStream as openIosLogs, installApp as installIosApp, startSimulator, stopSimulator, deleteSimulator, getDeviceInfo } from '../services/ios.js'
import { listArtifacts } from '../services/gitlab.js'

// Memoized canvas wrapper to isolate the stream from React re-renders (e.g., logs)
const VideoCanvas = React.memo(function VideoCanvas({
  canvasRef,
  onMouseDown,
  onMouseUp,
  onMouseMove,
  onMouseLeave,
  onTouchStart,
  onTouchEnd,
  onTouchMove,
  onTouchCancel,
}) {
  return (
    <div className="bg-black rounded-md overflow-hidden flex justify-center items-center" style={{ height: '75vh', width: '100%' }}>
      <canvas
        ref={canvasRef}
        className="cursor-crosshair block"
        style={{ height: '100%', width: 'auto', maxWidth: '100%', objectFit: 'contain' }}
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        onMouseMove={onMouseMove}
        onMouseLeave={onMouseLeave}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
        onTouchMove={onTouchMove}
        onTouchCancel={onTouchCancel}
      />
    </div>
  )
})

export default function DeviceIos() {
  const { udid } = useParams()
  const canvasRef = useRef(null)
  const wsRef = useRef(null)
  const logWsRef = useRef(null)
  const [logs, setLogs] = useState('')
  const [artifacts, setArtifacts] = useState([])
  const [selectedArtifact, setSelectedArtifact] = useState(null)
  const [deviceInfo, setDeviceInfo] = useState(null)
  const pendingBlobRef = useRef(null)
  const rafIdRef = useRef(null)
  const frameQueueRef = useRef([]) // small queue to avoid lag
  const renderingRef = useRef(false)
  const lastFrameTsRef = useRef(0)
  const decodeInFlightRef = useRef(false)
  const ctxRef = useRef(null)
  const logBufferRef = useRef([])
  const logFlushTimerRef = useRef(null)
  const isDownRef = useRef(false)

  const refreshArtifacts = useCallback(async () => {
    try {
      const data = await listArtifacts()
      setArtifacts(data?.artifacts || [])
    } catch (e) { console.error('listArtifacts error', e) }
  }, [])

  useEffect(() => {
    const id = setTimeout(() => { refreshArtifacts() }, 0)
    return () => clearTimeout(id)
  }, [refreshArtifacts])

  function stopStream() {
    console.log('[iOS] Stop stream requested')
    if (wsRef.current) { 
      try { wsRef.current.close() } catch (err) { console.debug('ws close err', err) } 
      wsRef.current = null 
    }
    if (rafIdRef.current) { 
      cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null 
    }
    pendingBlobRef.current = null
    const ctx = canvasRef.current?.getContext('2d')
    if (ctx) ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height)
  }

  function stopLogs() {
    if (logWsRef.current) { 
      try { logWsRef.current.close() } catch (err) { console.debug('log ws close err', err) } 
      logWsRef.current = null 
    }
    if (logFlushTimerRef.current) {
      try { clearInterval(logFlushTimerRef.current) } catch { /* ignore */ }
      logFlushTimerRef.current = null
    }
    setLogs(l => l + `[System] Log stream stopped\n`)
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopStream()
      stopLogs()
    }
  }, [])

  function startStream() {
    stopStream()
    console.log('[iOS] Opening video stream for', udid)

    // Fetch device info to lock canvas to physical pixel size
    getDeviceInfo(udid).then(info => {
      if (info && info.width_pixels && info.height_pixels) {
        setDeviceInfo(info)
        const canvasEl = canvasRef.current
        if (canvasEl) {
          // Set intrinsic size (controls createImageBitmap scale and touch mapping)
          canvasEl.width = info.width_pixels
          canvasEl.height = info.height_pixels
        }
      }
    }).catch(() => {})
    
    const BACKEND = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
    const protocol = BACKEND.startsWith('https') ? 'wss:' : 'ws:'
    const host = BACKEND.replace(/^https?:\/\//, '')
    const url = `${protocol}//${host}/device-manager/ios/stream/${encodeURIComponent(udid)}`
    
    console.log('[iOS] Connecting to', url)
    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    
    ws.onopen = () => console.log('[iOS] Video WS open')
    ws.onclose = (ev) => console.log('[iOS] Video WS close', ev.code, ev.reason)
    ws.onerror = (e) => console.log('[iOS] Video WS error', e)
    
    ws.onmessage = (ev) => {
      const data = ev.data
      if (data instanceof ArrayBuffer || data instanceof Blob) {
        const blob = (data instanceof Blob) ? data : new Blob([data], { type: 'image/jpeg' })
        const q = frameQueueRef.current
        q.push(blob)
        while (q.length > 2) q.shift()
      } else {
        console.log('[iOS] Received unknown data type', typeof data)
      }
    }
    
    wsRef.current = ws

    const canvasEl = canvasRef.current
    ctxRef.current = canvasEl.getContext('2d', { alpha: false })
    if (ctxRef.current) ctxRef.current.imageSmoothingEnabled = false

    // Start persistent render loop
    renderingRef.current = true
    const renderLoop = () => {
      if (!renderingRef.current) return
      const ctx = ctxRef.current
      const canvas = canvasRef.current
      if (ctx && canvas && !decodeInFlightRef.current) {
        const q = frameQueueRef.current
        if (q.length > 0) {
          const blob = q.pop()
          q.length = 0
          decodeInFlightRef.current = true
          createImageBitmap(blob)
            .then((bitmap) => {
              if (!deviceInfo && (canvas.width !== bitmap.width || canvas.height !== bitmap.height)) {
                canvas.width = bitmap.width
                canvas.height = bitmap.height
              }
              ctx.drawImage(bitmap, 0, 0)
              bitmap.close()
              lastFrameTsRef.current = performance.now()
            })
            .catch((err) => console.error('[iOS] Frame render error', err))
            .finally(() => { decodeInFlightRef.current = false })
        }
      }
      rafIdRef.current = requestAnimationFrame(renderLoop)
    }
    rafIdRef.current = requestAnimationFrame(renderLoop)
  }

  function startLogs() {
    if (logWsRef.current) { try { logWsRef.current.close() } catch (err) { console.debug('log ws close err', err) } }
    const ws = openIosLogs(udid)
    ws.onopen = () => { console.log('[iOS] Log WS open'); setLogs(l => l + `[System] Log stream connected\n`)}
    ws.onmessage = (ev) => { logBufferRef.current.push(ev.data) }
    ws.onerror = (e) => console.log('[iOS] Log WS error', e)
    ws.onclose = () => console.log('[iOS] Log WS close')
    logWsRef.current = ws

    // Start throttled flush if not already
    if (!logFlushTimerRef.current) {
      logFlushTimerRef.current = setInterval(() => {
        if (logBufferRef.current.length) {
          const chunk = logBufferRef.current.join('\n') + '\n'
          logBufferRef.current = []
          setLogs((l) => l + chunk)
        }
      }, 100)
    }
  }

  async function onBoot() { await startSimulator(udid) }
  async function onShutdown() { await stopSimulator(udid) }
  async function onDelete() { await deleteSimulator(udid) }

  async function onInstall() {
    if (!selectedArtifact) { alert('Select an artifact first'); return }
    const app_path = selectedArtifact.path
    const res = await installIosApp({ udid, app_path })
    alert(res?.message || 'Install requested')
  }

  // Input handling
  const sendTouch = (action, event) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return

    const canvas = canvasRef.current
    const rect = canvas.getBoundingClientRect()
    
    let clientX, clientY
    if (event.touches && event.touches.length > 0) {
        clientX = event.touches[0].clientX
        clientY = event.touches[0].clientY
    } else if (event.changedTouches && event.changedTouches.length > 0) {
        clientX = event.changedTouches[0].clientX
        clientY = event.changedTouches[0].clientY
    } else {
        clientX = event.clientX
        clientY = event.clientY
    }

    const x = clientX - rect.left
    const y = clientY - rect.top
    
    const w = canvas.width
    const h = canvas.height
    const dw = rect.width
    const dh = rect.height
    
    if (dw === 0 || dh === 0 || !w || !h) return

    const scaledX = (x / dw) * w
    const scaledY = (y / dh) * h

    // send asynchronously to avoid blocking UI thread
    const payload = {
        type: 'touch',
        action: action,
        x: Math.round(scaledX),
        y: Math.round(scaledY)
    }
    try {
      ws.send(JSON.stringify(payload))
    } catch (err) {
      console.debug('touch send error', err)
    }
  }

  const handleMouseDown = (e) => { isDownRef.current = true; sendTouch(0, e) }
  const handleMouseUp = (e) => { isDownRef.current = false; sendTouch(1, e) }
  const handleMouseMove = (e) => { if (isDownRef.current) sendTouch(2, e) }
  const handleMouseLeave = (e) => { if (isDownRef.current) { isDownRef.current = false; sendTouch(1, e) } }
  
  const handleTouchStart = (e) => { e.preventDefault(); sendTouch(0, e) }
  const handleTouchEnd = (e) => { e.preventDefault(); sendTouch(1, e) }
  const handleTouchMove = (e) => { e.preventDefault(); sendTouch(2, e) }
  const handleTouchCancel = (e) => { e.preventDefault(); sendTouch(1, e) }

  const sendHome = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({ type: 'home' }))
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">iOS Device — {udid}</h2>
      <div className="grid grid-cols-[1fr_350px] gap-4">
        <div className="bg-neutral-900 rounded-lg p-3 flex flex-col gap-3">
          <VideoCanvas
            canvasRef={canvasRef}
            onMouseDown={handleMouseDown}
            onMouseUp={handleMouseUp}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            onTouchStart={handleTouchStart}
            onTouchEnd={handleTouchEnd}
            onTouchMove={handleTouchMove}
            onTouchCancel={handleTouchCancel}
          />
          <div className="grid grid-cols-4 gap-2">
            <button className="px-3 py-2 rounded-md border cursor-pointer bg-blue-600 text-white border-blue-600" onClick={startStream}>Stream</button>
            <button className="px-3 py-2 rounded-md border cursor-pointer bg-red-600 text-white border-red-600" onClick={stopStream}>Stop</button>
            <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-600 text-white border-gray-600" onClick={sendHome}>Home</button>
            <button className="px-3 py-2 rounded-md border cursor-pointer" onClick={onBoot}>Boot</button>
          </div>
        </div>

        <div className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-3">
          <div>
            <h3 className="text-lg font-semibold">Controls</h3>
            <div className="grid grid-cols-3 gap-2 mt-2">
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-green-600 text-white border-green-600" onClick={onBoot}>Boot</button>
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-red-600 text-white border-red-600" onClick={onShutdown}>Shutdown</button>
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-red-700 text-white border-red-700" onClick={onDelete}>Delete</button>
            </div>
          </div>

          <div>
            <h3 className="text-lg font-semibold">Install</h3>
            <div className="mt-2">
              <div className="text-sm mb-1">Select Artifact</div>
              <div className="max-h-40 overflow-auto border border-gray-200 rounded-md">
                {artifacts.map(a => (
                  <button key={a.filename} className={`w-full text-left px-2 py-2 cursor-pointer ${selectedArtifact === a ? 'bg-blue-50 border-l-4 border-blue-500' : 'hover:bg-gray-50'}`} onClick={() => setSelectedArtifact(a)}>
                    <div className="font-medium">{a.filename}</div>
                    <div className="text-xs text-gray-600">{a.size_mb} MB</div>
                  </button>
                ))}
                {!artifacts.length && <div className="text-sm text-gray-500 px-2 py-2">No artifacts found</div>}
              </div>
              <div className="grid grid-cols-2 gap-2 mt-2">
                <button className="px-3 py-2 rounded-md border cursor-pointer bg-indigo-600 text-white border-indigo-600" onClick={onInstall}>Boot & Install Selected</button>
                <button className="px-3 py-2 rounded-md border cursor-pointer bg-indigo-600 text-white border-indigo-600" onClick={onInstall}>Install Selected</button>
                <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={refreshArtifacts}>Refresh Artifacts</button>
              </div>
            </div>
          </div>

          <div className="flex-1 flex flex-col">
            <h3 className="text-lg font-semibold">Logs</h3>
            <div className="grid grid-cols-3 gap-2 mt-2">
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={startLogs}>Start Logs</button>
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={stopLogs}>Stop Logs</button>
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={() => setLogs('')}>Clear</button>
            </div>
            <div className="mt-2 flex-1 bg-neutral-900 text-green-400 text-xs font-mono p-2 rounded-md overflow-auto" style={{ whiteSpace: 'pre-wrap' }}>{logs}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
