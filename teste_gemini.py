import requests
import json
import os

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

PROMPT_RELEVANCIA = """Sua tarefa é avaliar se o conteúdo abaixo é uma divulgação de edital, concurso, processo seletivo, certame, e similares, que sejam relevantes para um bacharel em Direito que estuda para concursos públicos nas seguintes áreas:
RELEVANTE — incluir sempre que o conteúdo tiver:
- Procurador ou Advogado em qualquer órgão do executivo ou legislativo: AGU, PGFN, PGF, PGE, PGM, câmaras municipais, assembleias legislativas, TCU, TCE, TCM, agências reguladoras federais como ANATEL, ANEEL, ANVISA, ANAC, ANS, ANA, ANTAQ, ANTT, ANP, CADE, Banco Central, conselhos profissionais como OAB, CRM, CREA, CFM, etc
- Procurador ou Advogado da Caixa Econômica Federal, Banco do Brasil, Petrobras, BNDES, Correios, EBSERH, Embrapa, Serpro, DATAPREV, autarquias e fundações federais, estaduais e municipais, etc
- Analista ou Assessor de matéria jurídica ou correlatas em órgãos do executivo federal, estadual ou municipal, secretarias, ministérios, autarquias, agências reguladoras, empresas públicas, etc
- Analista ou Assessor de matéria jurídica ou correlatas de Tribunal de Contas como TCU, TCE, TCM, etc
- Cargos que exijam bacharelado em Direito e cujo conteúdo programático envolva direito público, administrativo, constitucional, tributário, civil, financeiro, licitações, contratos públicos, execução fiscal
- Residência Jurídica em qualquer órgão público
- Estágio de pós-graduação em Direito em qualquer órgão público
- Programas de formação jurídica remunerada em órgãos públicos
- Todos os cargos que, por algum dos motivos acima, pareçam relevantes mas não estejam incluído nessa lista
NÃO RELEVANTE — excluir se o conteúdo for apenas:
- Cargos que não exijam formação em Direito (professores de ensino básico, médicos, engenheiros, enfermeiros, técnicos de outras áreas, etc)
- Cargos de nível médio ou técnico sem relevância jurídica
Responda APENAS no seguinte formato JSON, sem nenhum texto adicional:
{"relevante": true, "motivo": "explicação em uma linha"}
ou
{"relevante": false, "motivo": "explicação em uma linha"}
Conteúdo para avaliar:
"""

textos = [
    {
        "url": "https://www.pciconcursos.com.br/noticias/funpresp-jud-df-abre-concurso-publico-com-salarios-de-ate-11-4-mil",
        "texto": "Funpresp-Jud - DF abre concurso público com salários de até R$ 11,4 mil. A Fundação de Previdência Complementar do Servidor Público Federal do Poder Judiciário (Funpresp-Jud) abriu um concurso público para preencher vagas e formar cadastro de reserva em empregos de nível superior. Segundo o edital, as oportunidades são para os cargos de: Advogado (1 vaga), Analista - Especialidade: Administração, Governança e Planejamento (1 vaga), Analista - Especialidade: Auditoria e Controle Interno, Analista - Especialidade: Contabilidade, Analista - Especialidade: Seguridade (1 vaga)."
    },
    {
        "url": "https://cj.estrategia.com/portal/concurso-advogado-tres-barras-sc/",
        "texto": "Concurso Advogado Três Barras SC: inscrições abertas! R$ 7,9 mil e 20h semanais! A Prefeitura de Três Barras, em Santa Catarina, está em andamento com o edital de concurso público para o cargo de Advogado. A Fundação FAFIPA organiza o certame, que oferece 1 vaga imediata. O cargo prevê remuneração inicial de R$ 7.915,03 e carga horária de 20 horas semanais. Os interessados podem se inscrever até 13 de maio."
    },
]

for item in textos:
    print(f"\n=== {item['url']} ===")
    conteudo = f"URL: {item['url']}\n\nTexto:\n{item['texto']}"
    payload = {
        "contents": [{"parts": [{"text": PROMPT_RELEVANCIA + conteudo}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 200},
    }
    try:
        resp = requests.post(
            GEMINI_URL,
            headers={"Content-Type": "application/json"},
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=30,
        )
        print(f"Status API: {resp.status_code}")
        data = resp.json()
        print("Resposta bruta:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        texto_resposta = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"\nTexto da resposta: {texto_resposta}")
    except Exception as e:
        print(f"ERRO: {e}")
        print(f"Resposta raw: {resp.text[:500] if 'resp' in dir() else 'sem resposta'}")
