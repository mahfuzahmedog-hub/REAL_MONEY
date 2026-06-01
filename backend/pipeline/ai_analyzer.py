import os
import json
import re
from groq import Groq

_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key or api_key == "your_new_groq_api_key_here":
            raise ValueError("GROQ_API_KEY not set. Edit backend/.env with your key.")
        _client = Groq(api_key=api_key)
    return _client

def analyze_transcript(transcript: list, duration: float) -> list:
    client = get_client()

    segments_text = "\n".join(
        f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}"
        for s in transcript
    )

    if not segments_text.strip():
        raise ValueError("Empty transcript — nothing to analyze")

    prompt = f"""You are a viral shorts analyst. Given a transcript with timestamps from a {duration:.0f}-second video, find the best viral-worthy clips (15-40 seconds each). The number of clips depends on content quality — return minimum 1, maximum 5.

For each clip, score 0-100 based on: hook moments, emotional peaks, strong opinions, revelations, conflict, quotable lines, story peaks, and practical value.

Return ONLY valid JSON. No markdown, no code fences, no extra text:
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
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    content = content.strip()

    if not content:
        raise ValueError("AI returned empty response")

    try:
        clips = json.loads(content)
    except json.JSONDecodeError:
        response = client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": prompt + "\n\nIMPORTANT: Return ONLY valid JSON. No extra text."}],
            temperature=0.1,
            max_tokens=2000
        )
        content = response.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        clips = json.loads(content)

    if not isinstance(clips, list):
        raise ValueError("AI response was not a list")

    for c in clips:
        c["start"] = max(0.0, float(c.get("start", 0)))
        c["end"] = float(c.get("end", 0))
        c["score"] = int(c.get("score", 0))
        c["mood"] = c.get("mood", "chill")
        c["reason"] = c.get("reason", "Viral moment")

    clips.sort(key=lambda x: x["score"], reverse=True)
    return clips
