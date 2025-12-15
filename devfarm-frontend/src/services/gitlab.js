const BACKEND = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
const base = `${BACKEND}/gitlab`

export async function getUser() {
  const res = await fetch(`${base}/user`, { credentials: 'include' })
  return res.json()
}

export async function listBranches(project_id = 63) {
  const url = new URL(`${base}/branches`)
  url.searchParams.set('project_id', project_id)
  const res = await fetch(url, { credentials: 'include' })
  return res.json()
}

export async function triggerPipeline({ project_id = 63, branch, platform }) {
  const url = new URL(`${base}/pipeline/trigger`)
  url.searchParams.set('project_id', project_id)
  url.searchParams.set('branch', branch)
  url.searchParams.set('platform', platform)
  const res = await fetch(url, { method: 'POST', credentials: 'include' })
  return res.json()
}

export async function pipelineStatus({ project_id = 63, pipeline_id }) {
  const url = new URL(`${base}/pipeline/status/${pipeline_id}`)
  url.searchParams.set('project_id', project_id)
  const res = await fetch(url, { credentials: 'include' })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`pipelineStatus failed: ${res.status} ${text}`)
  }
  return res.json()
}

export async function downloadBuildArtifact({ pipeline_id, platform, project_id = 63 }) {
  const url = new URL(`${base}/build/${pipeline_id}/download`)
  url.searchParams.set('project_id', project_id)
  url.searchParams.set('platform', platform)
  const res = await fetch(url, { method: 'POST', credentials: 'include' })
  return res.json()
}

export async function listArtifacts() {
  const res = await fetch(`${base}/artifacts`, { credentials: 'include' })
  return res.json()
}

export async function getPipelineJobs({ project_id = 63, pipeline_id }) {
  const url = new URL(`${base}/pipelines/${pipeline_id}/jobs`)
  url.searchParams.set('project_id', project_id)
  const res = await fetch(url, { credentials: 'include' })
  return res.json()
}

export async function listBuilds() {
  const res = await fetch(`${base}/builds`, { credentials: 'include' })
  return res.json()
}
