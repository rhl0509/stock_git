"""
agent/llm_client.py
===================
LLM 래퍼. 로컬 Ollama 전용. (Claude API 폴백은 과금 제거판에서 삭제됨)

사용:
  from agent.llm_client import generate, is_available
  text = generate(prompt)

Ollama 미가용 시 generate()는 빈 문자열을 반환하고, 이를 호출하는
에이전트 잡들은 LLM 서술 없이(또는 스킵) 동작한다.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Generator

import requests

logger = logging.getLogger(__name__)

OLLAMA_BASE    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL  = os.getenv("REPORT_LLM_MODEL", "qwen2.5:7b")
FALLBACK_MODEL = "llama3.2:latest"

# system 미지정 호출의 기본 시스템 프롬프트.
# qwen2.5 등 중국어 편향 소형 모델이 한국어 생성 중 다른 언어로 갈아타는(code-switching)
# 현상을 막는다. 명시적으로 다른 언어를 요청한 경우(예: 사용자 워크플로)는 허용.
DEFAULT_SYSTEM = (
    "당신은 한국 금융 분석가입니다. 사용자가 다른 언어를 명시적으로 요청하지 않는 한 "
    "반드시 자연스러운 한국어로만 작성하고, 하나의 답변 안에서 중국어·일본어·영어 등 "
    "다른 언어의 문자를 절대 섞지 마세요."
)

_ollama_available: bool | None = None  # None = 아직 미확인


def _check_ollama() -> bool:
    """Ollama 서버 및 사용 가능한 모델이 있는지 확인."""
    global _ollama_available
    if _ollama_available is not None:
        return _ollama_available
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        if resp.ok:
            names = {m["name"] for m in resp.json().get("models", [])}
            _ollama_available = bool(names)
        else:
            _ollama_available = False
    except Exception:
        _ollama_available = False
    return _ollama_available


def _pick_ollama_model() -> str:
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
        if resp.ok:
            names = {m["name"] for m in resp.json().get("models", [])}
            for candidate in (DEFAULT_MODEL, "qwen2.5:7b", FALLBACK_MODEL):
                if candidate in names:
                    return candidate
    except Exception:
        pass
    return DEFAULT_MODEL


# ─────────────────────────────────────────────────────────────────
# Ollama 호출
# ─────────────────────────────────────────────────────────────────

def _generate_ollama(prompt: str, system: str, temperature: float, max_tokens: int) -> str:
    model = _pick_ollama_model()
    payload: dict = {
        "model":   model,
        "prompt":  prompt,
        "stream":  False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if system:
        payload["system"] = system
    try:
        resp = requests.post(f"{OLLAMA_BASE}/api/generate", json=payload, timeout=300)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"[llm_client] Ollama generate 실패 ({model}): {e}")
        return ""


# ─────────────────────────────────────────────────────────────────
# 공개 인터페이스
# ─────────────────────────────────────────────────────────────────

def generate(
    prompt: str,
    *,
    system: str = "",
    _model: str | None = None,  # 하위호환용 — 내부적으로 모델 자동 선택
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """
    텍스트 생성. 로컬 Ollama 사용. 미가용/실패 시 빈 문자열 반환.
    """
    if not system:
        system = DEFAULT_SYSTEM
    if _check_ollama():
        logger.info("[llm_client] Ollama 사용")
        return _generate_ollama(prompt, system, temperature, max_tokens)

    logger.warning("[llm_client] Ollama 미가용 — 빈 응답 반환")
    return ""


def stream_generate(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """스트리밍 생성. Ollama 전용. 미가용 시 아무것도 yield하지 않음."""
    if not system:
        system = DEFAULT_SYSTEM
    if _check_ollama():
        model = _pick_ollama_model()
        payload: dict = {
            "model":   model,
            "prompt":  prompt,
            "stream":  True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        try:
            with requests.post(
                f"{OLLAMA_BASE}/api/generate",
                json=payload,
                stream=True,
                timeout=300,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            return
                    except json.JSONDecodeError:
                        continue
            return
        except Exception as e:
            logger.warning(f"[llm_client] Ollama stream 실패: {e}")
            return

    logger.warning("[llm_client] Ollama 미가용 — 스트리밍 없음")
    return


def is_available() -> bool:
    """LLM 사용 가능 여부 (로컬 Ollama 사용 가능 시 True)."""
    return _check_ollama()


def reset_cache():
    """테스트 또는 재시작 시 Ollama 가용성 캐시 초기화."""
    global _ollama_available
    _ollama_available = None
