"""Módulo de integração com IA (Google Gemini) / AI Integration Module (Google Gemini)

Implementa o funil de curadoria em camadas:
- Etapa 1 (Triagem Ampla / Alto Recall): Gemini Flash Lite
- Etapa 2 (Refinamento em Lotes de 2 a 3 notícias): Gemini Flash com Extended Thinking
- Etapa 3 (Consolidação e Harmonização de Grupos): Gemini Flash com Extended Thinking
- Gerenciamento de quotas com cascata automática de fallback
- Controle proativo de taxa (RPM / Pacing)
"""
import json
import logging
import os
import re
import time
import unicodedata
from typing import Any, Optional

import requests

from config import CAREER_LABELS

logger = logging.getLogger(__name__)

def _load_env_file() -> None:
    """Carrega variáveis de .env local se existir (suporte nativo sem dependências)"""
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and v and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


_load_env_file()

# Chave da API Google / Google API Key
AI_API_KEY: str = os.environ.get("AI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta/models"

# Filas de modelos para fallback em ordem de prioridade
FLASH_MODELS: list[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-2.5-flash",
]

LITE_MODELS: list[str] = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
]

# Intervalos mínimos entre requisições para respeitar os limites de RPM
# 15 RPM = 4.0s (adotado 4.2s por margem de segurança)
# 5 RPM  = 12.0s (adotado 12.5s por margem de segurança)
RPM_INTERVALS: dict[str, float] = {
    "lite": 4.2,
    "flash": 12.5,
}

# Prompts refinados do Funil de Curadoria Jurídica
from prompts import (
    PROMPT_TRIAGE_LITE,
    PROMPT_REFINEMENT_BATCH,
    PROMPT_CONSOLIDATION,
)

# Aliases para compatibilidade legada
PROMPT_RELEVANCE = PROMPT_REFINEMENT_BATCH


class GeminiClient:
    """Cliente gerenciador da API Gemini com rate limiting e fallback em cascata"""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key: Optional[str] = api_key
        self.exhausted_models: set[str] = set()
        self.last_call_time: float = 0.0

    @property
    def api_key(self) -> str:
        if self._api_key:
            return self._api_key
        return os.environ.get("AI_API_KEY", os.environ.get("GEMINI_API_KEY", AI_API_KEY))

    def _wait_for_rate_limit(self, tier: str) -> None:
        """Garante o espaçamento mínimo entre chamadas para respeitar o RPM do modelo"""
        min_interval = RPM_INTERVALS.get(tier, 4.2)
        elapsed = time.time() - self.last_call_time
        if elapsed < min_interval:
            sleep_duration = min_interval - elapsed
            time.sleep(sleep_duration)

    def _build_payload(self, system_prompt: str, user_content: str, enable_thinking: bool, model_name: str) -> dict[str, Any]:
        """Monta o payload JSON compatível com a API Gemini v1beta"""
        generation_config: dict[str, Any] = {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        }

        # Extended Thinking apenas para modelos Flash que não sejam Lite
        if enable_thinking and "flash" in model_name and "lite" not in model_name:
            generation_config["thinkingConfig"] = {"thinkingBudget": -1}

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_content}],
                }
            ],
            "generationConfig": generation_config,
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}]
            }

        return payload

    def _extract_content(self, data: dict[str, Any]) -> str:
        """Extrai o texto da resposta filtrando partes de pensamento (Extended Thinking)"""
        candidates = data.get("candidates", [])
        if not candidates:
            return ""

        parts = candidates[0].get("content", {}).get("parts", [])
        # Filtra pensamentos intermediários para pegar apenas a resposta JSON final
        text_parts = [
            p.get("text", "")
            for p in parts
            if not p.get("thought", False) and "text" in p
        ]
        return "".join(text_parts).strip()

    def generate(self, tier: str, system_prompt: str, user_content: str, enable_thinking: bool = True) -> str:
        """Executa a chamada à API Gemini com rotação de modelos e cascata de fallback"""
        if not self.api_key:
            logger.error("AI_API_KEY não configurada no ambiente.")
            return ""

        # Define a fila de modelos conforme o tier e a política de fallback
        if tier == "flash":
            # Tenta a cadeia Flash; se todos esgotarem, degrada para a cadeia Lite
            model_queue = [m for m in FLASH_MODELS if m not in self.exhausted_models]
            if not model_queue:
                logger.warning("Todos os modelos Flash esgotaram cotas. Ativando fallback de emergência para Flash Lite.")
                model_queue = [m for m in LITE_MODELS if m not in self.exhausted_models]
        else:
            model_queue = [m for m in LITE_MODELS if m not in self.exhausted_models]

        if not model_queue:
            logger.error("Todos os modelos configurados na cascata estão com cotas esgotadas nesta sessão.")
            return ""

        for model_name in model_queue:
            url = f"{GEMINI_API_BASE}/{model_name}:generateContent?key={self.api_key}"
            current_tier = "lite" if "lite" in model_name else "flash"
            use_thinking = enable_thinking and (current_tier == "flash")

            for attempt in range(2):
                self._wait_for_rate_limit(current_tier)
                payload = self._build_payload(system_prompt, user_content, use_thinking, model_name)

                try:
                    resp = requests.post(url, json=payload, timeout=60)
                    self.last_call_time = time.time()

                    if resp.status_code == 200:
                        content = self._extract_content(resp.json())
                        if content:
                            return content
                        logger.warning("Modelo %s retornou resposta vazia na tentativa %d/2.", model_name, attempt + 1)
                        continue

                    # Erro 400: Parâmetro inválido (ex: thinkingConfig não suportado no modelo)
                    if resp.status_code == 400:
                        err_text = resp.text
                        if "thinkingConfig" in err_text or "thinking" in err_text:
                            logger.warning("Modelo %s não suporta thinkingConfig. Desativando thinking e retentando...", model_name)
                            use_thinking = False
                            continue
                        logger.error("Requisição inválida (HTTP 400) para %s: %s", model_name, err_text[:300])
                        self.exhausted_models.add(model_name)
                        break

                    # Erro 429: Cota esgotada ou Too Many Requests
                    if resp.status_code == 429:
                        logger.warning("Modelo %s atingiu limite de cota (HTTP 429). Alternando para próximo da fila.", model_name)
                        self.exhausted_models.add(model_name)
                        break

                    # Erros 5xx: Instabilidade temporária da API
                    if resp.status_code >= 500:
                        logger.warning("Instabilidade na API Google (%s - HTTP %d). Retentando em 3s...", model_name, resp.status_code)
                        time.sleep(3)
                        continue

                    logger.error("Erro inesperado em %s [HTTP %d]: %s", model_name, resp.status_code, resp.text[:300])

                except requests.exceptions.RequestException as e:
                    logger.warning("Falha de rede ao chamar %s (tentativa %d/2): %s", model_name, attempt + 1, e)
                    time.sleep(2)

            # Se o modelo falhou e foi marcado como esgotado, o loop avança para o próximo modelo da fila
            if model_name in self.exhausted_models:
                continue

        return ""


# Instância única compartilhada na execução / Shared client instance
gemini_client = GeminiClient()


def normalize_group(g: str) -> str:
    """Normaliza o nome do grupo gerado por IA (remove acentos e caracteres especiais)"""
    if not g:
        return ""
    g = unicodedata.normalize("NFKD", g).encode("ascii", "ignore").decode("ascii")
    g = g.lower().strip()
    g = re.sub(r"[^a-z0-9-]", "-", g)
    g = re.sub(r"-+", "-", g).strip("-")
    return g


def _clean_json_string(s: str) -> str:
    """Remove marcações de bloco de código markdown (```json ... ```)"""
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _validate_evaluation(data: Any) -> dict[str, Any]:
    """Valida e normaliza o dicionário de avaliação da IA"""
    if not isinstance(data, dict):
        return {"relevant": False, "reason": "response not a json object"}

    relevant = data.get("relevant")
    if not isinstance(relevant, bool):
        return {"relevant": False, "reason": "missing or invalid 'relevant' field"}

    reason_raw = data.get("reason", "")
    reason = reason_raw if isinstance(reason_raw, str) else str(reason_raw or "")
    result: dict[str, Any] = {"relevant": relevant, "reason": reason}

    if relevant:
        career_raw = data.get("career", "")
        career = career_raw.strip().lower() if isinstance(career_raw, str) else ""
        result["career"] = career if career in CAREER_LABELS else "administrativo"

        group_raw = data.get("group", "")
        result["group"] = normalize_group(group_raw if isinstance(group_raw, str) else "")

    return result


def call_ai_api(system_prompt: str, user_content: str, tier: str = "flash", enable_thinking: bool = True) -> str:
    """Função central de chamada à IA com fallback de modelos e extended thinking"""
    return gemini_client.generate(tier=tier, system_prompt=system_prompt, user_content=user_content, enable_thinking=enable_thinking)


def triage_item(url: str, title: str, text: str) -> bool:
    """Etapa 1: Triagem de alto recall com Gemini Flash Lite (descarta apenas os 100% irrelevantes)"""
    if not gemini_client.api_key:
        return False
    if not text or len(text) < 50:
        return False

    snippet = text[:2000]
    content = f"URL: {url}\nTítulo: {title}\n\nTexto:\n{snippet}"
    response = call_ai_api(
        system_prompt=PROMPT_TRIAGE_LITE,
        user_content=content,
        tier="lite",
        enable_thinking=False,
    )

    if not response:
        logger.warning("Triagem sem resposta da IA para %s. Mantendo como potencialmente relevante por segurança.", url)
        return True

    cleaned = _clean_json_string(response)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return bool(data.get("relevant", False))
    except Exception:
        logger.warning("Resposta inválida na triagem para %s: %s. Mantendo no funil.", url, cleaned[:100])
        return True

    return False


def _evaluate_single_fallback(item: dict[str, Any]) -> dict[str, Any]:
    """Fallback individual caso uma chamada em lote falhe completamente"""
    url = item.get("url", "")
    title = item.get("title") or item.get("real_title") or ""
    text = item.get("text", "")[:4000]
    content = f"URL: {url}\nTítulo: {title}\n\nTexto:\n{text}"

    prompt_single = PROMPT_REFINEMENT_BATCH + "\nAvalie este item único e responda com array contendo apenas 1 objeto JSON [ { ... } ]."
    response = call_ai_api(prompt_single, content, tier="flash", enable_thinking=True)
    if not response:
        return {"relevant": False, "reason": "empty response from AI in single fallback"}

    cleaned = _clean_json_string(response)
    try:
        data = json.loads(cleaned)
        if isinstance(data, list) and data:
            return _validate_evaluation(data[0])
        if isinstance(data, dict):
            return _validate_evaluation(data)
    except Exception as e:
        logger.warning("Falha no fallback individual para %s: %s", url, e)

    return {"relevant": False, "reason": "error parsing single fallback"}


def evaluate_batch(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Etapa 2: Avaliação analítica profunda em lote (2 a 3 notícias) com Gemini Flash + Extended Thinking"""
    if not items:
        return []
    if not gemini_client.api_key:
        return [{"relevant": False, "reason": "AI_API_KEY not configured"} for _ in items]

    batch_payload = []
    valid_indices = []
    results: list[Optional[dict[str, Any]]] = [None] * len(items)

    for idx, item in enumerate(items):
        text = item.get("text", "")
        if not text or len(text) < 50:
            results[idx] = {"relevant": False, "reason": "insufficient text"}
            continue

        valid_indices.append(idx)
        url = item.get("url", "")
        title = item.get("title") or item.get("real_title") or ""
        batch_payload.append({
            "id": str(idx),
            "url": url,
            "title": title,
            "text": text[:4000],
        })

    if not valid_indices:
        return [r for r in results if r is not None]

    user_content = json.dumps(batch_payload, ensure_ascii=False, indent=2)
    response = call_ai_api(
        system_prompt=PROMPT_REFINEMENT_BATCH,
        user_content=user_content,
        tier="flash",
        enable_thinking=True,
    )

    if not response:
        logger.warning("Lote de %d itens sem resposta da IA Flash. Acionando fallback individual.", len(valid_indices))
        for idx in valid_indices:
            results[idx] = _evaluate_single_fallback(items[idx])
        return [r for r in results if r is not None]

    cleaned = _clean_json_string(response)
    try:
        raw_list = json.loads(cleaned)
        if isinstance(raw_list, list):
            results_by_id: dict[str, dict[str, Any]] = {}
            for obj in raw_list:
                if isinstance(obj, dict) and "id" in obj:
                    results_by_id[str(obj["id"])] = _validate_evaluation(obj)

            for idx in valid_indices:
                str_idx = str(idx)
                if str_idx in results_by_id:
                    results[idx] = results_by_id[str_idx]
                elif idx < len(raw_list) and isinstance(raw_list[idx], dict):
                    results[idx] = _validate_evaluation(raw_list[idx])
                else:
                    results[idx] = {"relevant": False, "reason": "missing from batch response"}
            return [r for r in results if r is not None]
    except Exception as e:
        logger.warning("Erro ao parsear resposta em lote: %s. Acionando fallback individual.", e)

    for idx in valid_indices:
        results[idx] = _evaluate_single_fallback(items[idx])
    return [r for r in results if r is not None]


def evaluate_relevance(url: str, title: str, text: str) -> dict[str, Any]:
    """Avaliação de relevância de um único item (compatibilidade com chamadas individuais e testes)"""
    if not gemini_client.api_key:
        return {"relevant": False, "reason": "AI_API_KEY not configured"}
    if not text or len(text) < 50:
        return {"relevant": False, "reason": "insufficient text"}

    content = f"URL: {url}\nTítulo: {title}\n\nTexto:\n{text}"
    response = call_ai_api(PROMPT_REFINEMENT_BATCH, content, tier="flash", enable_thinking=True)
    if not response:
        return {"relevant": False, "reason": "empty response from AI"}

    cleaned = _clean_json_string(response)
    try:
        raw = json.loads(cleaned)
        if isinstance(raw, list) and raw:
            raw = raw[0]
    except json.JSONDecodeError:
        return {"relevant": False, "reason": f"error parsing response: {cleaned}", "raw_response": response}

    result = _validate_evaluation(raw)
    result["raw_response"] = response
    return result


def consolidate_groups(relevant_items: list[dict[str, Any]]) -> None:
    """Etapa 3: Consolida e unifica identificadores de grupo de itens do mesmo certame"""
    if not gemini_client.api_key or len(relevant_items) <= 1:
        return

    items_to_send = [
        {
            "id": str(i),
            "title": item.get("real_title") or item.get("title") or "",
            "reason": item.get("reason", ""),
            "group": item.get("group", ""),
        }
        for i, item in enumerate(relevant_items)
    ]

    content = json.dumps(items_to_send, ensure_ascii=False, indent=2)
    response = call_ai_api(
        system_prompt=PROMPT_CONSOLIDATION,
        user_content=content,
        tier="flash",
        enable_thinking=True,
    )

    if not response:
        logger.warning("Falha na consolidação de grupos: sem resposta da IA.")
        return

    cleaned = _clean_json_string(response)
    try:
        mapping = json.loads(cleaned)
        if isinstance(mapping, dict):
            for i, item in enumerate(relevant_items):
                str_i = str(i)
                if str_i in mapping:
                    item["group"] = normalize_group(mapping[str_i])
    except json.JSONDecodeError:
        logger.warning("Falha na consolidação de grupos: resposta não é JSON. Limpo: %s", cleaned)
    except Exception as e:
        logger.warning("Falha na consolidação de grupos: %s", e)
