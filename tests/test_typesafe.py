"""Testes do cliente TypeSafe AI / TypeSafe AI client tests"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from typesafe_client import TypeSafeClient


class TestTypeSafeClient:
    def test_missing_api_key_raises_value_error(self):
        client = TypeSafeClient(api_key="")
        with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
            client.call_system_one({"test": "data"}, {})

    @patch("requests.post")
    def test_call_system_one_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "model": "jev-1.13.0",
            "answers": {
                "has_legal_vacancies": {"type": "noul", "noul": 0.95},
            },
        }
        mock_post.return_value = mock_resp

        client = TypeSafeClient(api_key="test-key")
        res = client.call_system_one("some state", {"has_legal_vacancies": {}})

        assert res["model"] == "jev-1.13.0"
        assert res["answers"]["has_legal_vacancies"]["noul"] == 0.95
        mock_post.assert_called_once()

    @patch("time.sleep", return_value=None)
    @patch("requests.post")
    def test_call_system_one_rate_limit_backoff(self, mock_post, mock_sleep):
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0.1"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"answers": {}}

        mock_post.side_effect = [resp_429, resp_200]

        client = TypeSafeClient(api_key="test-key")
        res = client.call_system_one("state", {})
        assert res == {"answers": {}}
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(0.1)

    def test_extract_legal_snippet(self):
        client = TypeSafeClient(api_key="test-key")
        full_text = (
            "Aviso de licitação para reforma do prédio da prefeitura.\n"
            "Vagas para nível superior: Engenheiro Civil e Arquiteto.\n"
            "Também haverá vaga para Advogado Municipal com exigência de inscrição regular na OAB.\n"
            "Inscrições no site da prefeitura a partir de segunda-feira."
        )
        snippet = client._extract_legal_snippet(full_text)
        assert "Advogado Municipal" in snippet
        assert "OAB" in snippet
        # Parágrafos sem relação não devem predominar
        assert "Aviso de licitação" not in snippet

    @patch.object(TypeSafeClient, "call_system_one")
    def test_triage_direct_approval(self, mock_call):
        mock_call.return_value = {
            "answers": {
                "has_legal_vacancies": {"type": "noul", "noul": 0.98},
                "is_exclusive_non_legal": {"type": "noul", "noul": 0.02},
                "is_only_legislative_citation": {"type": "noul", "noul": 0.01},
                "career": {"type": "choice", "choice": "procuradorias", "confidence": 0.99},
                "stage": {"type": "choice", "choice": "edital_publicado", "confidence": 0.95},
            }
        }
        client = TypeSafeClient(api_key="test-key")
        result = client.triage("Concurso PGM", "Vaga para Procurador")

        assert result["relevant"] is True
        assert result["career"] == "procuradorias"
        assert result["deep_probed"] is False
        assert result["score"] > 0.85

    @patch.object(TypeSafeClient, "call_system_one")
    def test_triage_direct_discard(self, mock_call):
        mock_call.return_value = {
            "answers": {
                "has_legal_vacancies": {"type": "noul", "noul": 0.02},
                "is_exclusive_non_legal": {"type": "noul", "noul": 0.95},
                "is_only_legislative_citation": {"type": "noul", "noul": 0.80},
                "career": {"type": "choice", "choice": "none", "confidence": 1.0},
                "stage": {"type": "choice", "choice": "edital_publicado", "confidence": 0.90},
            }
        }
        client = TypeSafeClient(api_key="test-key")
        result = client.triage("Concurso Saúde", "Vagas para Médico e Enfermeiro")

        assert result["relevant"] is False
        assert result["career"] == "none"
        assert result["deep_probed"] is False
        assert result["score"] < 0.15

    @patch.object(TypeSafeClient, "call_system_one")
    def test_triage_uncertainty_triggers_deep_probe_positive(self, mock_call):
        # 1ª chamada: Zona cinzenta (score ~0.40, carreira não muito confiável)
        initial_resp = {
            "answers": {
                "has_legal_vacancies": {"type": "noul", "noul": 0.60},
                "is_exclusive_non_legal": {"type": "noul", "noul": 0.30},
                "is_only_legislative_citation": {"type": "noul", "noul": 0.10},
                "career": {"type": "choice", "choice": "administrativo", "confidence": 0.65},
                "stage": {"type": "choice", "choice": "edital_publicado", "confidence": 0.70},
            }
        }
        # 2ª chamada (Deep Probe): confirma exigência de Direito
        probe_resp = {
            "answers": {
                "requires_law_degree_explicitly": {"type": "noul", "noul": 0.92},
                "is_purely_non_legal": {"type": "noul", "noul": 0.05},
            }
        }
        mock_call.side_effect = [initial_resp, probe_resp]

        client = TypeSafeClient(api_key="test-key")
        result = client.triage("Concurso Misto", "Vagas gerais e Assessor Jurídico OAB")

        assert result["relevant"] is True
        assert result["career"] == "administrativo"
        assert result["deep_probed"] is True
        assert mock_call.call_count == 2

    @patch.object(TypeSafeClient, "call_system_one")
    def test_triage_uncertainty_triggers_deep_probe_negative(self, mock_call):
        # 1ª chamada: Zona cinzenta
        initial_resp = {
            "answers": {
                "has_legal_vacancies": {"type": "noul", "noul": 0.50},
                "is_exclusive_non_legal": {"type": "noul", "noul": 0.20},
                "is_only_legislative_citation": {"type": "noul", "noul": 0.30},
                "career": {"type": "choice", "choice": "none", "confidence": 0.60},
                "stage": {"type": "choice", "choice": "edital_publicado", "confidence": 0.70},
            }
        }
        # 2ª chamada (Deep Probe): rejeita por ser puramente não-jurídico
        probe_resp = {
            "answers": {
                "requires_law_degree_explicitly": {"type": "noul", "noul": 0.05},
                "is_purely_non_legal": {"type": "noul", "noul": 0.95},
            }
        }
        mock_call.side_effect = [initial_resp, probe_resp]

        client = TypeSafeClient(api_key="test-key")
        result = client.triage("Concurso Dúvida", "Apenas servidores da saúde citando lei")

        assert result["relevant"] is False
        assert result["career"] == "none"
        assert result["deep_probed"] is True
        assert mock_call.call_count == 2
