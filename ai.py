import json
import re
import time
import unicodedata
import os
import requests

# Configurações da API da IA
AI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
AI_MODEL = "gpt-4o-mini"
AI_URL = "https://api.openai.com/v1/chat/completions"

# Instruções de comportamento da IA
PROMPT_RELEVANCE = """Sua tarefa é avaliar se o conteúdo abaixo é um artigo de atualização, previsão, ou divulgação, de edital, concurso, processo seletivo, certame, e similares, que sejam relevantes para um bacharel em Direito que estuda para concursos públicos nas seguintes áreas:

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
- Páginas que sejam apenas listagens de provas para download, índices de banca, ou agregadores de outros concursos sem foco em um certame específico

Se for relevante, identifique também:

1. STATUS do certame, escolhendo UMA das opções:
   - "announced" → autorização publicada, comissão formada, banca contratada, edital previsto mas ainda não publicado
   - "registration_open" → edital publicado e inscrições em andamento
   - "registration_closed" → inscrições já fecharam, aguardando prova
   - "exam_taken" → prova aplicada, aguardando gabarito ou resultado preliminar
   - "result" → gabarito divulgado, resultado preliminar, recursos, resultado final
   - "closed" → certame finalizado, convocações, posses, prorrogação de validade

2. GROUP no formato "orgao-localidade-cargo" usando apenas letras minúsculas, números e hífens, SEM acentos. Exemplos:
   - "cgm-porto-velho-ro-auditor"
   - "prefeitura-martinopolis-sp-advogado"
   - "sefaz-ce-auditor-fiscal"
   - "pgm-caxias-do-sul-rs-procurador"
   - "al-ms-analista-juridico"
   - "tjto-residencia-juridica"
   Use o mesmo identificador para notícias que tratem do mesmo concurso, mesmo que escritas de formas diferentes. Se houver dúvida sobre o cargo específico, omita a parte do cargo.

REGRAS PARA O CAMPO "reason":
- Descreva o cargo e o contexto específico do certame
- Nunca use frases como "relevante para bacharéis em Direito", "exige formação em Direito" ou similares
- Essas conclusões são óbvias; o motivo deve agregar informação nova, não reafirmar o óbvio

Responda APENAS no seguinte formato JSON, sem nenhum texto adicional:
{"relevant": true, "reason": "cargo e contexto específico do certame", "status": "registration_open", "group": "orgao-localidade-cargo"}
ou
{"relevant": false, "reason": "explicação em uma linha"}

Conteúdo para avaliar:
"""

# Mapeia os valores de status retornados pela IA para rótulos visuais no relatório HTML
STATUS_LABELS = {
    "announced": ("📢 Anunciado", "#6c757d"),
    "registration_open": ("✅ Inscrição aberta", "#28a745"),
    "registration_closed": ("⏰ Inscrição encerrada", "#fd7e14"),
    "exam_taken": ("📝 Prova realizada", "#17a2b8"),
    "result": ("🏁 Resultado", "#6f42c1"),
    "closed": ("🔒 Encerrado", "#495057"),
}

def normalize_group(g: str) -> str:
    """Normaliza o nome do grupo gerado por IA (remove acentos e espaços)"""
    if not g:
        return ""
    g = unicodedata.normalize("NFKD", g).encode("ascii", "ignore").decode("ascii")
    g = g.lower().strip()
    g = re.sub(r"[^a-z0-9-]", "-", g)
    g = re.sub(r"-+", "-", g).strip("-")
    return g

def call_ai_api(prompt: str) -> str:
    """Faz a chamada HTTP para a API da OpenAI com lógica de repetição"""
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 400,
    }
    for attempt in range(3):
        try:
            resp = requests.post(
                AI_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {AI_API_KEY}",
                },
                json=payload,
                timeout=45,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"    [ERRO OpenAI tentativa {attempt+1}/3] → {e}")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
    return ""

def evaluate_relevance(url: str, title: str, text: str) -> dict:
    """Envia o conteúdo da página para a IA e retorna uma avaliação estruturada"""
    if not AI_API_KEY:
        return {"relevant": False, "reason": "AI_API_KEY not configured"}
    if not text or len(text) < 50:
        return {"relevant": False, "reason": "insufficient text"}

    content = f"URL: {url}\nTítulo: {title}\n\nTexto:\n{text}"
    response = call_ai_api(PROMPT_RELEVANCE + content)

    if not response:
        return {"relevant": False, "reason": "error after 3 attempts"}

    try:
        response = re.sub(r"```json|```", "", response).strip()
        evaluation = json.loads(response)

        if evaluation.get("relevant"):
            evaluation["group"] = normalize_group(evaluation.get("group", ""))
            status = (evaluation.get("status") or "").strip().lower()
            evaluation["status"] = status if status in STATUS_LABELS else ""

        return evaluation
    except Exception:
        return {"relevant": False, "reason": "error parsing response"}
