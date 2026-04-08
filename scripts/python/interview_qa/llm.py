from __future__ import annotations

import os
from typing import Any

import requests

from app.config import TUNING_PREDICT_QA_KEEP_ALIVE, TUNING_PREDICT_QA_OUTPUT_FORMAT


def _ollama_chat(*, model: str, prompt: str, keep_alive: str) -> dict[str, Any]:
    """Call the Ollama chat API directly."""
    base_url = (os.getenv("OLLAMA_BASE_URL") or os.getenv("LLM_UPSTREAM_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json" if TUNING_PREDICT_QA_OUTPUT_FORMAT == "json" else None,
        "options": {"temperature": 0},
        "keep_alive": keep_alive,
        "stream": False,
    }
    response = requests.post(f"{base_url}/api/chat", json=payload, timeout=600)
    response.raise_for_status()
    return response.json()


def _llama_cpp_chat(*, model: str, prompt: str) -> dict[str, Any]:
    """Call the llama.cpp OpenAI-compatible endpoint."""
    base_url = str(os.getenv("LLAMA_CPP_BASE_URL") or "http://127.0.0.1:8080/v1").rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=600)
    response.raise_for_status()
    body = response.json()
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    return {
        "message": {"content": content},
        "total_duration": 0,
        "load_duration": 0,
        "eval_duration": 0,
        "prompt_eval_count": int(body.get("usage", {}).get("prompt_tokens") or 0),
        "eval_count": int(body.get("usage", {}).get("completion_tokens") or 0),
    }


def _gateway_chat(*, model: str, prompt: str) -> dict[str, Any]:
    """Call the local gateway to keep backend routing consistent with the rest of the system."""
    base_url = str(
        os.getenv("LLM_GATEWAY_BASE_URL")
        or os.getenv("LOCAL_LLM_BASE_URL")
        or "http://127.0.0.1:8101/v1"
    ).rstrip("/")
    shared_token = str(os.getenv("INTERNAL_LLM_SHARED_TOKEN", "") or "").strip()
    headers = {"Content-Type": "application/json"}
    if shared_token:
        headers["X-Internal-LLM-Token"] = shared_token
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=600)
    response.raise_for_status()
    body = response.json()
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    usage = body.get("usage", {}) or {}
    return {
        "message": {"content": content},
        "total_duration": int(usage.get("total_duration") or 0),
        "load_duration": int(usage.get("load_duration") or 0),
        "eval_duration": int(usage.get("eval_duration") or 0),
        "prompt_eval_count": int(usage.get("prompt_eval_count") or usage.get("prompt_tokens") or 0),
        "eval_count": int(usage.get("eval_count") or usage.get("completion_tokens") or 0),
        "gateway_usage": usage,
    }


def chat_backend(*, backend: str, model: str, prompt: str) -> dict[str, Any]:
    """Dispatch prediction calls to the configured local backend."""
    normalized = str(backend or "").strip().lower()
    if normalized == "ollama":
        return _ollama_chat(model=model, prompt=prompt, keep_alive=TUNING_PREDICT_QA_KEEP_ALIVE)
    if normalized == "llama_cpp":
        return _llama_cpp_chat(model=model, prompt=prompt)
    if normalized in {"gateway", "gateway_ollama_chat"}:
        return _gateway_chat(model=model, prompt=prompt)
    raise ValueError(f"Unsupported prediction backend: {backend}")
