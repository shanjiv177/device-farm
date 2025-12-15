import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { openLogStream as openAndroidLogs, openVideoStream as openAndroidVideo, installApp as installAndroidApp, startEmulator, stopEmulator, deleteAvd, getDeviceInfo } from '../services/android.js'
import { createAndroidJMuxer } from '../services/streamer.js'
import { listArtifacts } from '../services/gitlab.js'

export default function DeviceAndroid() {
  const { avdName } = useParams()
  const videoRef = useRef(null)
  const jmuxerRef = useRef(null)
  const wsRef = useRef(null)
  const logWsRef = useRef(null)
  const [logs, setLogs] = useState('')
  const [artifacts, setArtifacts] = useState([])
  const [selectedArtifact, setSelectedArtifact] = useState(null)
  const [deviceInfo, setDeviceInfo] = useState(null)

  const refreshArtifacts = useCallback(async () => {
    try {
      const data = await listArtifacts()
      setArtifacts(data?.artifacts || [])
    } catch (e) { console.error('listArtifacts error', e) }
  }, [])

  useEffect(() => {
    // Fetch artifacts on mount (defer to next tick)
    const id = setTimeout(() => { refreshArtifacts() }, 0)
    return () => clearTimeout(id)
  }, [refreshArtifacts])

  function startStream() {
    stopStream()
    const videoEl = videoRef.current
    videoEl.classList.remove('hidden')
    jmuxerRef.current = createAndroidJMuxer('player')
    wsRef.current = openAndroidVideo(avdName, (data) => {
      try {
        const arr = new Uint8Array(data)
        jmuxerRef.current?.feed({ video: arr })
        // Constrain to device resolution if available via metadata
        // Prefer backend-reported device pixels
        if (deviceInfo?.width && deviceInfo?.height) {
          // Intrinsic size is handled by video element automatically
        } else if (videoEl.videoWidth && videoEl.videoHeight) {
          // Intrinsic size is handled by video element automatically
        }
      } catch (e) { console.error('JMuxer feed error', e) }
    })

    // Fetch device info to ensure correct sizing
    getDeviceInfo(avdName).then((info) => {
      setDeviceInfo(info)
    }).catch((e) => console.error('getDeviceInfo error', e))

    // Attach pointer/touch handlers to send input events to backend (scrcpy)
    // action: 0=down, 1=up, 2=move
    let isMouseDown = false
    const sendTouch = (action, event) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
      const rect = videoEl.getBoundingClientRect()
      let clientX, clientY
      if (event.touches?.length) {
        clientX = event.touches[0].clientX
        clientY = event.touches[0].clientY
      } else if (event.changedTouches?.length) {
        clientX = event.changedTouches[0].clientX
        clientY = event.changedTouches[0].clientY
      } else {
        clientX = event.clientX
        clientY = event.clientY
      }
      // Map to device pixels if known; else send normalized and let backend scale
      const normX = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      const normY = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height))
      const pxX = (deviceInfo?.width) ? Math.round(normX * deviceInfo.width) : normX
      const pxY = (deviceInfo?.height) ? Math.round(normY * deviceInfo.height) : normY
      const payload = { type: 'touch', action, x: pxX, y: pxY }
      try {
        wsRef.current.send(JSON.stringify(payload))
      } catch (err) {
        console.error('send touch error', err)
      }
    }

    // Mouse
    videoEl.onmousedown = (e) => { isMouseDown = true; sendTouch(0, e) }
    videoEl.onmouseup = (e) => { isMouseDown = false; sendTouch(1, e) }
    videoEl.onmousemove = (e) => { if (isMouseDown) sendTouch(2, e) }
    videoEl.onmouseleave = (e) => { if (isMouseDown) { isMouseDown = false; sendTouch(1, e) } }
    // Touch
    videoEl.ontouchstart = (e) => { e.preventDefault(); sendTouch(0, e) }
    videoEl.ontouchend = (e) => { e.preventDefault(); sendTouch(1, e) }
    videoEl.ontouchmove = (e) => { e.preventDefault(); sendTouch(2, e) }
    videoEl.ontouchcancel = (e) => { e.preventDefault(); sendTouch(1, e) }
  }

  function stopStream() {
  if (wsRef.current) { try { wsRef.current.close() } catch (err) { console.debug('ws close err', err) } wsRef.current = null }
  if (jmuxerRef.current) { try { jmuxerRef.current.destroy() } catch (err) { console.debug('jmuxer destroy err', err) } jmuxerRef.current = null }
    if (videoRef.current) videoRef.current.classList.add('hidden')
    // Remove handlers to avoid leaks
    const videoEl = videoRef.current
    if (videoEl) {
      videoEl.onmousedown = null
      videoEl.onmouseup = null
      videoEl.onmousemove = null
      videoEl.onmouseleave = null
      videoEl.ontouchstart = null
      videoEl.ontouchend = null
      videoEl.ontouchmove = null
      videoEl.ontouchcancel = null
    }
  }

  function startLogs() {
  if (logWsRef.current) { try { logWsRef.current.close() } catch (err) { console.debug('log ws close err', err) } }
    const ws = openAndroidLogs(avdName)
    ws.onopen = () => setLogs(l => l + `[System] Log stream connected\n`)
    ws.onmessage = (ev) => setLogs(l => l + ev.data + '\n')
    logWsRef.current = ws
  }

  function stopLogs() {
  if (logWsRef.current) { try { logWsRef.current.close() } catch (err) { console.debug('log ws close err', err) } logWsRef.current = null }
    setLogs(l => l + `[System] Log stream stopped\n`)
  }

  async function onBoot() { await startEmulator(avdName) }
  async function onShutdown() { await stopEmulator(avdName) }
  async function onDelete() { await deleteAvd(avdName) }

  async function onInstall() {
    if (!selectedArtifact) { alert('Select an artifact first'); return }
    const app_path = selectedArtifact.path
    await startEmulator(avdName)
    const res = await installAndroidApp({ avd_name: avdName, app_path })
    alert(res?.message || 'Install requested')
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Android Device — {avdName}</h2>
      <div className="grid grid-cols-[1fr_350px] gap-4">
        {/* Left: Stream box constrained to device dimensions with logs below */}
        <div className="rounded-lg p-3 flex flex-col gap-3 bg-transparent">
          <div className="grid place-items-center">
            <div
              className="bg-black rounded-md overflow-hidden flex justify-center items-center"
              style={{
                height: '75vh',
                width: '100%'
              }}
            >
              <video 
                id="player" 
                ref={videoRef} 
                autoPlay 
                muted 
                className="hidden" 
                style={{
                  height: '100%',
                  width: 'auto',
                  maxWidth: '100%',
                  objectFit: 'contain'
                }}
              />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <button className="px-3 py-2 rounded-md border cursor-pointer bg-blue-600 text-white border-blue-600" onClick={startStream}>Connect Stream</button>
            <button className="px-3 py-2 rounded-md border cursor-pointer bg-red-600 text-white border-red-600" onClick={stopStream}>Disconnect</button>
            <button className="px-3 py-2 rounded-md border cursor-pointer" onClick={onBoot}>Boot</button>
          </div>
          {/* Logs below stream */}
          <div className="flex-1 flex flex-col max-w-[800px] max-h-[400px]">
            <h3 className="text-lg font-semibold">Logs</h3>
            <div className="grid grid-cols-3 gap-2 mt-2">
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={startLogs}>Start Logs</button>
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={stopLogs}>Stop Logs</button>
              <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={() => setLogs('')}>Clear</button>
            </div>
            {logs?.trim().length > 0 && (
              <div className="mt-2 flex-1 bg-neutral-900 text-green-400 text-xs font-mono p-2 rounded-md overflow-auto" style={{ whiteSpace: 'pre-wrap' }}>{logs}</div>
            )}
          </div>
        </div>

        {/* Right: Controls & Install */}
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
                <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={refreshArtifacts}>Refresh Artifacts</button>
              </div>
            </div>
          </div>

          
        </div>
      </div>
    </div>
  )
}
