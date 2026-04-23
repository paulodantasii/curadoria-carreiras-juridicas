import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

# ─── Configuração ────────────────────────────────────────────────────────────

URLS_ALVO = [
    "https://www.pciconcursos.com.br/previstos/",
    "https://www.pciconcursos.com.br/noticias/",
    "https://www.pciconcursos.com.br/ultimas/",
    "https://jcconcursos.com.br/noticia/concursos",
    "https://jcconcursos.com.br/noticia/concursos?page=2",
    "https://jcconcursos.com.br/noticia/empregos",
    "https://jcconcursos.com.br/noticia/empregos?page=2",
    "https://jcconcursos.com.br/concursos/previstos",
    "https://jcconcursos.com.br/concursos/autorizados",
    "https://jcconcursos.com.br/concursos/inscricoes-abertas",
    "https://jcconcursos.com.br/cronograma-geral/",
    "https://www.acheconcursos.com.br/concursos-atualizados-recentemente",
    "https://www.acheconcursos.com.br/concursos-previstos",
    "https://www.acheconcursos.com.br/concursos-abertos",
    "https://cj.estrategia.com/portal/",
    "https://cj.estrategia.com/portal/page/2/",
    "https://cj.estrategia.com/portal/page/3/",
    "https://cj.estrategia.com/portal/page/4/",
    "https://cj.estrategia.com/portal/page/5/",
    "https://cj.estrategia.com/portal/page/6/",
    "https://cj.estrategia.com/portal/page/7/",
    "https://cj.estrategia.com/portal/page/8/",
    "https://cj.estrategia.com/portal/page/9/",
    "https://cj.estrategia.com/portal/page/10/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/2/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/3/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/4/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/5/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/6/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/7/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/8/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/9/",
    "https://cj.estrategia.com/portal/carreiras-juridicas/page/10/",
    "https://cj.estrategia.com/portal/procuradoria/",
    "https://cj.estrategia.com/portal/procuradoria/page/2/",
    "https://cj.estrategia.com/portal/procuradoria/page/3/",
    "https://cj.estrategia.com/portal/procuradoria/page/4/",
    "https://cj.estrategia.com/portal/procuradoria/page/5/",
    "https://cj.estrategia.com/portal/procuradoria/page/6/",
    "https://cj.estrategia.com/portal/procuradoria/page/7/",
    "https://cj.estrategia.com/portal/procuradoria/page/8/",
    "https://cj.estrategia.com/portal/procuradoria/page/9/",
    "https://cj.estrategia.com/portal/procuradoria/page/10/",
]

# Feed RSS do Google Alertas
GOOGLE_ALERTAS_FEEDS = [
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/13784085206058947900",
        "termo": "residencia jurídica estágio de pós graduação",
    },
]

DATABASE_FILE = "database.json"
OUTPUT_FILE = "novos_links.txt"
MAX_AUSENCIAS = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DOMINIOS_ALVO = {
    "pciconcursos.com.br",
    "jcconcursos.com.br",
    "acheconcursos.com.br",
    "cj.estrategia.com",
}

PADROES_RELEVANTES = [
    r"/concurso",
    r"/noticia",
    r"/edital",
    r"/concursos/",
    r"/previstos",
    r"/abertos",
    r"/autorizados",
    r"/inscricoes",
    r"/cronograma",
    r"/ultimas",
    r"/noticias",
    r"/portal/\d{4}/",
    r"/portal/[a-z0-9-]+/$",
]

PADROES_IGNORAR = [
    r"/(login|cadastro|conta|assinar|assine|newsletter)",
    r"\.(jpg|jpeg|png|gif|pdf|zip|rar|mp4|svg|css|js)$",
    r"/(tag|autor|author|page|pagina)/",
    r"#",
    r"javascript:",
    r"mailto:",
    r"whatsapp:",
]


# ─── Utilitários ──────────────────────────────────────────────────────────────

def dominio(url: str) -> str:
    host = urlparse(url).netloc
    return host.replace("www.", "")


def eh_relevante(url: str) -> bool:
    dom = dominio(url)
    if not any(d in dom for d in DOMINIOS_ALVO):
        return False
    for p in PADROES_IGNORAR:
        if re.search(p, url, re.IGNORECASE):
            return False
    for p in PADROES_RELEVANTES:
        if re.search(p, url, re.IGNORECASE):
            return True
    return False


def normalizar(url: str) -> str:
    url = url.split("#")[0].strip()
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def extrair_url_real(href: str) -> str:
    """
    Links do Google Alertas chegam encapsulados como:
    https://www.google.com/url?rct=j&sa=t&url=https://site.com/artigo&...
    Esta função extrai a URL real do parâmetro 'url'.
    """
    parsed = urlparse(href)
    if "google.com" in parsed.netloc and parsed.path == "/url":
        qs = parse_qs(parsed.query)
        if "url" in qs:
            return unquote(qs["url"][0])
    return href


# ─── Scraping das páginas-alvo ────────────────────────────────────────────────

def coletar_links_pagina(url: str, sessao: requests.Session) -> set:
    try:
        resp = sessao.get(url, timeout=20, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [ERRO] {url} → {e}")
        return set()

    soup = BeautifulSoup(resp.text, "html.parser")
    links = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        absoluto = urljoin(url, href)
        absoluto = normalizar(absoluto)
        if eh_relevante(absoluto):
            links.add(absoluto)

    print(f"  [OK] {url} → {len(links)} links")
    return links


def coletar_todos_links() -> set:
    sessao = requests.Session()
    todos = set()
    for url in URLS_ALVO:
        links = coletar_links_pagina(url, sessao)
        todos.update(links)
        time.sleep(1.5)
    return todos


# ─── Google Alertas RSS ───────────────────────────────────────────────────────

def ler_feed_alerta(feed_url: str, termo: str) -> list:
    """
    Lê um feed RSS do Google Alertas e retorna lista de:
    {url, title, snippet, termo}
    """
    try:
        resp = requests.get(feed_url, timeout=15, headers=HEADERS)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [ERRO feed] {feed_url} → {e}")
        return []

    resultados = []
    try:
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            # Título
            title_el = entry.find("atom:title", ns)
            title = title_el.text if title_el is not None else ""

            # URL real (dentro do link encapsulado do Google)
            link_el = entry.find("atom:link", ns)
            href = link_el.attrib.get("href", "") if link_el is not None else ""
            url_real = extrair_url_real(href)

            # Trecho/resumo
            summary_el = entry.find("atom:summary", ns)
            snippet = ""
            if summary_el is not None and summary_el.text:
                # Remove tags HTML do snippet
                soup = BeautifulSoup(summary_el.text, "html.parser")
                snippet = soup.get_text(separator=" ").strip()

            if url_real:
                resultados.append({
                    "url": url_real,
                    "title": title,
                    "snippet": snippet,
                    "termo": termo,
                })

        print(f"  [Alerta] '{termo}' → {len(resultados)} resultados")
    except Exception as e:
        print(f"  [ERRO parse] {feed_url} → {e}")

    return resultados


def coletar_todos_alertas() -> list:
    todos = []
    for feed in GOOGLE_ALERTAS_FEEDS:
        resultados = ler_feed_alerta(feed["url"], feed["termo"])
        todos.extend(resultados)
        time.sleep(1)
    return todos


# ─── Base de dados ────────────────────────────────────────────────────────────

def carregar_base() -> dict:
    if not os.path.exists(DATABASE_FILE):
        return {}
    with open(DATABASE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_base(base: dict) -> None:
    with open(DATABASE_FILE, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)


# ─── Principal ────────────────────────────────────────────────────────────────

def main():
    agora = datetime.now(timezone.utc).isoformat()
    print(f"\n=== Execução: {agora} ===\n")

    base = carregar_base()
    primeira_execucao = len(base) == 0

    print("Coletando links das páginas-alvo...")
    links_scraping = coletar_todos_links()
    print(f"Total scraping: {len(links_scraping)}\n")

    print("Lendo Google Alertas...")
    resultados_alertas = coletar_todos_alertas()
    links_alertas = {r["url"] for r in resultados_alertas if r["url"]}
    print(f"Total alertas: {len(links_alertas)}\n")

    todos_links = links_scraping | links_alertas

    if primeira_execucao:
        print("Primeira execução: populando a base de dados.")
        for url in todos_links:
            base[url] = {
                "primeira_vez": agora,
                "ultima_vez_visto": agora,
                "ausencias_consecutivas": 0,
                "fonte": "alerta" if url in links_alertas else "scraping",
            }
        salvar_base(base)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(
                f"Primeira execução em {agora}.\n"
                f"Base criada com {len(base)} links "
                f"({len(links_scraping)} scraping + {len(links_alertas)} alertas).\n"
                "Nenhum link 'novo' acusado (todos são a base inicial).\n"
            )
        print(f"Base criada com {len(base)} links.")
        return

    # Verificação normal
    novos_scraping = []
    novos_alertas = []

    for url in todos_links:
        fonte = "alerta" if url in links_alertas else "scraping"
        if url not in base:
            if fonte == "alerta":
                info = next((r for r in resultados_alertas if r["url"] == url), {})
                novos_alertas.append(info if info else {"url": url, "title": "", "snippet": "", "termo": ""})
            else:
                novos_scraping.append(url)
            base[url] = {
                "primeira_vez": agora,
                "ultima_vez_visto": agora,
                "ausencias_consecutivas": 0,
                "fonte": fonte,
            }
        else:
            base[url]["ultima_vez_visto"] = agora
            base[url]["ausencias_consecutivas"] = 0

    removidos = []
    for url in list(base.keys()):
        if url not in todos_links:
            base[url]["ausencias_consecutivas"] += 1
            if base[url]["ausencias_consecutivas"] >= MAX_AUSENCIAS:
                removidos.append(url)
                del base[url]

    salvar_base(base)

    total_novos = len(novos_scraping) + len(novos_alertas)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"Verificação: {agora}\n")
        f.write(f"Links novos encontrados: {total_novos}\n")
        f.write(f"  Scraping: {len(novos_scraping)}\n")
        f.write(f"  Alertas:  {len(novos_alertas)}\n")
        f.write(f"Removidos da base: {len(removidos)}\n")
        f.write(f"Total na base: {len(base)}\n")
        f.write("=" * 60 + "\n\n")

        if novos_scraping:
            f.write("── NOVOS (scraping) ──\n\n")
            for url in sorted(novos_scraping):
                f.write(url + "\n")
            f.write("\n")

        if novos_alertas:
            f.write("── NOVOS (Google Alertas) ──\n\n")
            for item in novos_alertas:
                f.write(f"Termo:   {item.get('termo', '')}\n")
                f.write(f"Título:  {item.get('title', '')}\n")
                f.write(f"URL:     {item.get('url', '')}\n")
                f.write(f"Trecho:  {item.get('snippet', '')}\n\n")

        if total_novos == 0:
            f.write("Nenhum link novo encontrado.\n")

    print(f"Novos scraping: {len(novos_scraping)}")
    print(f"Novos alertas:  {len(novos_alertas)}")
    print(f"Removidos: {len(removidos)}")
    print(f"Total na base: {len(base)}")
    print(f"Salvo em '{OUTPUT_FILE}'.")


if __name__ == "__main__":
    main()
