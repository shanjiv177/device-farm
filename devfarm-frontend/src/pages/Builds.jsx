import React from 'react'
import { listBuilds, pipelineStatus, downloadBuildArtifact } from '../services/gitlab.js'

// Renders a single build card with status polling and download button
function BuildCard({ build }) {
  const [status, setStatus] = React.useState(null)

  // Poll pipeline status every 10s continuously
  React.useEffect(() => {
    let cancelled = false
    async function fetchStatus() {
      try {
        const s = await pipelineStatus({ pipeline_id: build.pipeline_id })
        if (cancelled) return
        setStatus(s)
      } catch (e) {
        console.error('pipelineStatus error', e)
      }
    }
    // initial fetch
    fetchStatus()
    const interval = setInterval(fetchStatus, 10000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [build.pipeline_id])

  const overallSuccess = (status?.status || build.status) === 'success'
  const alreadyDownloaded = !!build.artifact_path
  const downloadLabel = alreadyDownloaded ? 'Re-download Artifact' : 'Download Artifact'

  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold">#{build.pipeline_id}</div>
        <span className={`px-2 py-1 text-xs rounded-md border ${build.platform === 'android' ? 'bg-green-50 text-green-700 border-green-200' : 'bg-indigo-50 text-indigo-700 border-indigo-200'}`}>{build.platform || 'unknown'}</span>
      </div>
      <div className="text-sm text-gray-700 truncate">{build.ref}</div>
      <div className="text-xs text-gray-600 mt-1">Status: {status?.status || build.status || 'unknown'}</div>
      {build.artifact_path && (
        <div className="text-xs text-gray-600 mt-1">Artifact: {build.artifact_path}</div>
      )}
      <div className="mt-3 flex gap-2">
        {build.web_url && (
          <a href={build.web_url} target="_blank" rel="noreferrer" className="px-3 py-2 rounded-md border cursor-pointer bg-blue-600 text-white border-blue-600">Open</a>
        )}
        {overallSuccess && (
          <button
            className="px-3 py-2 rounded-md border cursor-pointer bg-gray-100 hover:bg-gray-200"
            onClick={async () => {
              try {
                const res = await downloadBuildArtifact({ pipeline_id: build.pipeline_id, platform: build.platform })
                alert(res?.message || 'Artifact download requested')
              } catch (e) {
                console.error('downloadBuildArtifact error', e)
                alert('Failed to request artifact download')
              }
            }}
          >
            {downloadLabel}
          </button>
        )}
      </div>
    </div>
  )
}

export default function Builds() {
  const [builds, setBuilds] = React.useState([])

  // Initial fetch and periodic refresh every 10s
  React.useEffect(() => {
    let cancelled = false
    async function fetchBuilds() {
      try {
        const b = await listBuilds()
        console.log(b)
        if (cancelled) return
        setBuilds(b?.builds || [])
      } catch (e) {
        console.error('listBuilds error', e)
      }
    }
    fetchBuilds()
    const interval = setInterval(fetchBuilds, 10000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3">
      <h2 className="text-xl font-semibold mb-3">Builds</h2>
      {!builds.length && <div className="text-sm text-gray-500">No builds yet</div>}
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {builds.map(b => (
          <BuildCard key={`${b.pipeline_id}-${b.platform}`} build={b} />
        ))}
      </div>
    </div>
  )
}
