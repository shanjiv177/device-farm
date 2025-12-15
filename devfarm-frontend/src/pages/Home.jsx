import React from 'react'
import { listBranches, triggerPipeline, pipelineStatus, getPipelineJobs } from '../services/gitlab.js'
import { listAvdStatuses, listEmulators, startEmulator, stopEmulator, installApp } from '../services/android.js'
import { listBuilds } from '../services/gitlab.js'
import { listDevices as listIosDevices } from '../services/ios.js'
import { Link } from 'react-router-dom'

export default function Home() {
  const [branches, setBranches] = React.useState([])
  const [branch, setBranch] = React.useState('')
  const [platform, setPlatform] = React.useState('android')
  const [lastPipeline, setLastPipeline] = React.useState(null)
  const [pipelineStatusState, setPipelineStatusState] = React.useState(null)
  // const [jobs, setJobs] = React.useState([])
  // Builds UI moved to Builds.jsx

  const [devicePlatform, setDevicePlatform] = React.useState('android')
  const [androidAvds, setAndroidAvds] = React.useState([]) // [{ avd_name, running_serials, running }]
  const [iosDevices, setIosDevices] = React.useState([])
  const [runningEmulators, setRunningEmulators] = React.useState([]) // [{ avd_name, serial }]
  const [latestAndroidApk, setLatestAndroidApk] = React.useState(null)

  React.useEffect(() => {
    (async () => {
      try {
        const b = await listBranches(63)
        const list = b?.branches || []
        setBranches(list)
        setBranch(list[0]?.name || '')
      } catch (e) { console.error('listBranches error', e) }
      // Builds listing removed from Home; handled in Builds.jsx
      try {
        const avdsRes = await listAvdStatuses()
        setAndroidAvds(avdsRes?.avds || [])
      } catch (e) { console.error('listAvdStatuses error', e) }
      try {
        const emusRes = await listEmulators()
        setRunningEmulators(emusRes?.emulators || [])
      } catch (e) { console.error('listEmulators error', e) }
      try {
        const buildsRes = await listBuilds()
        const androidBuilds = (buildsRes?.builds || []).filter(b => b.platform === 'android' && !!b.artifact_path)
        androidBuilds.sort((a, b) => (b.pipeline_id || 0) - (a.pipeline_id || 0))
        setLatestAndroidApk(androidBuilds[0]?.artifact_path || null)
      } catch (e) { console.error('listBuilds error', e) }
      try {
        const iosRes = await listIosDevices()
        setIosDevices((iosRes?.devices || []).map(d => ({ id: d.udid, name: d.name, state: d.state })))
      } catch (e) { console.error('listIosDevices error', e) }
    })()
  }, [])

  // Periodically refresh AVD status and running emulators
  React.useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const avdsRes = await listAvdStatuses()
        setAndroidAvds(avdsRes?.avds || [])
      } catch { /* ignore */ }
      try {
        const emusRes = await listEmulators()
        setRunningEmulators(emusRes?.emulators || [])
      } catch { /* ignore */ }
    }, 10000)
    return () => clearInterval(interval)
  }, [])

  // Builds polling removed from Home; handled in Builds.jsx

  async function onTrigger() {
    if (!branch) return
    try {
      const res = await triggerPipeline({ branch, platform })
      setLastPipeline(res?.pipeline || res)
      setPipelineStatusState(null)
  // clear jobs UI (not shown)
    } catch (e) { console.error('triggerPipeline error', e) }
  }

  async function refreshStatus() {
    if (!lastPipeline?.id) {
      // Try to infer from latest build if available
      const inferredId = undefined // builds moved to Builds.jsx
      if (!inferredId) {
        console.warn('[Pipelines] refreshStatus skipped: no lastPipeline.id and no builds to infer from')
        return
      }
      console.log('[Pipelines] refreshStatus inferred pipeline_id from builds', inferredId)
      try {
        const s = await pipelineStatus({ pipeline_id: inferredId })
        console.log('[Pipelines] pipelineStatus (inferred)', s)
        setPipelineStatusState(s)
        setLastPipeline({ id: inferredId, status: s?.status })
      } catch (e) { console.error('pipelineStatus error (inferred)', e) }
      return
    }
    try {
      const s = await pipelineStatus({ pipeline_id: lastPipeline.id })
      console.log('[Pipelines] pipelineStatus', s)
      setPipelineStatusState(s)
    } catch (e) { console.error('pipelineStatus error', e) }
  }

  async function refreshJobs() {
    if (!lastPipeline?.id) {
      const inferredId = undefined // builds moved to Builds.jsx
      if (!inferredId) {
        console.warn('[Pipelines] refreshJobs skipped: no lastPipeline.id and no builds to infer from')
        return
      }
      console.log('[Pipelines] refreshJobs inferred pipeline_id from builds', inferredId)
      try {
        const j = await getPipelineJobs({ pipeline_id: inferredId })
        console.log('[Pipelines] jobs (inferred)', j)
      } catch (e) { console.error('getPipelineJobs error (inferred)', e) }
      return
    }
    try {
      const j = await getPipelineJobs({ pipeline_id: lastPipeline.id })
      console.log('[Pipelines] jobs', j)
    } catch (e) { console.error('getPipelineJobs error', e) }
  }

  // Builds refresh removed from Home; handled in Builds.jsx



  // Download gating moved to Builds.jsx

  return (
    <div className="grid grid-cols-[480px_1fr] gap-4">
  {/* Pipelines Panel (builds moved to Builds.jsx) */}
      <div className="bg-white border border-gray-200 rounded-lg p-3">
        <h2 className="text-xl font-semibold mb-3">Pipelines</h2>
        <div className="flex flex-col gap-2">
          <label className="text-sm">Branch</label>
          <select className="px-3 py-2 border border-gray-300 rounded-md" value={branch} onChange={e => setBranch(e.target.value)}>
            {branches.map(b => <option key={b.name} value={b.name}>{b.name}</option>)}
          </select>
          <label className="text-sm mt-1">Platform</label>
          <div className="flex gap-2">
            <button className={`px-3 py-2 rounded-md border cursor-pointer ${platform === 'android' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-800 border-gray-300 hover:bg-gray-50'}`} onClick={() => setPlatform('android')}>Android</button>
            <button className={`px-3 py-2 rounded-md border cursor-pointer ${platform === 'ios' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-800 border-gray-300 hover:bg-gray-50'}`} onClick={() => setPlatform('ios')}>iOS</button>
          </div>
          <div className="flex gap-2 mt-2">
            <button className="px-3 py-2 rounded-md border cursor-pointer bg-indigo-600 text-white border-indigo-600" onClick={onTrigger}>Trigger Pipeline</button>
            <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={refreshStatus}>Refresh Status</button>
            <button className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200" onClick={refreshJobs}>List Jobs</button>
            {/* Builds actions moved to Builds.jsx */}
          </div>
        </div>
        <div className="mt-4">
          <div className="text-sm">{lastPipeline ? `ID: ${lastPipeline.id} | Status: ${pipelineStatusState?.status || lastPipeline.status || 'unknown'}` : 'No pipeline yet'}</div>
        </div>
      </div>

      {/* Devices Panel */}
      <div className="bg-white border border-gray-200 rounded-lg p-3">
        <h2 className="text-xl font-semibold mb-3">Devices</h2>
        <div className="flex gap-2 mb-2">
          <button className={`px-3 py-2 rounded-md border cursor-pointer ${devicePlatform === 'android' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-800 border-gray-300 hover:bg-gray-50'}`} onClick={() => setDevicePlatform('android')}>Android</button>
          <button className={`px-3 py-2 rounded-md border cursor-pointer ${devicePlatform === 'ios' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-800 border-gray-300 hover:bg-gray-50'}`} onClick={() => setDevicePlatform('ios')}>iOS</button>
        </div>
        <div className="divide-y divide-gray-200">
          {devicePlatform === 'android' ? (
            androidAvds.map(item => (
              <div key={item.avd_name} className="px-2 py-2 hover:bg-gray-50">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium">{item.avd_name}</div>
                    {item.running && (
                      <div className="text-xs text-gray-600">Running: {item.running_serials.join(', ')}</div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {!item.running ? (
                      <button
                        className="px-2 py-1 rounded-md border cursor-pointer bg-white text-gray-800 border-gray-300 hover:bg-gray-100"
                        onClick={async () => {
                          try {
                            await startEmulator(item.avd_name)
                            const avdsRes = await listAvdStatuses()
                            setAndroidAvds(avdsRes?.avds || [])
                          } catch (e) { console.error('startEmulator error', e) }
                        }}
                      >
                        Start
                      </button>
                    ) : (
                      <button
                        className="px-2 py-1 rounded-md border cursor-pointer bg-white text-gray-800 border-gray-300 hover:bg-gray-100"
                        onClick={async () => {
                          try {
                            await stopEmulator(item.avd_name)
                            const avdsRes = await listAvdStatuses()
                            setAndroidAvds(avdsRes?.avds || [])
                          } catch (e) { console.error('stopEmulator error', e) }
                        }}
                      >
                        Stop
                      </button>
                    )}
                    {item.running && latestAndroidApk && (
                      <button
                        className="px-2 py-1 rounded-md border cursor-pointer bg-white text-gray-800 border-gray-300 hover:bg-gray-100"
                        onClick={async () => {
                          try {
                            const res = await installApp({ avd_name: item.avd_name, app_path: latestAndroidApk })
                            alert(res?.message || 'Install requested')
                          } catch (e) {
                            console.error('installApp error', e)
                            alert('Failed to install app')
                          }
                        }}
                      >
                        Install latest APK
                      </button>
                    )}
                    <Link to={`/device/android/${encodeURIComponent(item.avd_name)}`} className="px-2 py-1 rounded-md border cursor-pointer bg-white text-gray-800 border-gray-300 hover:bg-gray-100">Open</Link>
                  </div>
                </div>
              </div>
            ))
          ) : (
            iosDevices.map(d => (
              <Link key={d.id} to={`/device/ios/${encodeURIComponent(d.id)}`} className="block px-2 py-2 hover:bg-gray-50">
                <div className="font-medium">{d.name}</div>
                <div className="text-xs text-gray-600">{d.state}</div>
              </Link>
            ))
          )}
        </div>
      </div>
      {/* Optional: Running Emulators */}
      <div className="bg-white border border-gray-200 rounded-lg p-3 mt-4">
        <h3 className="text-lg font-semibold mb-2">Running Emulators</h3>
        {!runningEmulators.length && <div className="text-sm text-gray-500">None</div>}
        {runningEmulators.map(e => (
          <div key={`${e.serial}-${e.avd_name}`} className="text-sm">
            {e.avd_name} — {e.serial}
          </div>
        ))}
      </div>
    </div>
  )
}
