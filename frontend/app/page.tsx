"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { startProcessing, getJobStatus, getDownloadUrl, checkHealth, cancelProcessing, triggerDownload, type ClipResult, type JobStatus, type HealthStatus } from "../lib/api"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const MOOD_EMOJIS: Record<string, string> = {
  hype: "\u26A1",
  chill: "\uD83C\uDF43",
  emotional: "\uD83D\uDC94",
  funny: "\uD83D\uDE02",
  serious: "\uD83D\uDCA1",
}

const SIGNAL_EMOJIS: Record<string, string> = {
  "SHARE BAIT": "\uD83D\uDCE3",
  "SAVE BAIT": "\uD83D\uDCCB",
  "COMMENT BAIT": "\uD83D\uDCAC",
  "COMPLETION BAIT": "\uD83D\uDC40",
  "LOOP BAIT": "\uD83D\uDD01",
}

const STAGE_LABELS: Record<string, string> = {
  validating: "Checking URL...",
  downloading: "Downloading video...",
  transcribing: "Transcribing audio...",
  analyzing: "AI analyzing best moments...",
  clipping: "Creating clips...",
  done: "Done!",
  error: "Error occurred",
  cancelled: "Cancelled",
}

export default function Home() {
  const [url, setUrl] = useState("")
  const [niche, setNiche] = useState("general")
  const [loading, setLoading] = useState(false)
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [activePlatforms, setActivePlatforms] = useState<Record<number, string>>({})
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    checkHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  const pollStatus = useCallback(async (id: string) => {
    try {
      const status = await getJobStatus(id)
      setJobStatus(status)
      if (status.done || status.error) {
        stopPolling()
        setLoading(false)
      }
    } catch {
      stopPolling()
      setLoading(false)
      setJobStatus({
        progress: 0,
        stage: "error",
        clips: [],
        error: "Lost connection to backend. Make sure it's running on port 8000.",
        download_path: null,
        video_title: null,
        done: false,
      })
    }
  }, [stopPolling])

  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!url.trim()) return

    setLoading(true)
    setJobStatus(null)
    setJobId(null)

    try {
      const id = await startProcessing(url.trim(), niche)
      setJobId(id)
      intervalRef.current = setInterval(() => pollStatus(id), 2000)
    } catch (err: any) {
      setLoading(false)
      const msg = err.message || "Failed to start. Is the backend running on port 8000?"
      setJobStatus({
        progress: 0,
        stage: "error",
        clips: [],
        error: msg,
        download_path: null,
        video_title: null,
        done: false,
      })
    }
  }

  const handleReset = () => {
    stopPolling()
    setLoading(false)
    setJobStatus(null)
    setJobId(null)
  }

  const handleCancel = async () => {
    if (!jobId) return
    try { await cancelProcessing(jobId) } catch {}
  }

  const handleDownload = () => {
    triggerDownload(getDownloadUrl(jobId!), `realmoney_${jobId}.zip`)
  }

  const progress = jobStatus?.progress ?? 0
  const stage = jobStatus?.stage ?? "idle"
  const clips = jobStatus?.clips ?? []
  const error = jobStatus?.error
  const isDone = jobStatus?.done

  const getClipUrl = (jobId: string, index: number) => `${API_BASE}/clip/${jobId}/${index}`

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

  const noGroq = health && !health.groq_configured
  const noMusic = health && Object.values(health.music_tracks).every((c) => c === 0)
  const backendOffline = health === null

  return (
    <main style={{
      maxWidth: "720px",
      margin: "0 auto",
      padding: "40px 20px",
    }}>
      {backendOffline && (
        <div style={{
          background: "#1a0a0a",
          border: "1px solid #3a1a1a",
          borderRadius: "12px",
          padding: "12px 16px",
          color: "#ff6b6b",
          marginBottom: "20px",
          fontSize: "0.85rem",
          textAlign: "center",
        }}>
          Backend offline — start the Python server on port 8000
        </div>
      )}

      {noGroq && (
        <div style={{
          background: "#1a1a0a",
          border: "1px solid #3a3a1a",
          borderRadius: "12px",
          padding: "12px 16px",
          color: "#d4a853",
          marginBottom: "20px",
          fontSize: "0.85rem",
          textAlign: "center",
        }}>
          Groq API key not set — edit backend/.env and restart the server
        </div>
      )}

      {noMusic && !noGroq && !backendOffline && (
        <div style={{
          background: "#0a1a1a",
          border: "1px solid #1a3a3a",
          borderRadius: "12px",
          padding: "12px 16px",
          color: "#00c853",
          marginBottom: "20px",
          fontSize: "0.85rem",
          textAlign: "center",
        }}>
          No music tracks found — run backend/download_music.ps1 or add .mp3 files
        </div>
      )}

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
          marginBottom: "8px",
        }}>
          <input
            type="url"
            placeholder="https://youtube.com/watch?v=..."
            autoFocus
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
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}>
          <label style={{ color: "#888", fontSize: "0.85rem" }}>Niche:</label>
          <select
            value={niche}
            onChange={(e) => setNiche(e.target.value)}
            disabled={loading}
            style={{
              flex: 1,
              background: "#121212",
              border: "1px solid #2a2a3a",
              borderRadius: "8px",
              padding: "8px 12px",
              color: "#e0e0e0",
              fontSize: "0.85rem",
              outline: "none",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            <option value="general">General</option>
            <option value="gaming">Gaming</option>
            <option value="music">Music</option>
            <option value="finance">Finance</option>
            <option value="fitness">Fitness</option>
            <option value="education">Education</option>
            <option value="comedy">Comedy</option>
            <option value="news">News</option>
            <option value="sports">Sports</option>
            <option value="food">Food</option>
          </select>
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
              boxShadow: progress > 0 && progress < 100 ? "0 0 8px rgba(212, 168, 83, 0.4)" : "none",
            }} />
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "12px" }}>
            <button
              onClick={handleCancel}
              style={{
                padding: "6px 14px",
                borderRadius: "6px",
                border: "1px solid #3a1a1a",
                background: "transparent",
                color: "#ff6b6b",
                cursor: "pointer",
                fontSize: "0.8rem",
              }}
            >
              Cancel
            </button>
          </div>
          {progress < 100 && (
            <div className="shimmer" style={{
              height: "2px",
              borderRadius: "1px",
              marginTop: "8px",
            }} />
          )}
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
          <div style={{ marginBottom: "12px" }}>{error}</div>
          <button
            onClick={handleReset}
            style={{
              padding: "8px 20px",
              borderRadius: "8px",
              border: "1px solid #3a1a1a",
              background: "transparent",
              color: "#ff6b6b",
              cursor: "pointer",
              fontSize: "0.85rem",
            }}
          >
            Try another video
          </button>
        </div>
      )}

      {isDone && clips.length > 0 && (
        <div>
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "16px",
          }}>
            <div>
              <h2 style={{ color: "#e0e0e0", fontSize: "1.1rem", fontWeight: 600 }}>
                {clips.length} clip{clips.length > 1 ? "s" : ""} ready
              </h2>
              {jobStatus?.video_title && (
                <p style={{ color: "#666", fontSize: "0.85rem", marginTop: "4px" }}>
                  {jobStatus.video_title}
                </p>
              )}
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button
                onClick={handleDownload}
                style={{
                  padding: "10px 24px",
                  borderRadius: "10px",
                  border: "none",
                  background: "linear-gradient(135deg, #00c853, #00a844)",
                  color: "#fff",
                  fontWeight: 700,
                  fontSize: "0.85rem",
                  cursor: "pointer",
                }}
              >
                Download ZIP
              </button>
              <button
                onClick={handleReset}
                style={{
                  padding: "10px 20px",
                  borderRadius: "10px",
                  border: "1px solid #2a2a3a",
                  background: "transparent",
                  color: "#888",
                  cursor: "pointer",
                  fontSize: "0.85rem",
                }}
              >
                New video
              </button>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {clips.map((clip) => (
              <div key={clip.index} style={{
                background: "#121212",
                border: "1px solid #2a2a3a",
                borderRadius: "12px",
                overflow: "hidden",
              }}>
                {clip.title && (
                  <div style={{ padding: "16px 16px 0 16px" }}>
                    <h3 style={{ color: "#e0e0e0", fontSize: "1rem", fontWeight: 700, margin: 0 }}>
                      {clip.title}
                    </h3>
                  </div>
                )}
                <video
                  src={getClipUrl(jobId!, clip.index)}
                  controls
                  preload="metadata"
                  style={{
                    width: "100%",
                    maxHeight: "400px",
                    display: "block",
                    background: "#000",
                    marginTop: "8px",
                  }}
                />
                <div style={{ padding: "16px" }}>
                  {clip.hook_text && (
                    <div style={{
                      background: "#1a1a0a",
                      borderLeft: "3px solid #d4a853",
                      padding: "8px 12px",
                      marginBottom: "12px",
                      borderRadius: "0 6px 6px 0",
                    }}>
                      <p style={{ color: "#f5d78e", fontSize: "0.95rem", fontWeight: 600, margin: 0, fontStyle: "italic" }}>
                        "{clip.hook_text}"
                      </p>
                    </div>
                  )}
                  <div style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: "8px",
                    flexWrap: "wrap",
                    gap: "6px",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
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
                      {clip.primary_signal && (
                        <span style={{
                          padding: "3px 8px",
                          borderRadius: "4px",
                          background: "#2a2a1a",
                          color: "#d4a853",
                          fontSize: "0.7rem",
                          fontWeight: 600,
                          letterSpacing: "0.5px",
                        }}>
                          {SIGNAL_EMOJIS[clip.primary_signal] || ""} {clip.primary_signal}
                        </span>
                      )}
                      {clip.fallback_mode && (
                        <span style={{
                          padding: "3px 8px",
                          borderRadius: "4px",
                          background: "#2a1a1a",
                          color: "#ff6b6b",
                          fontSize: "0.7rem",
                          fontWeight: 600,
                        }}>
                          ENERGY DETECTED
                        </span>
                      )}
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
                  <p style={{ color: "#aaa", fontSize: "0.85rem", lineHeight: 1.4, marginBottom: "8px" }}>
                    {clip.reason}
                  </p>
                  {clip.tags && clip.tags.length > 0 && (
                    <div style={{ display: "flex", gap: "4px", flexWrap: "wrap", marginBottom: "12px" }}>
                      {clip.tags.map((tag, ti) => (
                        <span key={ti} style={{
                          padding: "2px 8px",
                          borderRadius: "4px",
                          background: "#1a1a2a",
                          color: "#888",
                          fontSize: "0.7rem",
                        }}>
                          #{tag}
                        </span>
                      ))}
                    </div>
                  )}
                  {(clip.caption_instagram || clip.caption_tiktok || clip.caption_youtube) && (() => {
                    const platforms = [
                      { key: "instagram", label: "Instagram", text: clip.caption_instagram },
                      { key: "tiktok", label: "TikTok", text: clip.caption_tiktok },
                      { key: "youtube", label: "YouTube", text: clip.caption_youtube },
                    ].filter(p => p.text)
                    const activeKey = activePlatforms[clip.index] || "instagram"
                    const active = platforms.find(p => p.key === activeKey) || platforms[0]
                    return (
                      <div>
                        <div style={{ display: "flex", gap: "4px", marginBottom: "8px" }}>
                          {platforms.map(p => (
                            <button
                              key={p.key}
                              onClick={() => setActivePlatforms(prev => ({ ...prev, [clip.index]: p.key }))}
                              style={{
                                padding: "4px 12px",
                                borderRadius: "6px",
                                border: "none",
                                background: p.key === activeKey ? "#d4a853" : "#2a2a3a",
                                color: p.key === activeKey ? "#0a0a0a" : "#888",
                                fontWeight: 600,
                                fontSize: "0.75rem",
                                cursor: "pointer",
                              }}
                            >
                              {p.label}
                            </button>
                          ))}
                        </div>
                        <div style={{
                          background: "#0a0a0a",
                          border: "1px solid #2a2a3a",
                          borderRadius: "8px",
                          padding: "10px 12px",
                          position: "relative",
                        }}>
                          <p style={{ color: "#ccc", fontSize: "0.8rem", lineHeight: 1.5, margin: 0, whiteSpace: "pre-wrap" }}>
                            {active.text}
                          </p>
                          <button
                            onClick={() => navigator.clipboard.writeText(active.text)}
                            style={{
                              position: "absolute",
                              top: "6px",
                              right: "6px",
                              padding: "3px 8px",
                              borderRadius: "4px",
                              border: "1px solid #2a2a3a",
                              background: "#121212",
                              color: "#888",
                              fontSize: "0.7rem",
                              cursor: "pointer",
                            }}
                          >
                            Copy
                          </button>
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </main>
  )
}
