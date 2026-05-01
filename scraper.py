import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
import trafilatura

# Importa a inteligência (ai.py) e o visual (report.py)
from ai import evaluate_relevance
from report import group_relevant_items, generate_html

# ─── Configurações gerais ─────────────────────────────────────────────────────
TARGET_URLS = [
    "https://www.pciconcursos.com.br/previstos/",
    "https://www.pciconcursos.com.br/noticias/",
    "https://www.pciconcursos.com.br/ultimas/",
    "https://www.acheconcursos.com.br/concursos-atualizados-recentemente",
    "https://www.acheconcursos.com.br/concursos-previstos",
    "https://www.acheconcursos.com.br/concursos-abertos",
]

GOOGLE_ALERTS_FEEDS = [
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/13784085206058947900", "term": "seletivo concurso residencia juridica"},
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/10699205725319407642", "term": "seletivo concurso procurador"},
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/15459908627525988139", "term": "seletivo concurso advogado"},
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/5648081314456116013", "term": "seletivo concurso estagio de pos graduacao direito"},
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/15126815070692715421", "term": "seletivo concurso analista juridico"},
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/4736851925661048284", "term": "seletivo concurso assessor juridico"},
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/2563769251380958392", "term": "seletivo concurso tecnico juridico"},
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/16659093265726736111", "term": "seletivo concurso consultor legislativo"},
    {"url": "https://www.google.com/alerts/feeds/05883152892408713569/4996675272987879500", "term": "seletivo concurso direito"},
]

GITHUB_USER = "paulodantasii"
GITHUB_REPO = "curadoria-carreiras-juridicas"
REPORT_URL = f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}/report.html"

DATABASE_FILE = "database.json"
OUTPUT_NEW_LINKS = "new_links.txt"
OUTPUT_RELEVANT = "new_relevant.txt"
OUTPUT_HTML = "report.html"

MAX_ABSENCES = 3
MAX_PAGE_CHARS = 6000
API_PAUSE = 2.0
BLOCK_403_DAYS = 30

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TARGET_DOMAINS = {"pciconcursos.com.br", "acheconcursos.com.br"}

RELEVANT_PATTERNS = [r"/concurso", r"/noticia", r"/edital", r"/concursos/", r"/previstos", r"/abertos", r"/autorizados", r"/inscricoes", r"/cronograma", r"/ultimas", r"/noticias", r"/portal/\d{4}/", r"/portal/[a-z0-9-]+/$"]
IGNORE_PATTERNS = [r"/(login|cadastro|conta|assinar|assine|newsletter)", r"\.(jpg|jpeg|png|gif|pdf|zip|rar|mp4|svg|css|js)$", r"/(tag|autor|author|page|pagina)/", r"#", r"javascript:", r"mailto:", r"whatsapp:"]


# ─── Utilitários básicos ──────────────────────────────────────────────────────
def get_brasilia_time() -> datetime:
    """Retorna a hora atual do servidor ajustada ao fuso horário de Brasília"""
    return datetime.now(timezone(timedelta(hours=-3)))

def is_relevant_url(url: str) -> bool:
    """Checks if the captured link belongs to the allowed domains or patterns."""
    host = urlparse(url).netloc.replace("www.", "")
    if not any(d in host for d in TARGET_DOMAINS): return False
    for p in IGNORE_PATTERNS:
        if re.search(p, url, re.IGNORECASE): return False
    for p in RELEVANT_PATTERNS:
        if re.search(p, url, re.IGNORECASE): return True
    return False

def normalize_url(url: str) -> str:
    """Removes anchor fragments (#) from links to avoid duplicate URLs."""
    url = url.split("#")[0].strip()
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()

def extract_real_url(href: str) -> str:
    """Unwraps URLs provided by Google Alerts that come masked."""
    parsed = urlparse(href)
    if "google.com" in parsed.netloc and parsed.path == "/url":
        qs = parse_qs(parsed.query)
        if "url" in qs: return unquote(qs["url"][0])
    return href

# ─── 403 Block Management ─────────────────────────────────────────────────
def is_domain_blocked(db: dict, url: str) -> bool:
    """Checks if the domain is currently blocked due to a prior 403 response."""
    blocks = db.get("_blocks_403", {})
    d = urlparse(url).netloc.replace("www.", "")
    if d not in blocks: return False
    block_date = datetime.fromisoformat(blocks[d])
    deadline = block_date + timedelta(days=BLOCK_403_DAYS)
    return datetime.now(timezone.utc) < deadline

def register_403_block(db: dict, url: str) -> None:
    """Records the domain as blocked in the database after a 403 error."""
    if "_blocks_403" not in db: db["_blocks_403"] = {}
    d = urlparse(url).netloc.replace("www.", "")
    now = datetime.now(timezone.utc).isoformat()
    db["_blocks_403"][d] = now
    print(f"    [403 BLOQUEADO] Domínio '{d}' bloqueado por {BLOCK_403_DAYS} dias.")

def clear_expired_blocks(db: dict) -> None:
    """Removes block records for domains whose block period has expired."""
    blocks = db.get("_blocks_403", {})
    now = datetime.now(timezone.utc)
    expired = [d for d, date_str in blocks.items() if now >= datetime.fromisoformat(date_str) + timedelta(days=BLOCK_403_DAYS)]
    for d in expired:
        del blocks[d]
        print(f"  [403] Bloqueio vencido para '{d}', domínio liberado para novo teste.")

# ─── Web Scraping ─────────────────────────────────────────────────────────
def collect_page_links(url: str, session: requests.Session) -> set:
    """Opens a target page and collects all valid news links within it."""
    try:
        resp = session.get(url, timeout=20, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [ERRO] {url} → {e}")
        return set()

    soup = BeautifulSoup(resp.text, "html.parser")
    links = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        absolute = urljoin(url, href)
        absolute = normalize_url(absolute)
        if is_relevant_url(absolute):
            links.add(absolute)

    print(f"  [OK] {url} → {len(links)} links")
    return links

def collect_all_links() -> set:
    """Iterates over all target URLs calling the link collection function."""
    session = requests.Session()
    all_links = set()
    for url in TARGET_URLS:
        links = collect_page_links(url, session)
        all_links.update(links)
        time.sleep(1.5)
    return all_links

# ─── Google Alerts ────────────────────────────────────────────────────────
def read_alert_feed(feed_url: str, term: str) -> list:
    """Reads the Google Alerts RSS feed and extracts the links notified by Google."""
    try:
        resp = requests.get(feed_url, timeout=15, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [ERRO feed] {feed_url} → {e}")
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
            summary_el = entry.find("atom:summary", ns)
            snippet = ""
            if summary_el is not None and summary_el.text:
                soup = BeautifulSoup(summary_el.text, "html.parser")
                snippet = soup.get_text(separator=" ").strip()
            if real_url:
                results.append({"url": real_url, "title": title, "snippet": snippet, "term": term})
        print(f"  [Alerta] '{term}' → {len(results)} resultados")
    except Exception as e:
        print(f"  [ERRO parse] {feed_url} → {e}")
    return results

def collect_all_alerts() -> list:
    all_alerts = []
    for feed in GOOGLE_ALERTS_FEEDS:
        results = read_alert_feed(feed["url"], feed["term"])
        all_alerts.extend(results)
        time.sleep(1)
    return all_alerts

# ─── Page Content Extraction ──────────────────────────────────────────────
def extract_page(url: str, timeout: int = 20) -> tuple:
    """Extracts only the useful text body from a page, ignoring menus and ads."""
    try:
        resp = requests.get(url, timeout=timeout, headers=HEADERS)
        resp.raise_for_status()
        html_content = resp.text

        # 1. Pega o Título
        soup = BeautifulSoup(html_content, "html.parser")
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        if not title:
            h1 = soup.find("h1")
            if h1: title = h1.get_text(strip=True)

        # 2. Usa a inteligência do trafilatura para isolar o miolo do artigo
        text = trafilatura.extract(html_content, include_comments=False)

        # 3. Fallback: Se o trafilatura falhar, usa a limpeza manual pelo BeautifulSoup
        if not text:
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()

        return title, text[:MAX_PAGE_CHARS], ""

    except requests.exceptions.Timeout:
        print(f"    [TIMEOUT] {url}")
        return "", "", "timeout"
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print(f"    [ERRO página] {url} → 403 Client Error: Forbidden")
            return "", "", "403"
        print(f"    [ERRO página] {url} → {e}")
        return "", "", ""
    except Exception as e:
        print(f"    [ERRO página] {url} → {e}")
        return "", "", ""

# ─── JSON Database Management ─────────────────────────────────────────────
def load_database() -> dict:
    if not os.path.exists(DATABASE_FILE): return {}
    with open(DATABASE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_database(db: dict) -> None:
    with open(DATABASE_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

# ─── Item Analysis and Validation ─────────────────────────────────────────
def analyze_item(item: dict, db: dict, relevant_items: list, now_utc: str) -> str:
    """Extracts and sends the item to the AI for approval/rejection."""
    url = item["url"]
    if is_domain_blocked(db, url):
        d = urlparse(url).netloc.replace("www.", "")
        print(f"    [BLOQUEADO] Domínio '{d}' bloqueado por 403. Pulando.")
        return "blocked"

    real_title, text, error = extract_page(url)

    if error == "403":
        register_403_block(db, url)
        return "403"
    if error == "timeout":
        return "timeout"
    if not text or len(text) < 50:
        print("    Sem texto extraído, pulando.")
        return "error"

    title = real_title or item.get("title", "")
    evaluation = evaluate_relevance(url, title, text)
    reason = evaluation.get("reason", "")
    print(f"    → relevante: {evaluation.get('relevant')} | {reason}")

    if reason == "error after 3 attempts":
        return "ai_error"

    # Marks the URL as already processed in the database
    db[url] = {
        "first_seen": now_utc,
        "last_seen": now_utc,
        "consecutive_absences": 0,
        "source": item.get("source", "scraping"),
    }

    if evaluation.get("relevant"):
        relevant_items.append({
            **item,
            "real_title": real_title,
            "reason": reason,
            "status": evaluation.get("status", ""),
            "group": evaluation.get("group", ""),
        })
    return "ok"

def process_retry(item: dict, db: dict, relevant_items: list, now_utc: str, timeout: int, attempt_num: int) -> str:
    """Retries downloading a page that previously timed out."""
    url = item["url"]
    print(f"  [Retry {attempt_num}/3 | {timeout}s] {url}")
    real_title, text, error = extract_page(url, timeout=timeout)

    if error == "403":
        register_403_block(db, url)
        return "403"
    if error == "timeout":
        return "timeout"
    if not text or len(text) < 50:
        print("    Sem texto extraído, pulando.")
        return "error"

    title = real_title or item.get("title", "")
    evaluation = evaluate_relevance(url, title, text)
    reason = evaluation.get("reason", "")
    print(f"    → relevante: {evaluation.get('relevant')} | {reason}")

    if reason == "error after 3 attempts":
        return "ai_error"

    db[url] = {
        "first_seen": now_utc,
        "last_seen": now_utc,
        "consecutive_absences": 0,
        "source": item.get("source", "scraping"),
    }

    if evaluation.get("relevant"):
        relevant_items.append({
            **item,
            "real_title": real_title,
            "reason": reason,
            "status": evaluation.get("status", ""),
            "group": evaluation.get("group", ""),
        })
    return "ok"

# ─── Main Function ────────────────────────────────────────────────────────
def main():
    now_utc = datetime.now(timezone.utc).isoformat()
    br_time = get_brasilia_time()
    date_str = br_time.strftime("%d/%m/%Y às %Hh%M")

    print(f"\n{'='*60}")
    print(f"  CuradorIA de Carreiras Jurídicas")
    print(f"  Execução: {date_str}")
    print(f"{'='*60}\n")

    db = load_database()
    first_run = len(db) == 0
    clear_expired_blocks(db)

    print("Coletando links das páginas-alvo...")
    scraping_links = collect_all_links()
    print(f"Total scraping: {len(scraping_links)}\n")

    print("Lendo Google Alertas...")
    alerts_results = collect_all_alerts()
    alerts_links = {r["url"] for r in alerts_results if r["url"]}
    print(f"Total alertas: {len(alerts_links)}\n")

    all_links = scraping_links | alerts_links

    if first_run:
        print("Primeira execução: populando a base de dados.")
        for url in all_links:
            db[url] = {
                "first_seen": now_utc,
                "last_seen": now_utc,
                "consecutive_absences": 0,
                "source": "alert" if url in alerts_links else "scraping",
            }
        save_database(db)
        with open(OUTPUT_NEW_LINKS, "w", encoding="utf-8") as f:
            f.write(f"Primeira execução em {now_utc}.\nBase criada com {len(db)} links.\nNenhum link 'novo' acusado.\n")
        with open(OUTPUT_RELEVANT, "w", encoding="utf-8") as f:
            f.write(f"Primeira execução em {now_utc}.\nNenhum link relevante acusado.\n")
        with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(generate_html([], date_str, 0, 0))
        return

    new_scraping = []
    new_alerts = []

    for url in all_links:
        source = "alert" if url in alerts_links else "scraping"
        if url not in db:
            if source == "alert":
                info = next((r for r in alerts_results if r["url"] == url), {})
                new_alerts.append(info if info else {"url": url, "title": "", "snippet": "", "term": ""})
            else:
                new_scraping.append(url)
        else:
            db[url]["last_seen"] = now_utc
            db[url]["consecutive_absences"] = 0
            db[url]["source"] = source

    removed_links = []
    for url in list(db.keys()):
        if url.startswith("_"): continue
        if url not in all_links:
            db[url]["consecutive_absences"] += 1
            if db[url]["consecutive_absences"] >= MAX_ABSENCES:
                removed_links.append(url)
                del db[url]

    total_new = len(new_scraping) + len(new_alerts)
    with open(OUTPUT_NEW_LINKS, "w", encoding="utf-8") as f:
        f.write(f"Verificação: {now_utc}\nLinks novos encontrados: {total_new}\n  Scraping: {len(new_scraping)}\n  Alertas:  {len(new_alerts)}\nRemovidos da base: {len(removed_links)}\nTotal na base: {len(db)}\n")
        f.write("=" * 60 + "\n\n")
        if new_scraping:
            f.write("── NEW (scraping) ──\n\n")
            for url in sorted(new_scraping): f.write(url + "\n")
            f.write("\n")
        if new_alerts:
            f.write("── NEW (Google Alerts) ──\n\n")
            for item in new_alerts:
                f.write(f"Term:    {item.get('term', '')}\nTitle:   {item.get('title', '')}\nURL:     {item.get('url', '')}\nSnippet: {item.get('snippet', '')}\n\n")

    print(f"\nAnalisando {total_new} links novos via IA...\n")
    relevant_items = []
    ai_errors = 0
    timeout_queue = []

    all_new_items = [{"url": url, "title": "", "source": "scraping"} for url in new_scraping]
    all_new_items.extend([{**item, "source": "alert"} for item in new_alerts])

    for i, item in enumerate(all_new_items, 1):
        print(f"  [{i}/{total_new}] {item['url']}")
        result = analyze_item(item, db, relevant_items, now_utc)
        if result == "timeout": timeout_queue.append(item)
        elif result == "ai_error": ai_errors += 1
        if result == "ok": time.sleep(API_PAUSE)

    RETRY_TIMEOUTS = [10, 5]
    for i, timeout_sec in enumerate(RETRY_TIMEOUTS):
        if not timeout_queue: break
        attempt_num = i + 2
        has_next = i + 1 < len(RETRY_TIMEOUTS)
        print(f"\nRetentando {len(timeout_queue)} link(s) com timeout ({attempt_num}ª tentativa, {timeout_sec}s)...\n")
        next_queue = []
        for item in timeout_queue:
            result = process_retry(item, db, relevant_items, now_utc, timeout_sec, attempt_num)
            if result == "timeout":
                if has_next: next_queue.append(item)
                else: print(f"    [TIMEOUT DEFINITIVO] {item['url']} — não entra na base.")
            elif result == "ai_error": ai_errors += 1
            if result == "ok": time.sleep(API_PAUSE)
        timeout_queue = next_queue

    save_database(db)

    with open(OUTPUT_RELEVANT, "w", encoding="utf-8") as f:
        f.write(f"Verificação: {now_utc}\nLinks analisados: {total_new}\nLinks relevantes: {len(relevant_items)}\n")
        f.write("=" * 60 + "\n\n")
        for item in relevant_items:
            title = item.get("real_title") or item.get("title") or "(ver link)"
            f.write(f"Title:   {title}\nURL:     {item.get('url', '')}\nStatus:  {item.get('status', '')}\nGroup:   {item.get('group', '')}\nReason:  {item.get('reason', '')}\n\n")

    groups = group_relevant_items(relevant_items)
    print("Gerando relatório HTML...")
    html = generate_html(groups, date_str, total_new, len(relevant_items))
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f: f.write(html)

    print(f"\nRelevantes: {len(relevant_items)}/{total_new} em {len(groups)} grupo(s)")
    print(f"Relatório: {REPORT_URL}")

if __name__ == "__main__":
    main()
