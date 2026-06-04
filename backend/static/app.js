// Islamic Hedayet - SPA logic
// Hash router, API client, views (form, job, settings), dark mode, toast.

const $app = document.getElementById("app");
const $toastContainer = document.getElementById("toast-container");
const $themeToggle = document.getElementById("theme-toggle");

const NICHES = ["islamic", "general", "comedy", "tech", "education", "gaming", "motivation", "lifestyle", "news", "music", "fitness"];

const API = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  },
  startProcess: (url, niche, quickMode, brandText) =>
    API.post("/api/process", { url, niche, quick_mode: quickMode, brand_text: brandText }),
  status: (jobId) => API.get(`/api/status/${jobId}`),
  cancel: (jobId) => API.post(`/api/cancel/${jobId}`),
  health: () => API.get("/api/health"),
  igStatus: () => API.get("/api/instagram/status"),
  igLogin: (username, password, code) =>
    API.post("/api/instagram/login", { username, password, code: code || null }),
  igLogout: () => API.post("/api/instagram/logout", {}),
  igPost: (jobId, index, caption) =>
    API.post(`/api/instagram/post/${jobId}/${index}`, { caption: caption || null }),
};

function toast(msg, kind) {
  const el = document.createElement("div");
  el.className = `toast ${kind || "info"}`;
  el.textContent = msg;
  $toastContainer.appendChild(el);
  setTimeout(() => el.classList.add("show"), 10);
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

function formatBytes(n) {
  if (n > 1e9) return (n / 1e9).toFixed(2) + " GB";
  if (n > 1e6) return (n / 1e6).toFixed(1) + " MB";
  if (n > 1e3) return (n / 1e3).toFixed(1) + " KB";
  return n + " B";
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

// ---------- Views ----------

function viewForm() {
  return `
    <div class="container">
      <h1>Generate Reels</h1>
      <p class="tagline">Paste a YouTube URL, get 15-60s vertical clips with AI-matched music, burned-in subtitles, and per-clip viral metadata.</p>

      <form id="gen-form" class="card">
        <label>
          <span>YouTube URL</span>
          <input id="url" type="text" required
            placeholder="https://www.youtube.com/watch?v=..." />
        </label>

        <label>
          <span>Niche</span>
          <select id="niche">
            ${NICHES.map((n) => `<option value="${n}"${n === "islamic" ? " selected" : ""}>${n}</option>`).join("")}
          </select>
        </label>

        <label class="row">
          <input id="quick" type="checkbox" checked />
          <span>Quick mode (recommended for videos &gt; 20 min)</span>
        </label>

        <label>
          <span>Brand watermark (optional)</span>
          <input id="brand" type="text" placeholder="Leave blank for 'Islamic Hedayet'" />
        </label>

        <button id="start-btn" type="submit" class="primary">Generate Reels</button>
        <div id="start-error" class="error" hidden></div>
      </form>
    </div>
  `;
}

function viewJob(jobId) {
  return `
    <div class="container">
      <h1>Job <code>${escapeHtml(jobId)}</code></h1>
      <a class="back-link" href="#/">&larr; New job</a>

      <div class="card">
        <div class="progress-row">
          <div class="progress-bar"><div id="progress-fill" class="progress-fill" style="width:0%"></div></div>
          <span id="progress-text" class="progress-text">0%</span>
        </div>
        <p id="stage-text" class="stage-text">Starting...</p>
        <div id="error-box" class="error" hidden></div>
        <div class="job-actions">
          <button id="cancel-btn" class="secondary">Cancel</button>
          <a id="zip-link" class="primary hidden" href="/api/download/${encodeURIComponent(jobId)}" download>Download all (ZIP)</a>
        </div>
      </div>

      <div id="source-info" class="card hidden">
        <h3>Source</h3>
        <p id="source-title"></p>
        <p id="source-channel" class="muted"></p>
      </div>

      <div id="clips-container"></div>
    </div>
  `;
}

function viewSettings() {
  return `
    <div class="container">
      <h1>Settings</h1>
      <a class="back-link" href="#/">&larr; Back</a>

      <div class="card">
        <h3>Theme</h3>
        <p class="muted">Toggle dark mode.</p>
        <button id="theme-toggle-2" class="secondary">Toggle theme</button>
      </div>

      <div class="card" id="ig-card">
        <h3>Instagram</h3>
        <p id="ig-status-text" class="muted">Checking...</p>

        <form id="ig-login-form" class="hidden">
          <label>
            <span>Username</span>
            <input id="ig-username" type="text" required autocomplete="username" />
          </label>
          <label>
            <span>Password</span>
            <input id="ig-password" type="password" required autocomplete="current-password" />
          </label>
          <label>
            <span>2FA code (if prompted)</span>
            <input id="ig-code" type="text" inputmode="numeric" pattern="[0-9]*" />
          </label>
          <button type="submit" class="primary">Log in</button>
          <div id="ig-error" class="error" hidden></div>
        </form>

        <button id="ig-logout-btn" class="secondary hidden">Log out</button>
      </div>

      <div class="card">
        <h3>About</h3>
        <p>Islamic Hedayet &mdash; local AI pipeline for Islamic YouTube-to-Reels.</p>
        <p class="muted">Free, local, no subscriptions.</p>
      </div>
    </div>
  `;
}

// ---------- Routing ----------

function render() {
  const hash = location.hash || "#/";
  if (hash === "#/" || hash === "#") {
    $app.innerHTML = viewForm();
    bindForm();
  } else if (hash.startsWith("#/job/")) {
    const jobId = hash.slice("#/job/".length);
    $app.innerHTML = viewJob(jobId);
    pollJob(jobId);
  } else if (hash === "#/settings") {
    $app.innerHTML = viewSettings();
    bindSettings();
  } else {
    $app.innerHTML = `<div class="container"><h1>Not found</h1><a href="#/">Back</a></div>`;
  }
}

window.addEventListener("hashchange", render);
window.addEventListener("DOMContentLoaded", () => {
  applyTheme();
  render();
});

// ---------- Form binding ----------

function bindForm() {
  const f = document.getElementById("gen-form");
  const err = document.getElementById("start-error");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    const url = document.getElementById("url").value.trim();
    const niche = document.getElementById("niche").value;
    const quickMode = document.getElementById("quick").checked;
    const brandText = document.getElementById("brand").value.trim();
    const btn = document.getElementById("start-btn");
    btn.disabled = true;
    btn.textContent = "Starting...";
    try {
      const r = await API.startProcess(url, niche, quickMode, brandText);
      location.hash = `#/job/${r.job_id}`;
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
      btn.disabled = false;
      btn.textContent = "Generate Reels";
    }
  });
}

// ---------- Job polling ----------

async function pollJob(jobId) {
  const $fill = document.getElementById("progress-fill");
  const $text = document.getElementById("progress-text");
  const $stage = document.getElementById("stage-text");
  const $err = document.getElementById("error-box");
  const $cancel = document.getElementById("cancel-btn");
  const $zip = document.getElementById("zip-link");
  const $source = document.getElementById("source-info");
  const $sourceTitle = document.getElementById("source-title");
  const $sourceChannel = document.getElementById("source-channel");
  const $clips = document.getElementById("clips-container");

  let lastClips = -1;

  const tick = async () => {
    let d;
    try {
      d = await API.status(jobId);
    } catch (ex) {
      $err.textContent = `Backend error: ${ex.message}`;
      $err.hidden = false;
      return;
    }
    $fill.style.width = `${d.progress || 0}%`;
    $text.textContent = `${d.progress || 0}%`;
    $stage.textContent = d.stage || "Working...";
    if (d.error) {
      $err.textContent = d.error;
      $err.hidden = false;
    } else {
      $err.hidden = true;
    }
    if (d.video_title) {
      $source.classList.remove("hidden");
      $sourceTitle.textContent = d.video_title;
      $sourceChannel.textContent = d.video_channel || "";
    }
    if (d.clips && d.clips.length !== lastClips) {
      lastClips = d.clips.length;
      renderClips(d.clips, $clips, jobId);
    }
    if (d.done) {
      $zip.classList.remove("hidden");
      $cancel.disabled = true;
      $cancel.textContent = "Done";
      $stage.textContent = `Done! ${d.clips.length} clips generated.`;
      toast("Pipeline complete!", "success");
      return;
    }
    if (d.stage === "cancelled") {
      $cancel.disabled = true;
      $cancel.textContent = "Cancelled";
      return;
    }
    setTimeout(tick, 2000);
  };
  tick();

  $cancel.addEventListener("click", async () => {
    try {
      await API.cancel(jobId);
      toast("Cancelled", "info");
    } catch (ex) {
      toast(`Cancel failed: ${ex.message}`, "error");
    }
  });
}

function renderClips(clips, container, jobId) {
  container.innerHTML = clips
    .map((c) => {
      const tags = (c.tags || []).map((t) => `<span class="tag">#${escapeHtml(t)}</span>`).join(" ");
      const index = c.index || 1;
      return `
      <div class="card clip-card">
        <div class="clip-video">
          <video controls preload="none" src="/api/clip/${encodeURIComponent(jobId)}/${index}">
            Your browser does not support video.
          </video>
        </div>
        <div class="clip-meta">
          <h3>${index}. ${escapeHtml(c.title || "")}</h3>
          <p class="muted">${escapeHtml(c.hook_text || "")} &middot; ${c.duration}s &middot; mood: ${escapeHtml(c.mood || "")}</p>
          <p class="tags">${tags}</p>
          <details>
            <summary>Captions</summary>
            <p><strong>Instagram:</strong> ${escapeHtml(c.caption_instagram || "")}</p>
            <p><strong>TikTok:</strong> ${escapeHtml(c.caption_tiktok || "")}</p>
            <p><strong>YouTube:</strong> ${escapeHtml(c.caption_youtube || "")}</p>
          </details>
          <div class="clip-actions">
            <a class="primary" href="/api/clip/${encodeURIComponent(jobId)}/${index}" download="clip_${index}.mp4">Download MP4</a>
            <button class="secondary ig-post-btn" data-index="${index}">Post to Instagram</button>
          </div>
        </div>
      </div>
    `;
    })
    .join("");

  container.querySelectorAll(".ig-post-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const idx = parseInt(btn.dataset.index, 10);
      const clip = clips.find((c) => c.index === idx) || {};
      const caption = clip.caption_instagram || "";
      const modal = openPostModal(jobId, idx, caption, clip.title);
      modal.open();
    });
  });
}

// ---------- IG post modal ----------

function openPostModal(jobId, index, caption, title) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <h3>Post clip ${index} to Instagram</h3>
      <p class="muted">${escapeHtml(title || "")}</p>
      <label>
        <span>Caption</span>
        <textarea id="post-caption" rows="6">${escapeHtml(caption)}</textarea>
      </label>
      <div id="post-status" class="muted"></div>
      <div class="modal-actions">
        <button id="post-cancel" class="secondary">Cancel</button>
        <button id="post-confirm" class="primary">Post</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const $status = overlay.querySelector("#post-status");
  const $confirm = overlay.querySelector("#post-confirm");
  const $cancel = overlay.querySelector("#post-cancel");
  const $caption = overlay.querySelector("#post-caption");

  const close = () => overlay.remove();
  $cancel.addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  return {
    open: () => {},
    confirm: async () => {
      $confirm.disabled = true;
      $status.textContent = "Posting to Instagram...";
      try {
        const r = await API.igPost(jobId, index, $caption.value);
        if (r.ok) {
          $status.innerHTML = `Posted! <a href="${escapeHtml(r.permalink || "#")}" target="_blank">View on Instagram</a>`;
          toast("Posted to Instagram!", "success");
        } else {
          $status.textContent = `Error: ${r.error || "unknown"}`;
          toast(`Post failed: ${r.error || "unknown"}`, "error");
          $confirm.disabled = false;
        }
      } catch (ex) {
        $status.textContent = `Error: ${ex.message}`;
        toast(`Post failed: ${ex.message}`, "error");
        $confirm.disabled = false;
      }
    },
  };
}

// Delegated handler for "Post to Instagram" buttons (set up once)
document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "post-confirm") {
    const overlay = e.target.closest(".modal-overlay");
    if (overlay && overlay._modal) overlay._modal.confirm();
  }
});

// ---------- Settings binding ----------

async function bindSettings() {
  // Theme toggle
  const t2 = document.getElementById("theme-toggle-2");
  if (t2) t2.addEventListener("click", toggleTheme);

  // IG status
  const $igStatus = document.getElementById("ig-status-text");
  const $igForm = document.getElementById("ig-login-form");
  const $igLogout = document.getElementById("ig-logout-btn");
  const $igErr = document.getElementById("ig-error");
  const f = document.getElementById("ig-login-form");

  try {
    const s = await API.igStatus();
    if (s.logged_in) {
      $igStatus.textContent = `Logged in as @${s.username}`;
      $igLogout.classList.remove("hidden");
    } else {
      $igStatus.textContent = "Not logged in.";
      $igForm.classList.remove("hidden");
    }
  } catch (ex) {
    $igStatus.textContent = `Backend error: ${ex.message}. Restart the webapp.`;
  }

  if (f) {
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      $igErr.hidden = true;
      const username = document.getElementById("ig-username").value.trim();
      const password = document.getElementById("ig-password").value;
      const code = document.getElementById("ig-code").value.trim();
      const btn = f.querySelector("button[type=submit]");
      btn.disabled = true;
      btn.textContent = "Logging in...";
      try {
        const r = await API.igLogin(username, password, code);
        if (r.ok) {
          toast("Logged in to Instagram", "success");
          bindSettings();
        } else if (r.requires_2fa) {
          $igErr.textContent = "2FA code required. Enter the code from your authenticator app.";
          $igErr.hidden = false;
          btn.disabled = false;
          btn.textContent = "Verify 2FA";
        } else {
          $igErr.textContent = r.error || "Login failed";
          $igErr.hidden = false;
          btn.disabled = false;
          btn.textContent = "Log in";
        }
      } catch (ex) {
        $igErr.textContent = ex.message;
        $igErr.hidden = false;
        btn.disabled = false;
        btn.textContent = "Log in";
      }
    });
  }

  if ($igLogout) {
    $igLogout.addEventListener("click", async () => {
      try {
        await API.igLogout();
        toast("Logged out", "info");
        bindSettings();
      } catch (ex) {
        toast(`Logout failed: ${ex.message}`, "error");
      }
    });
  }
}

// ---------- Dark mode ----------

function applyTheme() {
  let theme = localStorage.getItem("theme");
  if (!theme) {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  if (theme === "dark") {
    document.documentElement.classList.add("dark");
    if ($themeToggle) $themeToggle.innerHTML = "&#9788;";
  } else {
    document.documentElement.classList.remove("dark");
    if ($themeToggle) $themeToggle.innerHTML = "&#9728;";
  }
}

function toggleTheme() {
  const isDark = document.documentElement.classList.contains("dark");
  if (isDark) {
    document.documentElement.classList.remove("dark");
    localStorage.setItem("theme", "light");
    if ($themeToggle) $themeToggle.innerHTML = "&#9728;";
  } else {
    document.documentElement.classList.add("dark");
    localStorage.setItem("theme", "dark");
    if ($themeToggle) $themeToggle.innerHTML = "&#9788;";
  }
}

if ($themeToggle) {
  $themeToggle.addEventListener("click", toggleTheme);
}

// ---------- Boot ----------

document.addEventListener("DOMContentLoaded", () => {
  applyTheme();
  render();
});
