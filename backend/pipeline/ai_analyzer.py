import os
import json
import time
from groq import Groq

_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set")
        _client = Groq(api_key=api_key)
    return _client

def analyze_transcript(transcript: list, duration: float) -> list:
    client = get_client()

    segments_text = "\n".join(
        f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}"
        for s in transcript
    )

    prompt = f"""You are a viral shorts analyst. Given a transcript with timestamps from a {duration:.0f}-second video, find the best viral-worthy clips (15-40 seconds each). The number of clips depends on the content quality — return as many as you find worthy (minimum 1, maximum 5).

For each clip, score 0-100 based on: hook moments, emotional peaks, opinion bombs, revelations, conflict, quotable lines, story peaks, and practical value.

Return ONLY valid JSON array. No markdown, no code fences:
[{{"start": float, "end": float, "score": int, "reason": str, "mood": "chill"|"hype"|"emotional"|"funny"|"serious"}}]

Transcript:
{segments_text}"""

    response = client.chat.completions.create(
        model="llama-3.1-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000
    )

    content = response.choices[0].message.content.strip()
    content = content.replace("```json", "").replace("```", "").strip()

    clips = json.loads(content)
    for c in clips:
        c["start"] = float(c["start"])
        c["end"] = float(c["end"])
        c["score"] = int(c["score"])

    clips.sort(key=lambda x: x["score"], reverse=True)

    return clips
