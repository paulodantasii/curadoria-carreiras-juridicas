import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

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

DATABASE_FILE = "database.json"
OUTPUT_FILE = "novos_links.txt"
MAX_AUSENCIAS = 3  # apaga da base após 3 verificações sem aparecer

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Domínios relevantes: só links internos de cada site-alvo são coletados
DOMINIOS_ALVO = {
    "pciconcursos.com.br",
    "jcconcursos.com.br",
    "acheconcursos.com.br",
    "cj.estrategia.com",
}

# Padrões de URL que indicam conteúdo (artigos, concursos, notícias)
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
    r"/portal/\d{4}/",   # cj.estrategia: posts com ano
    r"/portal/[a-z0-9-]+/$",  # cj.estrategia: slugs de artigos
]

# Padrões a ignorar (páginas de navegação, categorias genéricas, etc.)
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
    """Retorna True se a URL é de conteúdo relevante (artigo/concurso)."""
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
    """Remove trailing slash duplicada e fragmentos."""
    url = url.split("#")[0].strip()
    parsed = urlparse(url)
    # reconstrói sem fragmento
    return parsed._replace(fragment="").geturl()


# ─── Scraping ─────────────────────────────────────────────────────────────────

def coletar_links_pagina(url: str, sessao: requests.Session) -> set[str]:
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

    print(f"  [OK] {url} → {len(links)} links relevantes")
    return links


def coletar_todos_links() -> set[str]:
    sessao = requests.Session()
    todos = set()
    for url in URLS_ALVO:
        links = coletar_links_pagina(url, sessao)
        todos.update(links)
        time.sleep(1.5)  # pausa entre requests para não sobrecarregar
    return todos


# ─── Base de dados ────────────────────────────────────────────────────────────

def carregar_base() -> dict:
    """
    Estrutura da base:
    {
        "url": {
            "primeira_vez": "ISO8601",
            "ultima_vez_visto": "ISO8601",
            "ausencias_consecutivas": 0
        }
    }
    """
    if not os.path.exists(DATABASE_FILE):
        return {}
    with open(DATABASE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_base(base: dict) -> None:
    with open(DATABASE_FILE, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)


# ─── Lógica principal ─────────────────────────────────────────────────────────

def main():
    agora = datetime.now(timezone.utc).isoformat()
    print(f"\n=== Execução: {agora} ===\n")

    base = carregar_base()
    primeira_execucao = len(base) == 0

    print("Coletando links das páginas-alvo...")
    links_encontrados = coletar_todos_links()
    print(f"\nTotal de links coletados nesta execução: {len(links_encontrados)}\n")

    if primeira_execucao:
        print("Primeira execução: populando a base de dados.")
        for url in links_encontrados:
            base[url] = {
                "primeira_vez": agora,
                "ultima_vez_visto": agora,
                "ausencias_consecutivas": 0,
            }
        salvar_base(base)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(
                f"Primeira execução em {agora}.\n"
                f"Base criada com {len(base)} links.\n"
                "Nenhum link 'novo' acusado (todos são a base inicial).\n"
            )
        print(f"Base criada com {len(base)} links. Arquivo '{OUTPUT_FILE}' registrado.")
        return

    # ── Verificação normal ────────────────────────────────────────────────────
    novos = []

    for url in links_encontrados:
        if url not in base:
            novos.append(url)
            base[url] = {
                "primeira_vez": agora,
                "ultima_vez_visto": agora,
                "ausencias_consecutivas": 0,
            }
        else:
            base[url]["ultima_vez_visto"] = agora
            base[url]["ausencias_consecutivas"] = 0

    # Incrementa ausências para links não encontrados nesta rodada
    removidos = []
    for url in list(base.keys()):
        if url not in links_encontrados:
            base[url]["ausencias_consecutivas"] += 1
            if base[url]["ausencias_consecutivas"] >= MAX_AUSENCIAS:
                removidos.append(url)
                del base[url]

    salvar_base(base)

    # ── Saída ─────────────────────────────────────────────────────────────────
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"Verificação: {agora}\n")
        f.write(f"Links novos encontrados: {len(novos)}\n")
        f.write(f"Links removidos da base (3 ausências): {len(removidos)}\n")
        f.write(f"Total na base após atualização: {len(base)}\n")
        f.write("=" * 60 + "\n\n")
        if novos:
            for url in sorted(novos):
                f.write(url + "\n")
        else:
            f.write("Nenhum link novo encontrado.\n")

    print(f"Novos links: {len(novos)}")
    print(f"Removidos da base: {len(removidos)}")
    print(f"Total na base: {len(base)}")
    print(f"Resultado salvo em '{OUTPUT_FILE}'.")


if __name__ == "__main__":
    main()
