"""Orquestração do CuradorIA / CuradorIA orchestration

Este módulo só "amarra" as etapas: coleta de links/alerts, análise via IA,
geração de relatório. Constantes vivem em config.py, persistência em
storage.py, parsing/HTTP em extractor.py, IA em ai.py, HTML em report.py.

This module just "wires" the pipeline: link/alert collection, AI analysis,
report generation. Constants live in config.py, persistence in storage.py,
parsing/HTTP in extractor.py, AI in ai.py, HTML in report.py.
"""
import argparse
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ai import (
    consolidate_groups,
    evaluate_batch,
    triage_item,
)
from config import (
    API_PAUSE,
    GOOGLE_ALERTS_FEEDS,
    HEADERS,
    HISTORY_DIR,
    MAX_ABSENCES,
    OUTPUT_HTML,
    OUTPUT_NEW_LINKS,
    OUTPUT_RELEVANT,
    REPORT_URL,
    TARGET_URLS,
)
from extractor import (
    extract_page,
    extract_real_url,
    is_relevant_url,
    normalize_url,
)
from logger import setup_logging
from report import generate_html, group_relevant_items
from storage import (
    clear_expired_blocks,
    is_domain_blocked,
    is_url_in_failure_cooldown,
    load_database,
    record_processed,
    register_403_block,
    register_url_failure,
    save_database,
)

logger = logging.getLogger(__name__)


def get_brasilia_time() -> datetime:
    """Retorna a hora atual ajustada para Brasília / Returns current time in Brasília time zone"""
    return datetime.now(timezone(timedelta(hours=-3)))


# Coleta de links / Link collection
def collect_page_links(url: str, session: requests.Session) -> dict:
    """Coleta {url: texto_do_link} de uma página de listagem / Collects {url: anchor_text} from a listing page

    O texto do link serve como fallback de título (item 2.5) quando a página
    de destino não puder ser extraída. / The anchor text doubles as a title
    fallback when the destination page can't be extracted.
    """
    try:
        resp = session.get(url, timeout=20, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Falha em %s: %s", url, e)
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    links: dict[str, str] = {}
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        absolute = normalize_url(urljoin(url, href))
        if not is_relevant_url(absolute):
            continue
        link_text = tag.get_text(strip=True)
        # Mantém a primeira ocorrência com texto não-vazio / Keep first occurrence with non-empty text
        if absolute not in links or (link_text and not links[absolute]):
            links[absolute] = link_text

    logger.info("OK %s → %d links", url, len(links))
    return links


def collect_all_links() -> dict:
    """Itera URLs alvo e agrega {url: texto_do_link} / Iterates target URLs and aggregates {url: anchor_text}"""
    session = requests.Session()
    all_links: dict[str, str] = {}
    for url in TARGET_URLS:
        for k, v in collect_page_links(url, session).items():
            if k not in all_links or (v and not all_links[k]):
                all_links[k] = v
        time.sleep(1.5)
    return all_links


# Google Alerts
def read_alert_feed(feed_url: str, term: str) -> list:
    """Lê um feed RSS do Google Alerts / Reads a Google Alerts RSS feed"""
    try:
        resp = requests.get(feed_url, timeout=15, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Falha em feed %s: %s", feed_url, e)
        return []

    results = []
    try:
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            title = title_el.text if title_el is not None else ""
            link_el = entry.find("atom:link", ns)
            href = link_el.attrib.get("href", "") if link_el is not None else ""
            real_url = extract_real_url(href)
            real_url = normalize_url(real_url) if real_url else ""
            summary_el = entry.find("atom:summary", ns)
            snippet = ""
            if summary_el is not None and summary_el.text:
                snippet_soup = BeautifulSoup(summary_el.text, "html.parser")
                snippet = snippet_soup.get_text(separator=" ").strip()
            if real_url:
                results.append({"url": real_url, "title": title, "snippet": snippet, "term": term})
        logger.info("Alerta '%s' → %d resultados", term, len(results))
    except Exception as e:
        logger.error("Erro de parse em feed %s: %s", feed_url, e)
    return results


def collect_all_alerts() -> list:
    """Lê todos os feeds configurados / Reads all configured feeds"""
    all_alerts = []
    for feed in GOOGLE_ALERTS_FEEDS:
        all_alerts.extend(read_alert_feed(feed["url"], feed["term"]))
        time.sleep(1)
    return all_alerts


# Análise / Analysis
def _triage_single(item: dict, db: dict, candidate_items: list, now_utc: str, timeout: int) -> str:
    """Extrai conteúdo e executa a Triagem Ampla (Flash Lite) / Extracts page and runs Lite triage"""
    url = item["url"]
    source = item.get("source", "scraping")

    real_title, text, error = extract_page(url, timeout=timeout)

    if error == "403":
        register_403_block(db, url)
        return "403"
    if error == "timeout":
        register_url_failure(db, url, "timeout", source, now_utc)
        return "timeout"
    if not text or len(text) < 50:
        logger.info("Sem texto extraído em %s, pulando.", url)
        register_url_failure(db, url, "empty", source, now_utc)
        return "error"

    title = real_title or item.get("title", "")
    item_meta: dict = {}
    is_candidate = triage_item(url, title, text, item_metadata=item_meta)

    if not is_candidate:
        logger.info("  ↳ [JEV] Descartado: sem relação com carreiras jurídicas.")
        record_processed(db, url, source, now_utc)
        return "discarded"

    logger.info("  ↳ [JEV] Pré-aprovado (%s) para refinamento Flash.", item_meta.get("career", "juridico"))
    candidate_items.append({
        **item,
        "real_title": real_title,
        "text": text,
        **item_meta,
    })
    return "candidate"


def analyze_item(item: dict, db: dict, candidate_items: list, now_utc: str) -> str:
    """Triagem inicial de um item com verificação prévia de bloqueios e cooldown"""
    url = item["url"]
    if is_domain_blocked(db, url):
        d = urlparse(url).netloc.replace("www.", "")
        logger.info("Domínio '%s' bloqueado por 403, pulando.", d)
        return "blocked"
    if is_url_in_failure_cooldown(db, url):
        failures = db[url].get("consecutive_failures", 0)
        logger.info("URL em cooldown (%d falhas), pulando.", failures)
        return "cooldown"
    return _triage_single(item, db, candidate_items, now_utc, timeout=20)


def process_retry(item: dict, db: dict, candidate_items: list, now_utc: str, timeout: int, attempt_num: int) -> str:
    """Retry de extração para itens que deram timeout com timeout progressivo reduzido"""
    logger.info("Retry %d/3 (%ds) em %s", attempt_num, timeout, item["url"])
    return _triage_single(item, db, candidate_items, now_utc, timeout=timeout)


# Identificação de novos itens / New item identification
def _identify_new_items(all_links: dict, alerts_links: set, alerts_results: list, db: dict, now_utc: str) -> tuple:
    """Separa URLs em "novas", "para retentar" e atualiza last_seen das conhecidas

    / Splits URLs into "new", "to retry" and updates last_seen on known ones."""
    new_scraping: list = []
    new_alerts: list = []
    retried_after_cooldown = 0

    def _build_alert_item(url: str) -> dict:
        info = next((r for r in alerts_results if r["url"] == url), None)
        return info or {"url": url, "title": "", "snippet": "", "term": ""}

    for url, fallback_title in all_links.items():
        source = "alert" if url in alerts_links else "scraping"

        if url not in db:
            if source == "alert":
                new_alerts.append(_build_alert_item(url))
            else:
                new_scraping.append({"url": url, "title": fallback_title})
            continue

        entry = db[url]
        had_failures = entry.get("consecutive_failures", 0) > 0
        cooldown_active = is_url_in_failure_cooldown(db, url)

        entry["last_seen"] = now_utc
        entry["consecutive_absences"] = 0
        entry["source"] = source

        # URL com falhas anteriores cujo cooldown expirou: retentar / Previously-failed URL whose cooldown expired: retry
        if had_failures and not cooldown_active:
            retried_after_cooldown += 1
            if source == "alert":
                new_alerts.append(_build_alert_item(url))
            else:
                new_scraping.append({"url": url, "title": fallback_title})

    return new_scraping, new_alerts, retried_after_cooldown


def _decay_absent_links(db: dict, all_links: dict) -> list:
    """Incrementa absences para URLs ausentes e remove as que ultrapassaram MAX_ABSENCES / Bumps absences and removes URLs over MAX_ABSENCES"""
    removed = []
    for url in list(db.keys()):
        if url.startswith("_"):
            continue
        if url not in all_links:
            db[url]["consecutive_absences"] += 1
            if db[url]["consecutive_absences"] >= MAX_ABSENCES:
                removed.append(url)
                del db[url]
    return removed


# Saída textual / Text output
def _write_new_links_file(new_scraping: list, new_alerts: list, removed_count: int, db_size: int, now_utc: str) -> None:
    """Escreve new_links.txt com listagem dos novos links / Writes new_links.txt"""
    total_new = len(new_scraping) + len(new_alerts)
    with open(OUTPUT_NEW_LINKS, "w", encoding="utf-8") as f:
        f.write(
            f"Verificação: {now_utc}\n"
            f"Links novos encontrados: {total_new}\n"
            f"  Scraping: {len(new_scraping)}\n"
            f"  Alertas:  {len(new_alerts)}\n"
            f"Removidos da base: {removed_count}\n"
            f"Total na base: {db_size}\n"
        )
        f.write("=" * 60 + "\n\n")
        if new_scraping:
            f.write("── NEW (scraping) ──\n\n")
            for item in sorted(new_scraping, key=lambda x: x["url"]):
                if item.get("title"):
                    f.write(f"{item['title']}\n  {item['url']}\n\n")
                else:
                    f.write(f"{item['url']}\n\n")
        if new_alerts:
            f.write("── NEW (Google Alerts) ──\n\n")
            for item in new_alerts:
                f.write(
                    f"Term:    {item.get('term', '')}\n"
                    f"Title:   {item.get('title', '')}\n"
                    f"URL:     {item.get('url', '')}\n"
                    f"Snippet: {item.get('snippet', '')}\n\n"
                )


def _write_relevant_file(relevant_items: list, total_new: int, now_utc: str) -> None:
    """Escreve new_relevant.txt com os itens classificados como relevantes / Writes new_relevant.txt"""
    with open(OUTPUT_RELEVANT, "w", encoding="utf-8") as f:
        f.write(
            f"Verificação: {now_utc}\n"
            f"Links analisados: {total_new}\n"
            f"Links relevantes: {len(relevant_items)}\n"
        )
        f.write("=" * 60 + "\n\n")
        for item in relevant_items:
            title = item.get("real_title") or item.get("title") or "(ver link)"
            f.write(
                f"Title:   {title}\n"
                f"URL:     {item.get('url', '')}\n"
                f"Career:   {item.get('career', '')}\n"
                f"Group:   {item.get('group', '')}\n"
                f"Reason:  {item.get('reason', '')}\n\n"
            )


# Função principal / Main
def _elapsed(t0: float) -> str:
    return f"{(time.time() - t0):.1f}s"


def _populate_sync(db: dict, all_links: dict, alerts_links: set, now_utc: str, date_str: str, is_first_run: bool = False) -> None:
    """Sincroniza/popula a base de dados com as URLs atuais sem executar chamadas de IA"""
    action_name = "Primeira execução" if is_first_run else "Repovoamento manual (--populate-only)"
    logger.info("%s: sincronizando a base de dados com links ativos hoje.", action_name)
    added_count = 0
    updated_count = 0
    for url in all_links:
        source = "alert" if url in alerts_links else "scraping"
        if url not in db:
            db[url] = {
                "first_seen": now_utc,
                "last_seen": now_utc,
                "consecutive_absences": 0,
                "source": source,
            }
            added_count += 1
        else:
            db[url]["last_seen"] = now_utc
            db[url]["consecutive_absences"] = 0
            db[url]["source"] = source
            updated_count += 1
    save_database(db)
    logger.info(
        "Base sincronizada com sucesso: %d adicionadas, %d atualizadas (Total: %d URLs). Zero chamadas de IA.",
        added_count,
        updated_count,
        len(db),
    )
    with open(OUTPUT_NEW_LINKS, "w", encoding="utf-8") as f:
        f.write(
            f"Sincronização ({action_name}) em {now_utc}.\n"
            f"Base atualizada com {len(db)} links ({added_count} novos, {updated_count} atualizados).\n"
            f"Nenhum link 'novo' para processamento de IA.\n"
        )
    with open(OUTPUT_RELEVANT, "w", encoding="utf-8") as f:
        f.write(
            f"Sincronização ({action_name}) em {now_utc}.\n"
            f"Nenhum link relevante acusado (modo sem IA).\n"
        )
    if is_first_run:
        with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(generate_html([], date_str, 0, 0))


def main():
    parser = argparse.ArgumentParser(description="CuradorIA - Coleta e curadoria de concursos jurídicos")
    parser.add_argument("--populate-only", action="store_true", help="Apenas sincroniza a base com as URLs ativas sem chamar a IA")
    args = parser.parse_args()

    setup_logging()
    run_start = time.time()
    now_utc = datetime.now(timezone.utc).isoformat()
    br_time = get_brasilia_time()
    date_str = br_time.strftime("%d/%m/%Y às %Hh%M")

    logger.info("=" * 60)
    logger.info("CuradorIA de Carreiras Jurídicas — Execução: %s", date_str)
    if args.populate_only:
        logger.info("MODO: --populate-only ativo (repovoamento sem chamadas de IA)")
    logger.info("=" * 60)

    db = load_database()
    db_size_start = sum(1 for k in db if not k.startswith("_"))
    first_run = len(db) == 0
    logger.info("Base de dados: %d URLs conhecidas", db_size_start)
    blocked_domains = list(db.get("_blocks_403", {}).keys())
    if blocked_domains:
        logger.info("Domínios bloqueados (403): %s", ", ".join(blocked_domains))
    clear_expired_blocks(db)

    t0 = time.time()
    logger.info("Coletando links das páginas-alvo...")
    scraping_titles = collect_all_links()  # dict[url, fallback_title]
    logger.info("Total scraping: %d (%s)", len(scraping_titles), _elapsed(t0))

    t0 = time.time()
    logger.info("Lendo Google Alerts...")
    alerts_results = collect_all_alerts()
    alerts_links = {r["url"] for r in alerts_results if r["url"]}
    logger.info("Total alertas: %d (%s)", len(alerts_links), _elapsed(t0))

    # Mescla alerts no mesmo dicionário {url: fallback_title} / Merge alerts into the same dict
    all_links = dict(scraping_titles)
    for url in alerts_links:
        if url not in all_links:
            all_links[url] = ""

    if first_run or args.populate_only:
        _populate_sync(db, all_links, alerts_links, now_utc, date_str, is_first_run=first_run)
        return

    new_scraping, new_alerts, retried_after_cooldown = _identify_new_items(
        all_links, alerts_links, alerts_results, db, now_utc
    )
    removed_links = _decay_absent_links(db, all_links)

    total_new = len(new_scraping) + len(new_alerts)
    logger.info("Links novos: %d (%d scraping + %d alertas)", total_new, len(new_scraping), len(new_alerts))
    if retried_after_cooldown:
        logger.info("Reincluídos após cooldown expirado: %d", retried_after_cooldown)
    logger.info("Links removidos da base (ausentes %dx): %d", MAX_ABSENCES, len(removed_links))
    logger.info("Links já conhecidos (atualizados): %d", len(all_links) - total_new)

    _write_new_links_file(new_scraping, new_alerts, len(removed_links), len(db), now_utc)

    logger.info("Iniciando Etapa 1: Triagem de %d novos links via Gemini Flash Lite...", total_new)
    candidate_items: list = []
    timeout_queue: list = []
    results_count = {
        "candidate": 0,
        "discarded": 0,
        "blocked": 0,
        "cooldown": 0,
        "403": 0,
        "timeout": 0,
        "error": 0,
    }

    all_new_items = [
        {"url": item["url"], "title": item.get("title", ""), "source": "scraping"}
        for item in new_scraping
    ]
    all_new_items.extend([{**item, "source": "alert"} for item in new_alerts])

    t0 = time.time()
    for i, item in enumerate(all_new_items, 1):
        source_tag = "alerta" if item.get("source") == "alert" else "scraping"
        logger.info("[%d/%d] [%s] %s", i, total_new, source_tag, item["url"])
        result = analyze_item(item, db, candidate_items, now_utc)
        results_count[result] = results_count.get(result, 0) + 1
        if result == "timeout":
            timeout_queue.append(item)
    logger.info("Triagem inicial concluída em %s (%d pré-aprovados)", _elapsed(t0), len(candidate_items))

    RETRY_TIMEOUTS = [10, 5]
    for i, timeout_sec in enumerate(RETRY_TIMEOUTS):
        if not timeout_queue:
            break
        attempt_num = i + 2
        has_next = i + 1 < len(RETRY_TIMEOUTS)
        logger.info("Retentando %d link(s) com timeout (tentativa %d, %ds)...", len(timeout_queue), attempt_num, timeout_sec)
        next_queue = []
        for item in timeout_queue:
            result = process_retry(item, db, candidate_items, now_utc, timeout_sec, attempt_num)
            results_count[result] = results_count.get(result, 0) + 1
            if result == "timeout":
                if has_next:
                    next_queue.append(item)
                else:
                    logger.warning("TIMEOUT DEFINITIVO em %s — registrado para cooldown.", item["url"])
        timeout_queue = next_queue

    relevant_items: list = []
    if candidate_items:
        batch_size = 3
        total_batches = (len(candidate_items) + batch_size - 1) // batch_size
        logger.info(
            "Iniciando Etapa 2: Validação analítica de %d candidatos em %d lotes via Gemini Flash (Extended Thinking)...",
            len(candidate_items),
            total_batches,
        )
        t_flash = time.time()

        for b_idx in range(0, len(candidate_items), batch_size):
            batch = candidate_items[b_idx : b_idx + batch_size]
            current_batch_num = (b_idx // batch_size) + 1
            logger.info("Processando lote %d/%d (%d notícias)...", current_batch_num, total_batches, len(batch))

            evaluations = evaluate_batch(batch)
            for cand, eval_result in zip(batch, evaluations):
                url = cand["url"]
                source = cand.get("source", "scraping")
                record_processed(db, url, source, now_utc)

                if eval_result.get("relevant"):
                    career = eval_result.get("career", "administrativo")
                    group = eval_result.get("group", "")
                    reason = eval_result.get("reason", "")
                    logger.info("  ✓ [FLASH CONFIRMADO] [%s | %s]: %s", career, group, reason[:120])
                    relevant_items.append({
                        **cand,
                        "reason": reason,
                        "career": career,
                        "group": group,
                    })
                else:
                    logger.info("  ✗ [FLASH FALSO POSITIVO]: %s", eval_result.get("reason", "")[:120])

        logger.info("Validação Flash concluída em %s", _elapsed(t_flash))
    else:
        logger.info("Nenhum candidato pré-aprovado na Triagem Lite; chamadas Flash dispensadas.")

    save_database(db)
    db_size_end = sum(1 for k in db if not k.startswith("_"))

    if len(relevant_items) > 1:
        logger.info("Iniciando Etapa 3: Consolidação e unificação de grupos via Gemini Flash...")
        consolidate_groups(relevant_items)

    _write_relevant_file(relevant_items, total_new, now_utc)

    groups = group_relevant_items(relevant_items)
    logger.info("Gerando relatório HTML...")
    total_time = time.time() - run_start

    today_iso = br_time.strftime("%Y-%m-%d")
    today_filename = f"report-{today_iso}.html"
    os.makedirs(HISTORY_DIR, exist_ok=True)

    history_files = sorted(
        (f for f in os.listdir(HISTORY_DIR) if f.startswith("report-") and f.endswith(".html")),
        reverse=True,
    )
    history_entries = [
        {
            "date": f[len("report-"):-len(".html")],
            "filename": f"{HISTORY_DIR}/{f}",
            "is_current": False,
        }
        for f in history_files
    ]
    today_entry = {"date": today_iso, "filename": f"{HISTORY_DIR}/{today_filename}", "is_current": True}
    history_entries = [
        e for e in history_entries if e["filename"] != today_entry["filename"]
    ]
    history_entries.insert(0, today_entry)
    history_entries = history_entries[:30]

    # Versão "atual" (report.html na raiz) com índice de histórico / "Current" version with history index
    html_current = generate_html(
        groups,
        date_str,
        total_new,
        len(relevant_items),
        run_seconds=total_time,
        history=history_entries,
    )
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_current)

    # Versão arquivada (history/report-YYYY-MM-DD.html) com link de retorno / Archived version with back link
    html_archived = generate_html(
        groups,
        date_str,
        total_new,
        len(relevant_items),
        run_seconds=total_time,
        archive_link=f"../{OUTPUT_HTML}",
    )
    with open(os.path.join(HISTORY_DIR, today_filename), "w", encoding="utf-8") as f:
        f.write(html_archived)

    logger.info("=" * 60)
    logger.info("RESUMO DA EXECUÇÃO (%.0fs no total)", total_time)
    logger.info("=" * 60)
    logger.info("Links coletados:  %d (%d scraping + %d alertas)", len(all_links), len(scraping_titles), len(alerts_links))
    logger.info("Links novos:      %d", total_new)
    logger.info("Links removidos:  %d", len(removed_links))
    logger.info("Base: %d → %d URLs", db_size_start, db_size_end)
    logger.info(
        "Triagem Lite:   %d candidatos | %d descartados | %d bloqueados | %d cooldown | %d timeouts/erros",
        results_count.get("candidate", 0),
        results_count.get("discarded", 0),
        results_count.get("blocked", 0),
        results_count.get("cooldown", 0),
        results_count.get("timeout", 0) + results_count.get("error", 0) + results_count.get("403", 0),
    )
    logger.info("Validação Flash: %d confirmados relevantes de %d pré-selecionados", len(relevant_items), len(candidate_items))
    logger.info("Grupos finais:   %d grupo(s)", len(groups))
    logger.info("Relatório:       %s", REPORT_URL)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
