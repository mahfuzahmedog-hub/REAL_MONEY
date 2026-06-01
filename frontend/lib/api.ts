const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export interface ClipResult {
  index: number
  score: number
  reason: string
  mood: string
  duration: number
  path: string
  filename: string
}

export interface JobStatus {
  progress: number
  stage: string
  clips: ClipResult[]
  error: string | null
  download_path: string | null
  done: boolean
}

export interface HealthStatus {
  status: string
  groq_configured: boolean
  music_tracks: Record<string, number>
}

export async function checkHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) throw new Error("Backend offline")
  return res.json()
}

export async function startProcessing(url: string): Promise<string> {
  const res = await fetch(`${API_BASE}/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    let msg = "Failed to start processing"
    try { const body = await res.json(); if (body.detail) msg = body.detail } catch {}
    throw new Error(msg)
  }
  const data = await res.json()
  return data.job_id
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/status/${jobId}`)
  if (!res.ok) throw new Error("Failed to get status")
  return res.json()
}

export function getDownloadUrl(jobId: string): string {
  return `${API_BASE}/download/${jobId}`
}

export function triggerDownload(url: string, filename: string) {
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.style.display = "none"
  document.body.appendChild(a)
  a.click()
  setTimeout(() => document.body.removeChild(a), 1000)
}
