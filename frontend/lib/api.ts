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

export async function startProcessing(url: string): Promise<string> {
  const res = await fetch(`${API_BASE}/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) throw new Error("Failed to start processing")
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
