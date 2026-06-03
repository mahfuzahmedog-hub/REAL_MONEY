"""Gradio UI for the REAL_MONEY pipeline.

Launches on port 7860 and talks to the FastAPI backend on port 8000.
This is a thin client - all real work happens in the FastAPI server.

Usage:
    python pipeline_ui.py
"""
import os
import time
import json
import uuid
import asyncio
import requests
import gradio as gr
from gradio_client import utils as _gc_utils
from dotenv import load_dotenv


def _patch_gradio_client_schema() -> None:
    """Work around gradio_client 4.44.1 TypeError on non-dict schema.

    In some pydantic-generated schemas, schema values come through as bool
    (e.g. additionalProperties=True) instead of dict, causing
    `if "const" in schema` to raise TypeError. Guard with isinstance.
    """
    _orig_get_type = _gc_utils.get_type

    def _safe_get_type(schema):
        if not isinstance(schema, dict):
            return "Any"
        return _orig_get_type(schema)

    _gc_utils.get_type = _safe_get_type

    _orig_jsppt = _gc_utils._json_schema_to_python_type

    def _safe_jsppt(schema, defs):
        if not isinstance(schema, (dict, list)):
            return "Any"
        return _orig_jsppt(schema, defs)

    _gc_utils._json_schema_to_python_type = _safe_jsppt


_patch_gradio_client_schema()
load_dotenv()

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
UI_PORT = int(os.getenv("UI_PORT", "7860"))

NICHES = ["islamic", "general", "comedy", "tech", "education", "gaming", "motivation", "lifestyle", "news", "music", "fitness"]

POLL_INTERVAL_S = 2.0


def _fmt_progress(stage: str, progress: int) -> str:
    return f"[{progress:3d}%] {stage}"


def _health_check() -> str:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        if r.status_code == 200:
            d = r.json()
            zen = "yes" if d.get("zen_configured") else "NO - check backend/.env"

            return f"Backend OK | Zen: {zen} | Music: {tracks.get('hype', 0)} hype / {tracks.get('chill', 0)} chill / {tracks.get('sad', 0)} sad / {tracks.get('tense', 0)} tense"
        return f"Backend returned {r.status_code}"
    except requests.exceptions.RequestException as e:
        return f"Backend not reachable at {API_BASE}: {e}"


def start_pipeline(url, niche, quick_mode, brand_text):
    if not url or not url.strip():
        raise gr.Error("Please paste a YouTube URL")
    try:
        r = requests.post(
            f"{API_BASE}/process",
            json={"url": url.strip(), "niche": niche, "quick_mode": bool(quick_mode), "brand_text": brand_text or ""},
            timeout=10,
        )
        r.raise_for_status()
        job_id = r.json()["job_id"]
        return job_id, gr.update(value=_fmt_progress("queued", 0), visible=True)
    except requests.exceptions.RequestException as e:
        raise gr.Error(f"Failed to start: {e}")


def poll_status(job_id):
    if not job_id:
        yield gr.update(value="no job", visible=False), gr.update(value=0), None
        return
    while True:
        try:
            r = requests.get(f"{API_BASE}/status/{job_id}", timeout=10)
            r.raise_for_status()
            d = r.json()
        except requests.exceptions.RequestException as e:
            yield gr.update(value=f"backend error: {e}", visible=True), gr.update(value=0), None
            return

        log = _fmt_progress(d.get("stage", "?"), d.get("progress", 0))
        if d.get("error"):
            log += f"\nERROR: {d['error']}"
        clips_state = (d.get("clips", []) or [], job_id, d.get("download_path")) if d.get("done") else None
        yield gr.update(value=log, visible=True), gr.update(value=d.get("progress", 0)), clips_state

        if d.get("done"):
            return

        time.sleep(POLL_INTERVAL_S)


def cancel_pipeline(job_id):
    if not job_id:
        return gr.update(value="No job", interactive=False)
    try:
        r = requests.post(f"{API_BASE}/cancel/{job_id}", timeout=5)
        if r.status_code == 200:
            return gr.update(value="Cancelled", interactive=False)
    except requests.exceptions.RequestException:
        pass
    return gr.update(value="Cancel failed", interactive=False)


def build_clip_urls(payload):
    if not payload:
        return [], None
    clips, job_id, zip_path = payload
    items = []
    for c in clips:
        url = f"{API_BASE}/clip/{job_id}/{c.get('index')}"
        title = c.get("title", "")
        score = c.get("score", 0)
        mood = c.get("mood", "")
        duration = c.get("duration", 0)
        tags = ", ".join(c.get("tags", []) or [])
        caption = c.get("caption_hook") or c.get("hook_text", "")
        items.append((url, f"#{c.get('index', '?')} {title} | score {score} | {mood} | {duration}s | tags: {tags}"))
    zip_url = f"{API_BASE}/download/{job_id}" if zip_path and job_id else None
    return items, zip_url


with gr.Blocks(title="Islamic Hedayet - YouTube to Vertical Shorts", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        "# Islamic Hedayet\n"
        "**YouTube to vertical shorts with AI-matched music, burned-in subtitles, "
        "and per-clip viral metadata.**\n\n"
        "Free, local, no subscriptions."
    )

    health_box = gr.Textbox(label="Backend status", value=_health_check(), interactive=False)
    gr.Button("Recheck backend").click(_health_check, outputs=health_box)

    with gr.Row():
        with gr.Column():
            url_in = gr.Textbox(
                label="YouTube URL",
                placeholder="https://www.youtube.com/watch?v=...",
                lines=1,
            )
            niche_in = gr.Dropdown(NICHES, value="islamic", label="Niche (helps metadata generation)")
            quick_mode_in = gr.Radio(
                [("Yes (recommended for >20 min videos)", True), ("No (full transcription)", False)],
                value=True,
                label="Quick mode",
            )
            brand_in = gr.Textbox(
                label="Brand watermark (optional, e.g. 'YOUR EDITZ')",
                placeholder="Leave blank for no watermark",
                lines=1,
            )
            start_btn = gr.Button("Start", variant="primary")
            cancel_btn = gr.Button("Cancel", interactive=False, visible=False)
            status_log = gr.Textbox(label="Pipeline status", lines=6, interactive=False, visible=False)
            progress_bar = gr.Slider(minimum=0, maximum=100, value=0, label="Progress", interactive=False, visible=False)

        with gr.Column():
            zip_link = gr.File(label="Download all clips (ZIP)", visible=False, interactive=False)
            clips_state = gr.State()
            clips_gallery = gr.Gallery(label="Generated clips", columns=1, height=600, visible=False)

    job_id_state = gr.State()

    start_btn.click(
        start_pipeline,
        inputs=[url_in, niche_in, quick_mode_in, brand_in],
        outputs=[job_id_state, status_log],
    ).then(
        lambda: (gr.update(visible=True, interactive=True, value="Cancel"), gr.update(visible=True)),
        outputs=[cancel_btn, progress_bar],
    ).then(
        poll_status,
        inputs=[job_id_state],
        outputs=[status_log, progress_bar, clips_state],
    ).then(
        build_clip_urls,
        inputs=[clips_state],
        outputs=[clips_gallery, zip_link],
    )

    cancel_btn.click(cancel_pipeline, inputs=[job_id_state], outputs=cancel_btn)


if __name__ == "__main__":
    demo.queue(max_size=4).launch(server_name="0.0.0.0", server_port=UI_PORT, show_error=True)
