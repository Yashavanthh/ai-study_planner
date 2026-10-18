"""
ai_client.py
------------
Two Gemini-powered functions:
  suggest_important_topics() -- ranked list of exam-important topics
  chat_with_subject()        -- multi-turn study assistant for a subject
"""

import json
import os

import requests

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


class AIConfigError(Exception):
    pass


class AIRequestError(Exception):
    pass


def _get_key():
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise AIConfigError(
            "GEMINI_API_KEY is not set. Get a free key from "
            "https://aistudio.google.com/apikey and add it to your .env file."
        )
    return key


def _post(payload: dict) -> dict:
    try:
        resp = requests.post(
            GEMINI_URL,
            headers={"Content-Type": "application/json", "x-goog-api-key": _get_key()},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise AIRequestError(f"Could not reach Gemini API: {exc}") from exc

    if resp.status_code != 200:
        raise AIRequestError(
            f"Gemini API error (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise AIRequestError("Gemini response was not valid JSON.") from exc


def _extract_text(data: dict) -> str:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIRequestError("Unexpected Gemini response shape.") from exc


# ---------------------------------------------------------------------------
# 1. Topic suggestions
# ---------------------------------------------------------------------------

def suggest_important_topics(subject_name: str, difficulty: int, count: int = 6) -> list:
    prompt = (
        f'You are an expert exam coach. A student is preparing for "{subject_name}" '
        f"(difficulty {difficulty}/5). List the {count} most important topics to study "
        f"to score well, ordered most-to-least important. Use short names (2-5 words). "
        f"Respond with ONLY a JSON array of strings, nothing else."
    )
    data = _post({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    })
    try:
        topics = json.loads(_extract_text(data))
    except (json.JSONDecodeError, ValueError) as exc:
        raise AIRequestError("Could not parse topic suggestions as JSON.") from exc
    if not isinstance(topics, list):
        raise AIRequestError("Gemini did not return a list of topics.")
    cleaned, seen = [], set()
    for t in topics:
        if isinstance(t, str):
            name = t.strip()
            if name and name.lower() not in seen:
                cleaned.append(name)
                seen.add(name.lower())
    return cleaned[:count]


# ---------------------------------------------------------------------------
# 2. Subject chatbot
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert study assistant helping a student prepare for their exam.
Your job is to:
- Explain concepts clearly and simply, with examples where helpful
- Answer questions about the subject accurately
- Generate practice questions when asked
- Give study tips relevant to this specific subject
- Be encouraging and supportive

Keep answers focused and concise. Use bullet points or numbered lists for clarity.
Do NOT answer questions unrelated to studying or the subject."""


def chat_with_subject(
    subject_name: str,
    difficulty: int,
    is_weak: bool,
    topics: list,
    history: list,
    user_message: str,
) -> str:
    """
    Send a message to Gemini with full context about the subject and
    the prior conversation history.

    history: list of dicts with keys 'role' ('user'|'assistant') and 'content'
    Returns the assistant's reply as a plain string.
    """
    topic_list = ", ".join(topics) if topics else "none logged yet"
    weak_note  = " (student finds this subject difficult)" if is_weak else ""

    system_context = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Subject: {subject_name}{weak_note}\n"
        f"Difficulty: {difficulty}/5\n"
        f"Topics the student is tracking: {topic_list}"
    )

    # Build the Gemini contents array from history + new message.
    # First turn always has the system context injected into the user message
    # so Gemini always knows the subject context regardless of history length.
    contents = []
    for i, msg in enumerate(history[-10:]):   # keep last 10 turns for context
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    # Inject system context into the very first user message only
    if not contents:
        first_text = f"[Context]\n{system_context}\n\n[Student question]\n{user_message}"
    else:
        first_text = user_message
        contents[0]["parts"][0]["text"] = (
            f"[Context]\n{system_context}\n\n"
            f"[Student question]\n{contents[0]['parts'][0]['text']}"
        )

    contents.append({"role": "user", "parts": [{"text": first_text if not history else user_message}]})

    data = _post({
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1024,
        },
    })
    return _extract_text(data).strip()
