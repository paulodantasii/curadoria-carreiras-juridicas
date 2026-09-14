"""Testes do módulo ai / ai module tests"""
import json
from unittest.mock import patch

import pytest

from ai import (
    GeminiClient,
    evaluate_batch,
    evaluate_relevance,
    normalize_group,
    consolidate_groups,
    triage_item,
)


class TestNormalizeGroup:
    def test_lowercases_and_replaces_spaces(self):
        assert normalize_group("PGM Caxias do Sul - Procurador") == "pgm-caxias-do-sul-procurador"

    def test_strips_accents(self):
        assert normalize_group("Procuração") == "procuracao"

    def test_collapses_repeated_separators(self):
        assert normalize_group("foo // bar -- baz") == "foo-bar-baz"

    def test_strips_leading_trailing_separators(self):
        assert normalize_group("--foo--") == "foo"

    def test_empty_returns_empty(self):
        assert normalize_group("") == ""

    def test_none_returns_empty(self):
        assert normalize_group(None) == ""


class TestEvaluateRelevance:
    LEGAL_TEXT = "Edital de concurso para procurador municipal " * 5

    def test_no_api_key(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "")
        monkeypatch.delenv("AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = evaluate_relevance("https://x.com", "title", self.LEGAL_TEXT)
        assert result["relevant"] is False
        assert result["reason"] == "AI_API_KEY not configured"

    def test_insufficient_text(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        result = evaluate_relevance("https://x.com", "title", "curto")
        assert result["relevant"] is False
        assert result["reason"] == "insufficient text"

    def test_relevant_response_passthrough(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        ai_response = json.dumps({
            "relevant": True,
            "reason": "Cargo de procurador municipal",
            "career": "procuradorias",
            "group": "PGM Foo - Procurador",
        })
        with patch("ai.call_ai_api", return_value=ai_response):
            result = evaluate_relevance("https://x.com", "Edital", self.LEGAL_TEXT)
        assert result["relevant"] is True
        assert result["career"] == "procuradorias"
        assert result["group"] == "pgm-foo-procurador"

    def test_invalid_career_fallback_to_administrativo(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        ai_response = json.dumps({
            "relevant": True,
            "reason": "x",
            "career": "INVALID_CAREER",
            "group": "g",
        })
        with patch("ai.call_ai_api", return_value=ai_response):
            result = evaluate_relevance("https://x.com", "Edital", self.LEGAL_TEXT)
        assert result["career"] == "administrativo"

    def test_malformed_json_handled(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        with patch("ai.call_ai_api", return_value="not valid json"):
            result = evaluate_relevance("https://x.com", "Edital", self.LEGAL_TEXT)
        assert result["relevant"] is False
        assert "error parsing response" in result["reason"]

    def test_empty_response_handled(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        with patch("ai.call_ai_api", return_value=""):
            result = evaluate_relevance("https://x.com", "Edital", self.LEGAL_TEXT)
        assert result["relevant"] is False
        assert result["reason"] == "empty response from AI"

class TestConsolidateGroups:
    def test_consolidate_groups_success(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        items = [
            {"title": "Edital TJSP", "group": "tjsp-juiz"},
            {"title": "Magistratura SP", "group": "tj-sp-magistratura"},
            {"title": "MPSP Promotor", "group": "mpsp-promotor"}
        ]
        
        ai_response = json.dumps({
            "0": "tjsp-juiz",
            "1": "tjsp-juiz",
            "2": "mpsp-promotor"
        })
        
        with patch("ai.call_ai_api", return_value=ai_response):
            consolidate_groups(items)
            
        assert items[0]["group"] == "tjsp-juiz"
        assert items[1]["group"] == "tjsp-juiz"
        assert items[2]["group"] == "mpsp-promotor"

    def test_consolidate_groups_invalid_json(self, monkeypatch, caplog):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        items = [
            {"title": "Edital TJSP", "group": "tjsp-juiz"},
            {"title": "Magistratura SP", "group": "tj-sp-magistratura"},
        ]
        
        with patch("ai.call_ai_api", return_value="not a json"):
            consolidate_groups(items)
            
        assert items[0]["group"] == "tjsp-juiz"
        assert "Falha na consolidação de grupos" in caplog.text

    def test_consolidate_groups_empty_items(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        items = []
        with patch("ai.call_ai_api") as mock_api:
            consolidate_groups(items)
        mock_api.assert_not_called()


class TestGeminiClient:
    def test_generate_strips_thinking_parts(self):
        client = GeminiClient(api_key="test-key")
        client.last_call_time = 0.0

        mock_resp = type("MockResponse", (), {
            "status_code": 200,
            "json": lambda *args, **kwargs: {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"thought": True, "text": "Raciocínio interno detalhado da IA..."},
                                {"text": '{"relevant": true, "career": "tribunais"}'},
                            ]
                        }
                    }
                ]
            },
        })()

        with patch("requests.post", return_value=mock_resp):
            with patch("time.sleep"):
                res = client.generate(tier="flash", system_prompt="sys", user_content="usr")
        assert res == '{"relevant": true, "career": "tribunais"}'

    def test_fallback_on_429_quota(self):
        client = GeminiClient(api_key="test-key")
        client.last_call_time = 0.0

        resp_429 = type("MockResponse", (), {"status_code": 429, "text": "Quota exceeded"})()
        resp_200 = type("MockResponse", (), {
            "status_code": 200,
            "json": lambda *args, **kwargs: {
                "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]
            },
        })()

        # Primeiro modelo falha com 429, segundo modelo tem sucesso com 200
        with patch("requests.post", side_effect=[resp_429, resp_200]) as mock_post:
            with patch("time.sleep"):
                res = client.generate(tier="flash", system_prompt="sys", user_content="usr")

        assert res == '{"ok": true}'
        assert len(client.exhausted_models) == 1
        assert "gemini-3.8-flash" in client.exhausted_models
        # Duas requisições feitas: primeiro no modelo 1, depois no modelo 2
        assert mock_post.call_count == 2
        first_call_url = mock_post.call_args_list[0][0][0]
        second_call_url = mock_post.call_args_list[1][0][0]
        assert "gemini-3.8-flash" in first_call_url
        assert "gemini-3.7-flash" in second_call_url

    def test_fallback_on_503_fast_fails_and_retries_next_batch(self):
        client = GeminiClient(api_key="test-key")

        resp_503 = type("MockResponse", (), {"status_code": 503, "text": "Model Overloaded"})()
        resp_200_fallback = type("MockResponse", (), {
            "status_code": 200,
            "json": lambda *args, **kwargs: {
                "candidates": [{"content": {"parts": [{"text": '{"result": "fallback_ok"}'}]}}]
            },
        })()
        resp_200_recovered = type("MockResponse", (), {
            "status_code": 200,
            "json": lambda *args, **kwargs: {
                "candidates": [{"content": {"parts": [{"text": '{"result": "recovered_ok"}'}]}}]
            },
        })()

        # Lote 1: 3.8 dá 503, pula imediatamente sem retry interno e vai para 3.7
        with patch("requests.post", side_effect=[resp_503, resp_200_fallback]) as mock_post:
            with patch("time.sleep"):
                res1 = client.generate(tier="flash", system_prompt="sys", user_content="batch 1")

        assert res1 == '{"result": "fallback_ok"}'
        # Apenas 2 chamadas: 1 tentativa no 3.8 (sem retry 2/2) + 1 chamada no 3.7
        assert mock_post.call_count == 2
        assert "gemini-3.8-flash" in mock_post.call_args_list[0][0][0]
        assert "gemini-3.7-flash" in mock_post.call_args_list[1][0][0]
        # O modelo 3.8 NÃO foi adicionado a exhausted_models (preservado para o próximo lote)
        assert len(client.exhausted_models) == 0

        # Lote 2: O modelo 3.8 é tentado novamente e desta vez tem sucesso!
        with patch("requests.post", side_effect=[resp_200_recovered]) as mock_post2:
            with patch("time.sleep"):
                res2 = client.generate(tier="flash", system_prompt="sys", user_content="batch 2")

        assert res2 == '{"result": "recovered_ok"}'
        assert mock_post2.call_count == 1
        assert "gemini-3.8-flash" in mock_post2.call_args_list[0][0][0]

    def test_thinking_unsupported_400_retry(self):
        client = GeminiClient(api_key="test-key")
        client.last_call_time = 0.0

        resp_400 = type("MockResponse", (), {
            "status_code": 400,
            "text": "Invalid JSON payload received. Unknown field 'thinkingConfig'",
        })()
        resp_200 = type("MockResponse", (), {
            "status_code": 200,
            "json": lambda *args, **kwargs: {
                "candidates": [{"content": {"parts": [{"text": '{"success": true}'}]}}]
            },
        })()

        with patch("requests.post", side_effect=[resp_400, resp_200]) as mock_post:
            with patch("time.sleep"):
                res = client.generate(tier="flash", system_prompt="sys", user_content="usr")

        assert res == '{"success": true}'
        assert mock_post.call_count == 2
        # Na segunda tentativa, thinkingConfig foi removido
        second_payload = mock_post.call_args_list[1][1]["json"]
        assert "thinkingConfig" not in second_payload["generationConfig"]


class TestTriageItem:
    def test_triage_item_true(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        with patch("ai.gemini_client.generate", return_value='{"relevant": true}') as mock_gen:
            res = triage_item("https://ex.com", "Concurso Juiz", "Texto longo sobre o certame " * 10)
        assert res is True
        mock_gen.assert_called_once()
        assert mock_gen.call_args[1]["tier"] == "lite"

    def test_triage_item_false(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        with patch("ai.gemini_client.generate", return_value='{"relevant": false}'):
            res = triage_item("https://ex.com", "Concurso Médico", "Texto longo sobre certame médico " * 10)
        assert res is False

    def test_triage_item_empty_response_fails_open(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        with patch("ai.gemini_client.generate", return_value=""):
            res = triage_item("https://ex.com", "Concurso Qualquer", "Texto longo " * 10)
        # Fail-open: garante que não descartamos edital em caso de timeout
        assert res is True


class TestEvaluateBatch:
    def test_evaluate_batch_success(self, monkeypatch):
        monkeypatch.setattr("ai.AI_API_KEY", "fake-key")
        items = [
            {"url": "https://a.com", "title": "Concurso PGM", "text": "Texto longo sobre procurador " * 10},
            {"url": "https://b.com", "title": "Concurso Saúde", "text": "Texto longo sobre enfermeiro " * 10},
        ]
        mock_ai_json = json.dumps([
            {
                "id": "0",
                "relevant": True,
                "career": "procuradorias",
                "reason": "Edital para procurador municipal",
                "group": "pgm-exemplo-procurador",
            },
            {
                "id": "1",
                "relevant": False,
                "reason": "Exclusivo para saúde",
            },
        ])

        with patch("ai.gemini_client.generate", return_value=mock_ai_json) as mock_gen:
            results = evaluate_batch(items)

        assert len(results) == 2
        assert results[0]["relevant"] is True
        assert results[0]["career"] == "procuradorias"
        assert results[0]["group"] == "pgm-exemplo-procurador"
        assert results[1]["relevant"] is False
        assert mock_gen.call_args[1]["tier"] == "flash"
        assert mock_gen.call_args[1]["enable_thinking"] is True

    def test_evaluate_batch_empty_list(self):
        assert evaluate_batch([]) == []


