import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from html import escape

import requests
from bs4 import BeautifulSoup

# ─── Configuração ────────────────────────────────────────────────────────────

URLS_ALVO = [
    "https://www.pciconcursos.com.br/previstos/",
    "https://www.pciconcursos.com.br/noticias/",
    "https://www.pciconcursos.com.br/ultimas/",
    "https://www.acheconcursos.com.br/concursos-atualizados-recentemente",
    "https://www.acheconcursos.com.br/concursos-previstos",
    "https://www.acheconcursos.com.br/concursos-abertos",
]

GOOGLE_ALERTAS_FEEDS = [
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/13784085206058947900",
        "termo": "seletivo concurso residencia juridica",
    },
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/10699205725319407642",
        "termo": "seletivo concurso procurador",
    },
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/15459908627525988139",
        "termo": "seletivo concurso advogado",
    },
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/5648081314456116013",
        "termo": "seletivo concurso estagio de pos graduacao direito",
    },
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/15126815070692715421",
        "termo": "seletivo concurso analista juridico",
    },
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/4736851925661048284",
        "termo": "seletivo concurso assessor juridico",
    },
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/2563769251380958392",
        "termo": "seletivo concurso tecnico juridico",
    },
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/16659093265726736111",
        "termo": "seletivo concurso consultor legislativo",
    },
    {
        "url": "https://www.google.com/alerts/feeds/05883152892408713569/4996675272987879500",
        "termo": "seletivo concurso direito",
    },
]

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = "whatsapp:+14155238886"
TWILIO_TO = f"whatsapp:{os.environ.get('WHATSAPP_NUMBER', '')}"
GITHUB_USER = "paulodantasii"
GITHUB_REPO = "curadoria-carreiras-juridicas"
URL_RELATORIO = f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}/relatorio.html"

DATABASE_FILE = "database.json"
OUTPUT_NOVOS = "novos_links.txt"
OUTPUT_RELEVANTES = "novos_relevantes.txt"
OUTPUT_HTML = "relatorio.html"
MAX_AUSENCIAS = 3
MAX_CHARS_PAGINA = 6000
PAUSA_API = 2.0
DIAS_BLOQUEIO_403 = 30

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
    "acheconcursos.com.br",
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

PROMPT_RELEVANCIA = """Sua tarefa é avaliar se o conteúdo abaixo é um artigo de atualização, previsão, ou divulgação, de edital, concurso, processo seletivo, certame, e similares, que sejam relevantes para um bacharel em Direito que estuda para concursos públicos nas seguintes áreas:
RELEVANTE — sempre que o conteúdo tiver:
- Procurador ou Advogado em qualquer órgão do executivo ou legislativo: AGU, PGFN, PGF, PGE, PGM, câmaras municipais, assembleias legislativas, TCU, TCE, TCM, agências reguladoras federais como ANATEL, ANEEL, ANVISA, ANAC, ANS, ANA, ANTAQ, ANTT, ANP, CADE, Banco Central (BACEN), conselhos profissionais como OAB, CRM, CREA, CFM, CFBM, CRBM, CONFEA, etc
- Procurador ou Advogado da Caixa Econômica Federal, Banco do Brasil, Petrobras, BNDES, Correios, EBSERH, Embrapa, Serpro, DATAPREV, autarquias e fundações federais, estaduais e municipais, etc
- Analista ou Assessor de matéria jurídica ou correlatas em órgãos do executivo federal, estadual ou municipal, secretarias, ministérios, autarquias, agências reguladoras, empresas públicas, etc
- Analista ou Assessor de matéria jurídica ou correlatas de Tribunal de Contas como TCU, TCE, TCM, etc
- Cargos que exijam bacharelado em Direito e cujo conteúdo programático envolva direito público, como: administrativo, constitucional, tributário, civil, financeiro, licitações, contratos públicos, execução fiscal, etc
- Residência Jurídica em qualquer órgão público
- Estágio de pós-graduação em Direito em qualquer órgão público
- Programas de formação jurídica remunerada em órgãos públicos
- Todos os cargos que, por algum dos motivos acima, pareçam necessitar de curso superior (diploma) em Direito mas não estejam incluídos nessa lista
NÃO RELEVANTE — se o conteúdo for integralmente apenas sobre:
- Cargos que NÃO exijam formação (curso superior/bacharelato/diploma) em Direito, como, por exemplo: professores de ensino básico, médicos, engenheiros, enfermeiros, saúde, limpeza, motoristas, técnicos de outras áreas, etc
- Cargos de nível médio ou técnico sem relevância jurídica
Responda APENAS no seguinte formato JSON, sem nenhum texto adicional:
{"relevante": true, "motivo": "explicação em duas linha, não reafirme que é relevante para bacharéis em Direito, diga o cargo ou o contexto suficiente para ficar subentendido"}
ou
{"relevante": false, "motivo": "explicação em uma linha"}
Conteúdo para avaliar:
"""

PROMPT_RESUMO = """Com base nos resultados abaixo, escreva um resumo, sem introdução, em texto corrido (entre 900 e 1000 caracteres) dos artigos encontrados, mencionando os cargos e órgãos, ou inscrições, ou provas, etc, priorizando o cargos e carreiras mais importantes no resumo."""


# ─── Utilitários ──────────────────────────────────────────────────────────────

def agora_brasilia() -> datetime:
    return datetime.now(timezone(timedelta(hours=-3)))


def nome_site(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    return host.upper()


def eh_relevante_url(url: str) -> bool:
    host = urlparse(url).netloc.replace("www.", "")
    if not any(d in host for d in DOMINIOS_ALVO):
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
    parsed = urlparse(href)
    if "google.com" in parsed.netloc and parsed.path == "/url":
        qs = parse_qs(parsed.query)
        if "url" in qs:
            return unquote(qs["url"][0])
    return href


# ─── Bloqueios 403 ────────────────────────────────────────────────────────────

def dominio_bloqueado(base: dict, url: str) -> bool:
    """Verifica se o domínio da URL está bloqueado e se o prazo ainda não venceu."""
    bloqueios = base.get("_bloqueios_403", {})
    d = urlparse(url).netloc.replace("www.", "")
    if d not in bloqueios:
        return False
    data_bloqueio = datetime.fromisoformat(bloqueios[d])
    prazo = data_bloqueio + timedelta(days=DIAS_BLOQUEIO_403)
    return datetime.now(timezone.utc) < prazo


def registrar_bloqueio_403(base: dict, url: str) -> None:
    """Registra o domínio como bloqueado por 403 a partir de agora."""
    if "_bloqueios_403" not in base:
        base["_bloqueios_403"] = {}
    d = urlparse(url).netloc.replace("www.", "")
    agora = datetime.now(timezone.utc).isoformat()
    base["_bloqueios_403"][d] = agora
    print(f"    [403 BLOQUEADO] Domínio '{d}' bloqueado por {DIAS_BLOQUEIO_403} dias.")


def limpar_bloqueios_vencidos(base: dict) -> None:
    """Remove da lista de bloqueios os domínios cujo prazo já venceu."""
    bloqueios = base.get("_bloqueios_403", {})
    agora = datetime.now(timezone.utc)
    vencidos = [
        d for d, data_str in bloqueios.items()
        if agora >= datetime.fromisoformat(data_str) + timedelta(days=DIAS_BLOQUEIO_403)
    ]
    for d in vencidos:
        del bloqueios[d]
        print(f"  [403] Bloqueio vencido para '{d}', domínio liberado para novo teste.")


# ─── Scraping ─────────────────────────────────────────────────────────────────

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
        if eh_relevante_url(absoluto):
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
            title_el = entry.find("atom:title", ns)
            title = title_el.text if title_el is not None else ""
            link_el = entry.find("atom:link", ns)
            href = link_el.attrib.get("href", "") if link_el is not None else ""
            url_real = extrair_url_real(href)
            summary_el = entry.find("atom:summary", ns)
            snippet = ""
            if summary_el is not None and summary_el.text:
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


# ─── Extração de texto e título ───────────────────────────────────────────────

def extrair_pagina(url: str, timeout: int = 20) -> tuple:
    """Retorna (titulo, texto, erro) onde erro pode ser '403', 'timeout' ou ''."""
    try:
        resp = requests.get(url, timeout=timeout, headers=HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        titulo = ""
        if soup.title and soup.title.string:
            titulo = soup.title.string.strip()
        if not titulo:
            h1 = soup.find("h1")
            if h1:
                titulo = h1.get_text(strip=True)

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        texto = soup.get_text(separator=" ", strip=True)
        texto = re.sub(r"\s+", " ", texto).strip()
        return titulo, texto[:MAX_CHARS_PAGINA], ""

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


# ─── IA ───────────────────────────────────────────────────────────────────────

def chamar_openai(prompt: str) -> str:
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 400,
    }
    for tentativa in range(3):
        try:
            resp = requests.post(
                OPENAI_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                },
                json=payload,
                timeout=45,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"    [ERRO OpenAI tentativa {tentativa+1}/3] → {e}")
            if tentativa < 2:
                time.sleep(10 * (tentativa + 1))
    return ""


def avaliar_relevancia(url: str, titulo: str, texto: str) -> dict:
    if not OPENAI_API_KEY:
        return {"relevante": False, "motivo": "OPENAI_API_KEY não configurada"}
    if not texto or len(texto) < 50:
        return {"relevante": False, "motivo": "texto insuficiente"}

    conteudo = f"URL: {url}\nTítulo: {titulo}\n\nTexto:\n{texto}"
    resposta = chamar_openai(PROMPT_RELEVANCIA + conteudo)
    if not resposta:
        return {"relevante": False, "motivo": "erro após 3 tentativas"}
    try:
        resposta = re.sub(r"```json|```", "", resposta).strip()
        return json.loads(resposta)
    except Exception:
        return {"relevante": False, "motivo": "erro ao interpretar resposta"}


def gerar_resumo_whatsapp(relevantes: list) -> str:
    if not OPENAI_API_KEY or not relevantes:
        return ""
    lista = "\n".join(
        f"- {item.get('titulo_real') or item.get('title') or item.get('url')} | {item.get('motivo', '')}"
        for item in relevantes
    )
    resposta = chamar_openai(PROMPT_RESUMO + "\n\nResultados:\n" + lista)
    if not resposta:
        return ""
    # Trunca no limite de 1000 caracteres sem cortar no meio de uma palavra
    if len(resposta) > 1000:
        resposta = resposta[:1000].rsplit(" ", 1)[0] + "..."
    return resposta


# ─── Relatório HTML ───────────────────────────────────────────────────────────

def gerar_html(relevantes: list, data_str: str, total_analisados: int) -> str:
    cards = ""
    for item in relevantes:
        titulo = item.get("titulo_real") or item.get("title") or "Ver link"
        titulo = re.sub(r"\s*[|\-–]\s*.{3,40}$", "", titulo).strip()
        titulo = escape(titulo)
        url = item.get("url", "")
        motivo = escape(item.get("motivo", ""))
        tag = nome_site(url)

        cards += f"""
        <div class="card">
            <span class="tag">{tag}</span>
            <h2><a href="{url}" target="_blank">{titulo}</a></h2>
            <p class="motivo">{motivo}</p>
            <a href="{url}" target="_blank" class="btn">Acessar matéria →</a>
        </div>
        """

    if not relevantes:
        cards = '<div class="vazio">Nenhuma oportunidade relevante encontrada nesta verificação.</div>'

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CuradorIA de Carreiras Jurídicas</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f0f2f5;
            color: #1a1a2e;
            min-height: 100vh;
        }}
        header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            padding: 2rem 1.5rem 1.5rem;
            text-align: center;
        }}
        header h1 {{
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: 0.5px;
            margin-bottom: 0.4rem;
        }}
        header p {{
            font-size: 0.85rem;
            opacity: 0.75;
        }}
        .badge {{
            display: inline-block;
            background: #e94560;
            color: white;
            font-size: 0.8rem;
            font-weight: 600;
            padding: 0.3rem 0.8rem;
            border-radius: 20px;
            margin-top: 0.8rem;
        }}
        .container {{
            max-width: 680px;
            margin: 0 auto;
            padding: 1.5rem 1rem;
        }}
        .card {{
            background: white;
            border-radius: 12px;
            padding: 1.2rem 1.3rem;
            margin-bottom: 1rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.07);
            border-left: 4px solid #e94560;
        }}
        .tag {{
            display: inline-block;
            background: #f0f2f5;
            color: #555;
            font-size: 0.72rem;
            font-weight: 600;
            padding: 0.2rem 0.6rem;
            border-radius: 6px;
            letter-spacing: 0.3px;
            margin-bottom: 0.6rem;
        }}
        .card h2 {{
            font-size: 1rem;
            font-weight: 600;
            line-height: 1.4;
            margin-bottom: 0.5rem;
            color: #1a1a2e;
        }}
        .card h2 a {{
            color: inherit;
            text-decoration: none;
        }}
        .card h2 a:hover {{
            color: #e94560;
        }}
        .motivo {{
            font-size: 0.85rem;
            color: #666;
            line-height: 1.5;
            margin-bottom: 0.9rem;
        }}
        .btn {{
            display: inline-block;
            background: #1a1a2e;
            color: white;
            font-size: 0.82rem;
            font-weight: 600;
            padding: 0.45rem 1rem;
            border-radius: 8px;
            text-decoration: none;
        }}
        .btn:hover {{
            background: #e94560;
        }}
        .vazio {{
            text-align: center;
            color: #888;
            padding: 3rem 1rem;
            font-size: 0.95rem;
        }}
        footer {{
            text-align: center;
            padding: 1.5rem;
            font-size: 0.78rem;
            color: #aaa;
        }}
    </style>
</head>
<body>
    <header>
        <h1>🤖 CuradorIA de Carreiras Jurídicas ⚖️</h1>
        <p>Verificação de {data_str} · {total_analisados} artigos analisados</p>
        <div class="badge">{len(relevantes)} oportunidade(s) relevante(s)</div>
    </header>
    <div class="container">
        {cards}
    </div>
    <footer>Gerado automaticamente · CuradorIA de Carreiras Jurídicas</footer>
</body>
</html>"""


# ─── WhatsApp ─────────────────────────────────────────────────────────────────

def enviar_whatsapp(mensagem: str) -> None:
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("  [AVISO] Credenciais WhatsApp não configuradas. Pulando envio.")
        return
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    for tentativa in range(3):
        try:
            resp = requests.post(
                url,
                data={"From": TWILIO_FROM, "To": TWILIO_TO, "Body": mensagem},
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                timeout=30,
            )
            if resp.status_code in (200, 201):
                print("  [WhatsApp] Mensagem enviada com sucesso.")
                return
            else:
                print(f"  [WhatsApp] Erro {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"  [WhatsApp tentativa {tentativa+1}/3] Erro: {e}")
            if tentativa < 2:
                time.sleep(10)
    print("  [WhatsApp] Falha após 3 tentativas.")


def formatar_mensagem_whatsapp(data_str: str, total_novos: int, relevantes: list, resumo: str, erros_ia: int = 0) -> str:
    cabecalho = (
        f"🤖 CuradorIA de Carreiras Jurídicas ⚖️ - {data_str}\n"
        f"{len(relevantes)} artigo(s) relevante(s) encontrado(s).\n\n"
    )
    if not relevantes:
        msg = cabecalho + "Nenhum artigo relevante encontrado hoje."
        if erros_ia > 0:
            msg += f"\n\n⚠️ {erros_ia} artigo(s) não analisado(s) por erro na API."
        return msg

    aviso_erros = f"\n\n⚠️ {erros_ia} artigo(s) não analisado(s) por erro na API." if erros_ia > 0 else ""
    rodape = f"\n\n🔗 {URL_RELATORIO}{aviso_erros}"
    corpo = resumo if resumo else "Veja a CuradorIA completa no link abaixo."

    mensagem = cabecalho + corpo + rodape
    if len(mensagem) > 1500:
        espaco = 1500 - len(cabecalho) - len(rodape) - 3
        corpo = corpo[:espaco].rsplit(" ", 1)[0] + "..."
        mensagem = cabecalho + corpo + rodape

    return mensagem


# ─── Base de dados ────────────────────────────────────────────────────────────

def carregar_base() -> dict:
    if not os.path.exists(DATABASE_FILE):
        return {}
    with open(DATABASE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_base(base: dict) -> None:
    with open(DATABASE_FILE, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)


# ─── Análise de um item ───────────────────────────────────────────────────────

def analisar_item(item: dict, base: dict, relevantes: list, agora_utc: str) -> str:
    """
    Tenta extrair e avaliar um item. Retorna:
    - "ok"       → verificado com sucesso (entra na base)
    - "403"      → bloqueado pelo site
    - "timeout"  → não respondeu no tempo
    - "bloqueado"→ domínio já bloqueado por 403 anterior
    - "erro"     → outro erro sem retry útil
    - "erro_ia"  → falha na API da IA
    """
    url = item["url"]

    if dominio_bloqueado(base, url):
        d = urlparse(url).netloc.replace("www.", "")
        print(f"    [BLOQUEADO] Domínio '{d}' bloqueado por 403. Pulando.")
        return "bloqueado"

    titulo_real, texto, erro = extrair_pagina(url)

    if erro == "403":
        registrar_bloqueio_403(base, url)
        return "403"

    if erro == "timeout":
        return "timeout"

    if not texto or len(texto) < 50:
        print("    Sem texto extraído, pulando.")
        return "erro"

    titulo = titulo_real or item.get("title", "")
    avaliacao = avaliar_relevancia(url, titulo, texto)
    motivo = avaliacao.get("motivo", "")
    print(f"    → relevante: {avaliacao.get('relevante')} | {motivo}")

    if motivo == "erro após 3 tentativas":
        return "erro_ia"

    # Verificação bem-sucedida: insere na base
    base[url] = {
        "primeira_vez": agora_utc,
        "ultima_vez_visto": agora_utc,
        "ausencias_consecutivas": 0,
        "fonte": item.get("fonte", "scraping"),
    }

    if avaliacao.get("relevante"):
        relevantes.append({
            **item,
            "titulo_real": titulo_real,
            "motivo": motivo,
        })

    return "ok"


def processar_retry(item: dict, base: dict, relevantes: list, agora_utc: str,
                    timeout: int, numero: int) -> str:
    """
    Executa uma tentativa de retry para um item que deu timeout.
    Retorna "ok", "403", "timeout", "erro" ou "erro_ia".
    """
    url = item["url"]
    print(f"  [Retry {numero}/3 | {timeout}s] {url}")

    titulo_real, texto, erro = extrair_pagina(url, timeout=timeout)

    if erro == "403":
        registrar_bloqueio_403(base, url)
        return "403"

    if erro == "timeout":
        return "timeout"

    if not texto or len(texto) < 50:
        print("    Sem texto extraído, pulando.")
        return "erro"

    titulo = titulo_real or item.get("title", "")
    avaliacao = avaliar_relevancia(url, titulo, texto)
    motivo = avaliacao.get("motivo", "")
    print(f"    → relevante: {avaliacao.get('relevante')} | {motivo}")

    if motivo == "erro após 3 tentativas":
        return "erro_ia"

    base[url] = {
        "primeira_vez": agora_utc,
        "ultima_vez_visto": agora_utc,
        "ausencias_consecutivas": 0,
        "fonte": item.get("fonte", "scraping"),
    }

    if avaliacao.get("relevante"):
        relevantes.append({**item, "titulo_real": titulo_real, "motivo": motivo})

    return "ok"


# ─── Principal ────────────────────────────────────────────────────────────────

def main():
    agora_utc = datetime.now(timezone.utc).isoformat()
    agora_br = agora_brasilia()
    data_str = agora_br.strftime("%d/%m/%Y às %Hh%M")

    print(f"\n{'='*60}")
    print(f"  CuradorIA de Carreiras Jurídicas")
    print(f"  Execução: {data_str}")
    print(f"{'='*60}\n")

    base = carregar_base()
    primeira_execucao = len(base) == 0

    limpar_bloqueios_vencidos(base)

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
                "primeira_vez": agora_utc,
                "ultima_vez_visto": agora_utc,
                "ausencias_consecutivas": 0,
                "fonte": "alerta" if url in links_alertas else "scraping",
            }
        salvar_base(base)
        with open(OUTPUT_NOVOS, "w", encoding="utf-8") as f:
            f.write(
                f"Primeira execução em {agora_utc}.\n"
                f"Base criada com {len(base)} links "
                f"({len(links_scraping)} scraping + {len(links_alertas)} alertas).\n"
                "Nenhum link 'novo' acusado (todos são a base inicial).\n"
            )
        with open(OUTPUT_RELEVANTES, "w", encoding="utf-8") as f:
            f.write(f"Primeira execução em {agora_utc}.\nNenhum link relevante acusado.\n")
        with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(gerar_html([], data_str, 0))
        print(f"Base criada com {len(base)} links.")
        return

    # ── Verificação normal ────────────────────────────────────────────────────
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
        else:
            base[url]["ultima_vez_visto"] = agora_utc
            base[url]["ausencias_consecutivas"] = 0
            base[url]["fonte"] = fonte

    removidos = []
    for url in list(base.keys()):
        if url.startswith("_"):
            continue
        if url not in todos_links:
            base[url]["ausencias_consecutivas"] += 1
            if base[url]["ausencias_consecutivas"] >= MAX_AUSENCIAS:
                removidos.append(url)
                del base[url]

    # ── novos_links.txt ───────────────────────────────────────────────────────
    total_novos = len(novos_scraping) + len(novos_alertas)
    with open(OUTPUT_NOVOS, "w", encoding="utf-8") as f:
        f.write(f"Verificação: {agora_utc}\n")
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

    # ── Análise IA ────────────────────────────────────────────────────────────
    print(f"\nAnalisando {total_novos} links novos via IA...\n")
    relevantes = []
    erros_ia = 0
    fila_timeout = []

    todos_novos = []
    for url in novos_scraping:
        todos_novos.append({"url": url, "title": "", "fonte": "scraping"})
    for item in novos_alertas:
        todos_novos.append({**item, "fonte": "alerta"})

    for i, item in enumerate(todos_novos, 1):
        print(f"  [{i}/{total_novos}] {item['url']}")
        resultado = analisar_item(item, base, relevantes, agora_utc)
        if resultado == "timeout":
            fila_timeout.append(item)
        elif resultado == "erro_ia":
            erros_ia += 1
        if resultado == "ok":
            time.sleep(PAUSA_API)

    # ── Retry de timeouts ─────────────────────────────────────────────────────
    # Tentativas com timeouts progressivamente menores: 10s e 5s
    RETRY_TIMEOUTS = [10, 5]

    for i, timeout_seg in enumerate(RETRY_TIMEOUTS):
        if not fila_timeout:
            break
        tentativa_num = i + 2  # começa em 2 para manter o log legível
        tem_proxima = i + 1 < len(RETRY_TIMEOUTS)
        print(f"\nRetentando {len(fila_timeout)} link(s) com timeout ({tentativa_num}ª tentativa, {timeout_seg}s)...\n")
        proxima_fila = []
        for item in fila_timeout:
            resultado = processar_retry(item, base, relevantes, agora_utc, timeout_seg, tentativa_num)
            if resultado == "timeout":
                if tem_proxima:
                    proxima_fila.append(item)
                else:
                    print(f"    [TIMEOUT DEFINITIVO] {item['url']} — não entra na base.")
            elif resultado == "erro_ia":
                erros_ia += 1
            if resultado == "ok":
                time.sleep(PAUSA_API)
        fila_timeout = proxima_fila

    # Links que esgotaram todas as tentativas
    for item in fila_timeout:
        print(f"  [TIMEOUT DEFINITIVO] {item['url']} — não entra na base.")

    # Salva a base após todas as análises
    salvar_base(base)

    # ── novos_relevantes.txt ──────────────────────────────────────────────────
    with open(OUTPUT_RELEVANTES, "w", encoding="utf-8") as f:
        f.write(f"Verificação: {agora_utc}\n")
        f.write(f"Links analisados: {total_novos}\n")
        f.write(f"Links relevantes: {len(relevantes)}\n")
        f.write("=" * 60 + "\n\n")
        if relevantes:
            for item in relevantes:
                titulo = item.get("titulo_real") or item.get("title") or "(ver link)"
                f.write(f"Título:  {titulo}\n")
                f.write(f"URL:     {item.get('url', '')}\n")
                f.write(f"Motivo:  {item.get('motivo', '')}\n\n")
        else:
            f.write("Nenhum link relevante encontrado.\n")

    # ── Relatório HTML ────────────────────────────────────────────────────────
    print("\nGerando relatório HTML...")
    html = gerar_html(relevantes, data_str, total_novos)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Relatório salvo em '{OUTPUT_HTML}'.")

    # ── Resumo para WhatsApp ──────────────────────────────────────────────────
    resumo = ""
    if relevantes:
        print("\nGerando resumo para WhatsApp...")
        resumo = gerar_resumo_whatsapp(relevantes)
        print(f"  Resumo: {resumo}")

    # ── WhatsApp ──────────────────────────────────────────────────────────────
    print("\nEnviando mensagem para WhatsApp...")
    mensagem = formatar_mensagem_whatsapp(data_str, total_novos, relevantes, resumo, erros_ia)
    print(f"  Mensagem ({len(mensagem)} chars):\n{mensagem}")
    enviar_whatsapp(mensagem)

    print(f"\nRelevantes: {len(relevantes)}/{total_novos}")
    print(f"Relatório: {URL_RELATORIO}")


if __name__ == "__main__":
    main()
