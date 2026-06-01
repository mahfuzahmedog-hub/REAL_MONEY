"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { startProcessing, getJobStatus, getDownloadUrl, type ClipResult, type JobStatus } from "../lib/api"

const MOOD_EMOJIS: Record<string, string> = {
  hype: "\u26A1",
  chill: "\uD83C\uDF43",
  emotional: "\uD83D\uDC94",
  funny: "\uD83D\uDE02",
  serious: "\uD83D\uDCA1",
}

const STAGE_LABELS: Record<string, string> = {
  downloading: "Downloading video...",
  transcribing: "Transcribing audio...",
  analyzing: "AI analyzing best moments...",
  clipping: "Creating clips...",
  done: "Done!",
  error: "Error occurred",
}

export default function Home() {
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  const pollStatus = useCallback(async (id: string) => {
    const status = await getJobStatus(id)
    setJobStatus(status)

    if (status.done || status.error) {
      if (intervalRef.current) clearInterval(intervalRef.current)
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return

    setLoading(true)
    setJobStatus(null)
    setJobId(null)

    try {
      const id = await startProcessing(url.trim())
      setJobId(id)
      intervalRef.current = setInterval(() => pollStatus(id), 2000)
    } catch (err) {
      setLoading(false)
      setJobStatus({
        progress: 0,
        stage: "error",
        clips: [],
        error: "Failed to start. Is the backend running?",
        download_path: null,
        done: false,
      })
    }
  }

  const progress = jobStatus?.progress ?? 0
  const stage = jobStatus?.stage ?? "idle"
  const clips = jobStatus?.clips ?? []
  const error = jobStatus?.error

  const moodColor = (mood: string) => {
    const colors: Record<string, string> = {
      hype: "text-yellow-400",
      chill: "text-blue-400",
      emotional: "text-pink-400",
      funny: "text-green-400",
      serious: "text-purple-400",
    }
    return colors[mood] || "text-gray-400"
  }

  return (
    <main style={{
      maxWidth: "720px",
      margin: "0 auto",
      padding: "40px 20px",
    }}>
      <div style={{ textAlign: "center", marginBottom: "40px" }}>
        <h1 style={{
          fontSize: "2.5rem",
          fontWeight: 800,
          letterSpacing: "-0.02em",
          background: "linear-gradient(135deg, #d4a853, #f5d78e)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          marginBottom: "8px",
        }}>
          REAL MONEY
        </h1>
        <p style={{ color: "#888", fontSize: "0.95rem" }}>
          Paste a YouTube link. Get viral-ready shorts.
        </p>
      </div>

      <form onSubmit={handleSubmit} style={{ marginBottom: "32px" }}>
        <div style={{
          display: "flex",
          gap: "8px",
          background: "#121212",
          border: "1px solid #2a2a3a",
          borderRadius: "12px",
          padding: "4px",
        }}>
          <input
            type="url"
            placeholder="https://youtube.com/watch?v=..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={loading}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              padding: "14px 16px",
              color: "#e0e0e0",
              fontSize: "0.95rem",
              outline: "none",
            }}
          />
          <button
            type="submit"
            disabled={loading || !url.trim()}
            style={{
              padding: "12px 28px",
              borderRadius: "10px",
              border: "none",
              background: loading ? "#333" : "linear-gradient(135deg, #d4a853, #c49a3c)",
              color: loading ? "#666" : "#0a0a0a",
              fontWeight: 700,
              fontSize: "0.9rem",
              cursor: loading ? "not-allowed" : "pointer",
              transition: "all 0.2s",
            }}
          >
            {loading ? "Processing..." : "Generate"}
          </button>
        </div>
      </form>

      {loading && (
        <div style={{
          background: "#121212",
          border: "1px solid #2a2a3a",
          borderRadius: "12px",
          padding: "24px",
          marginBottom: "24px",
        }}>
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            marginBottom: "12px",
            fontSize: "0.85rem",
          }}>
            <span style={{ color: "#888" }}>
              {STAGE_LABELS[stage] || stage}
            </span>
            <span style={{ color: "#d4a853", fontWeight: 600 }}>{progress}%</span>
          </div>
          <div style={{
            width: "100%",
            height: "6px",
            background: "#2a2a3a",
            borderRadius: "3px",
            overflow: "hidden",
          }}>
            <div style={{
              width: `${progress}%`,
              height: "100%",
              background: "linear-gradient(90deg, #d4a853, #f5d78e)",
              borderRadius: "3px",
              transition: "width 0.5s ease",
            }} />
          </div>
        </div>
      )}

      {error && !loading && (
        <div style={{
          background: "#1a0a0a",
          border: "1px solid #3a1a1a",
          borderRadius: "12px",
          padding: "20px",
          color: "#ff6b6b",
          marginBottom: "24px",
          fontSize: "0.9rem",
        }}>
          {error}
        </div>
      )}

      {clips.length > 0 && (
        <div>
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "16px",
          }}>
            <h2 style={{ color: "#e0e0e0", fontSize: "1.1rem", fontWeight: 600 }}>
              {clips.length} clip{clips.length > 1 ? "s" : ""} ready
            </h2>
            <a
              href={getDownloadUrl(jobId!)}
              download
              style={{
                padding: "10px 24px",
                borderRadius: "10px",
                border: "none",
                background: "linear-gradient(135deg, #00c853, #00a844)",
                color: "#fff",
                fontWeight: 700,
                fontSize: "0.85rem",
                textDecoration: "none",
                cursor: "pointer",
              }}
            >
              Download All (ZIP)
            </a>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {clips.map((clip) => (
              <div key={clip.index} style={{
                background: "#121212",
                border: "1px solid #2a2a3a",
                borderRadius: "12px",
                padding: "16px",
              }}>
                <div style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  marginBottom: "8px",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: "28px",
                      height: "28px",
                      borderRadius: "50%",
                      background: "#d4a853",
                      color: "#0a0a0a",
                      fontWeight: 700,
                      fontSize: "0.8rem",
                    }}>
                      {clip.index}
                    </span>
                    <span className={moodColor(clip.mood)}>
                      {MOOD_EMOJIS[clip.mood] || ""} {clip.mood}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                    <span style={{ color: "#888", fontSize: "0.85rem" }}>
                      {clip.duration}s
                    </span>
                    <span style={{
                      color: clip.score >= 80 ? "#00c853" : clip.score >= 60 ? "#d4a853" : "#888",
                      fontWeight: 700,
                      fontSize: "0.9rem",
                    }}>
                      {clip.score}
                    </span>
                  </div>
                </div>
                <p style={{ color: "#aaa", fontSize: "0.85rem", lineHeight: 1.4 }}>
                  {clip.reason}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </main>
  )
}
