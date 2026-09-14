"""Testes de orquestração do pipeline em scraper.py"""
from unittest.mock import MagicMock, patch

from scraper import _triage_single, analyze_item


class TestScraperPipeline:
    def test_triage_single_discarded(self, monkeypatch):
        db = {}
        candidate_items = []
        item = {"url": "https://concurso.exemplo.com/saude", "title": "Médico", "source": "scraping"}

        with patch("scraper.extract_page", return_value=("Médico", "Texto longo sobre certame médico " * 10, None)):
            with patch("scraper.triage_item", return_value=False):
                res = _triage_single(item, db, candidate_items, "2026-09-13T00:00:00Z", timeout=20)

        assert res == "discarded"
        assert len(candidate_items) == 0
        assert "https://concurso.exemplo.com/saude" in db
        assert db["https://concurso.exemplo.com/saude"]["source"] == "scraping"

    def test_triage_single_candidate(self, monkeypatch):
        db = {}
        candidate_items = []
        item = {"url": "https://concurso.exemplo.com/pgm", "title": "Procurador", "source": "scraping"}

        with patch("scraper.extract_page", return_value=("Procurador Municipal", "Texto longo sobre edital de procurador " * 10, None)):
            with patch("scraper.triage_item", return_value=True):
                res = _triage_single(item, db, candidate_items, "2026-09-13T00:00:00Z", timeout=20)

        assert res == "candidate"
        assert len(candidate_items) == 1
        assert candidate_items[0]["url"] == "https://concurso.exemplo.com/pgm"
        assert candidate_items[0]["real_title"] == "Procurador Municipal"

    def test_analyze_item_blocked_domain(self):
        db = {"_blocks_403": {"blocked.com": "2026-09-13T00:00:00Z"}}
        candidate_items = []
        item = {"url": "https://www.blocked.com/edital", "title": "Teste", "source": "scraping"}

        with patch("scraper.is_domain_blocked", return_value=True):
            res = analyze_item(item, db, candidate_items, "2026-09-13T00:00:00Z")

        assert res == "blocked"
        assert len(candidate_items) == 0
