"""Question generation and answer coaching with an optional Ollama backend."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass
class ProviderStatus:
    available: bool
    label: str
    detail: str


TOPICS = ["Python", "Java", "JavaScript", "HTML", "CSS", "C", "Databases", "APIs", "System design", "Cloud", "Testing", "Data structures"]

FALLBACK_QUESTIONS = {
    "Technical": [
        "Walk me through a project where you made an important technical trade-off.",
        "How do you investigate a production bug that cannot be reproduced locally?",
        "Describe how you would design a reliable, maintainable API for a growing product.",
        "Tell me about a time you improved performance or reduced operational risk.",
        "What do you do when a teammate strongly disagrees with your implementation?",
    ],
    "Behavioral": [
        "Tell me about a challenging project and how you kept it moving.",
        "Describe a time you received difficult feedback. What changed afterward?",
        "Give an example of a conflict you resolved on a team.",
        "Tell me about a mistake you made and what you learned from it.",
        "How do you prioritize when every stakeholder says their work is urgent?",
    ],
    "Mixed": [
        "Tell me about a project you are proud of and your specific contribution.",
        "How would you debug a slow service reported by customers?",
        "Describe a time you had to influence a decision without authority.",
        "What engineering or professional principle guides your work?",
        "How would you explain a complex idea to a non-technical stakeholder?",
    ],
}
FALLBACK_QUESTIONS["Technical"] += [
    "In {topic}, what design choice most affects correctness and maintainability?",
    "How would you test and troubleshoot a {topic} feature in production?",
    "Compare two approaches you have used with {topic}; when would you choose each?",
]


@lru_cache(maxsize=8)
def provider_status(model: str = "llama3.2") -> ProviderStatus:
    if not os.getenv("OLLAMA_HOST"):
        host = "http://localhost:11434"
    else:
        host = os.getenv("OLLAMA_HOST", "").rstrip("/")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=0.5) as response:
            if response.status == 200:
                return ProviderStatus(True, "Ollama connected", f"{host} • model: {model}")
    except (OSError, urllib.error.URLError):
        pass
    return ProviderStatus(False, "Local fallback active", "Ollama is optional. Set OLLAMA_HOST and run `ollama serve` to enable it.")


def _ollama(prompt: str, model: str, timeout: float = 8.0) -> str | None:
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    if not provider_status(model).available:
        return None
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 180},
    }).encode()
    request = urllib.request.Request(f"{host}/api/generate", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode()).get("response")
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _clean_questions(response: str | None) -> list[str]:
    if not response:
        return []
    return [line.strip(" -*0123456789.)").strip() for line in response.splitlines()
            if len(line.strip(" -*0123456789.)").strip()) > 15]


def generate_questions(role: str, level: str, interview_type: str, count: int, model: str,
                       topics: list[str] | None = None, excluded: list[str] | None = None,
                       use_ai: bool = True) -> list[str]:
    topics = topics or ["general software engineering"]
    excluded = {item.strip().casefold() for item in (excluded or [])}
    prompt = (f"Create exactly {count} short interview questions for a {level} {role} candidate. "
              f"Interview type: {interview_type}. Focus on: {', '.join(topics)}. "
              f"Do not repeat or paraphrase these prior questions: {list(excluded)[:30]}. "
              "Return one question per line, no numbering or commentary. Keep each under 25 words.")
    response = _ollama(prompt, model) if use_ai else None
    questions = []
    seen = set(excluded)
    for question in _clean_questions(response):
        key = question.casefold()
        if key not in seen:
            questions.append(question)
            seen.add(key)
    if len(questions) >= count:
        return questions[:count]
    base = FALLBACK_QUESTIONS.get(interview_type, FALLBACK_QUESTIONS["Mixed"])
    candidates = []
    for topic in topics:
        candidates.extend(q.format(topic=topic) for q in base)
        candidates.extend([
            f"Explain a difficult {topic} concept as if you were mentoring a new teammate.",
            f"How do you keep {topic} code secure, observable, and easy to maintain?",
            f"Describe a failure you might encounter with {topic} and your step-by-step response.",
            f"What would you measure to decide whether a {topic} solution is successful?",
        ])
    candidates.extend(q.replace("project", f"{role} project", 1) if role else q for q in base)
    for question in candidates:
        if question.casefold() not in seen:
            questions.append(question)
            seen.add(question.casefold())
        if len(questions) >= count:
            break
    return questions[:count]


def generate_follow_up(question: str, answer: str, model: str, topic: str = "") -> str:
    return "What measurable result, trade-off, or lesson would you add to that answer?"


def evaluate_answer(question: str, answer: str, model: str, fast: bool = False) -> dict[str, Any]:
    prompt = (f"Score this interview answer from 0 to 10. Q: {question}\nA: {answer}\n"
              "Return compact JSON: score, feedback, suggestion, follow_up_question. "
              "Keep feedback and suggestion under 25 words each.")
    response = None if fast else _ollama(prompt, model, timeout=8)
    if response:
        try:
            text = response[response.find("{"):response.rfind("}") + 1]
            parsed = json.loads(text)
            if all(key in parsed for key in ("score", "feedback", "suggestion")):
                parsed["score"] = max(0, min(10, float(parsed["score"])))
                parsed.setdefault("follow_up_question", generate_follow_up(question, answer, model))
                return parsed
        except (ValueError, json.JSONDecodeError):
            pass
    words = len(answer.split())
    has_example = any(token in answer.casefold() for token in ("for example", "project", "built", "used", "because"))
    score = min(10, max(2, round(3 + min(words, 120) / 20 + (0.8 if has_example else 0), 1)))
    return {
        "score": score,
        "feedback": "Good starting point. Add a concrete example and explain the result to make your answer more persuasive.",
        "suggestion": "Use a compact STAR structure: situation, task, action, and measurable result.",
        "follow_up_question": generate_follow_up(question, answer, model),
    }


def build_report(evaluations: list[dict[str, Any]], model: str) -> dict[str, Any]:
    overall = round(sum(float(item["score"]) for item in evaluations) / max(1, len(evaluations)), 1)
    prompt = (f"Create a personalized coaching report from these interview evaluations: {evaluations}. "
              "Return JSON with strengths, weaknesses, recommendations as arrays of short strings.")
    response = _ollama(prompt, model)
    if response:
        try:
            parsed = json.loads(response[response.find("{"):response.rfind("}") + 1])
            if all(key in parsed for key in ("strengths", "weaknesses", "recommendations")):
                parsed["overall_score"] = overall
                return parsed
        except (ValueError, json.JSONDecodeError):
            pass
    strong = sum(float(item["score"]) >= 7 for item in evaluations)
    needs_work = sum(float(item["score"]) < 6 for item in evaluations)
    return {
        "overall_score": overall,
        "strengths": [f"You completed {len(evaluations)} coached responses.",
                      f"{strong} response(s) showed strong structure or evidence."],
        "weaknesses": [f"{needs_work} response(s) need more depth or specificity.",
                       "Some answers would benefit from concrete evidence and outcomes."],
        "recommendations": ["Practice STAR responses aloud.", "Quantify impact wherever possible.",
                            "Use each adaptive follow-up to add a missing detail."],
    }
