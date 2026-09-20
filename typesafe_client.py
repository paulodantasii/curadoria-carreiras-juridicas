"""Cliente TypeSafe AI (System One / Jev) / TypeSafe AI Client (System One / Jev)

Fornece interface para o modelo Jev da TypeSafe AI:
- Triagem com Speculative Fan-Out (4 perguntas simultâneas em ~100ms)
- Cálculo determinístico de Composite Score em código
- Deep Probe cirúrgico para desempate autônomo na zona de incerteza (< 90% de certeza)
- Resiliência a rate limits (429/529) com backoff exponencial
"""
import json
import logging
import re
import time
from typing import Any, Optional

import requests

from config import (
    TYPESAFE_API_KEY,
    TYPESAFE_API_URL,
    TYPESAFE_CERTAINTY_THRESHOLD,
    TYPESAFE_DISCARD_THRESHOLD,
    TYPESAFE_MODEL,
    TYPESAFE_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Palavras-chave para isolamento cirúrgico de trechos em caso de incerteza
_LEGAL_KEYWORDS_RE = re.compile(
    r"\b(direito|oab|advogad\w*|procurad\w*|juiz\w*|magistrad\w*|promotor\w*|defensor\w*|"
    r"judici[aá]ri\w*|jur[ií]dic\w*|cart[oó]ri\w*|tabeli\w*|not[aá]ri\w*|resid[eê]ncia juridica|"
    r"delegad\w*|analista judici[aá]rio|oficial de justi[çc]a|assessor jur[ií]dico|consultor jur[ií]dico)\b",
    re.IGNORECASE,
)


class TypeSafeClient:
    """Cliente HTTP para a API TypeSafe AI System One (Jev)"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = TYPESAFE_TIMEOUT,
    ) -> None:
        self.api_key: str = TYPESAFE_API_KEY if api_key is None else api_key
        self.api_url: str = TYPESAFE_API_URL if api_url is None else api_url
        self.model: str = TYPESAFE_MODEL if model is None else model
        self.timeout: float = timeout

    def call_system_one(
        self,
        state: Any,
        questions: dict[str, Any],
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Executa uma chamada ao endpoint POST /v1/systemone com retentativas defensivas"""
        if not self.api_key:
            raise ValueError("TYPESAFE_API_KEY não configurada no ambiente ou .env")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "state": state,
            "questions": questions,
        }

        attempt = 0
        backoff_delay = 1.0

        while attempt <= max_retries:
            try:
                resp = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code in (429, 529):
                    retry_after = resp.headers.get("Retry-After")
                    sleep_time = float(retry_after) if retry_after else backoff_delay
                    logger.warning(
                        "TypeSafe Jev rate limit/overload (HTTP %d). Aguardando %.2fs (tentativa %d/%d)",
                        resp.status_code,
                        sleep_time,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(sleep_time)
                    attempt += 1
                    backoff_delay *= 2.0
                    continue

                logger.error(
                    "Erro na API TypeSafe Jev (HTTP %d): %s",
                    resp.status_code,
                    resp.text,
                )
                resp.raise_for_status()

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                attempt += 1
                if attempt > max_retries:
                    logger.error("Falha de conexão com TypeSafe Jev após %d tentativas: %s", max_retries, e)
                    raise
                logger.warning(
                    "Falha temporária de rede com TypeSafe Jev (%s). Tentando novamente em %.2fs",
                    e,
                    backoff_delay,
                )
                time.sleep(backoff_delay)
                backoff_delay *= 2.0

        raise RuntimeError(f"TypeSafe Jev falhou após {max_retries} tentativas")

    def _extract_legal_snippet(self, text: str, max_chars: int = 1500) -> str:
        """Extrai seletivamente parágrafos com termos jurídicos para eliminar context rot no desempate"""
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        relevant_parts: list[str] = []
        total_len = 0

        for p in paragraphs:
            if _LEGAL_KEYWORDS_RE.search(p):
                relevant_parts.append(p)
                total_len += len(p)
                if total_len >= max_chars:
                    break

        if relevant_parts:
            return " ".join(relevant_parts)[:max_chars]
        return text[:max_chars]

    def _build_primary_questions(self) -> dict[str, Any]:
        """Monta o lote de 4 perguntas paralelas do Speculative Fan-Out primário"""
        return {
            "has_legal_vacancies": {
                "type": "noul",
                "instructions": (
                    "Existe nesta notícia menção a vagas, cargos ou oportunidades específicas "
                    "para a área jurídica ou formação em Direito (ex: Juiz, Promotor, Defensor, "
                    "Procurador, Advogado, Analista/Técnico Judiciário, Cartórios, Residência Jurídica)?"
                ),
                "criteria": {
                    "true": "Há cargos ou vagas para a área jurídica ou graduados em Direito (mesmo em concurso misto)",
                    "false": "Não há nenhum cargo ou vaga para Direito",
                },
            },
            "is_exclusive_non_legal": {
                "type": "noul",
                "instructions": (
                    "O certame é EXCLUSIVAMENTE para áreas sem relação com Direito "
                    "(ex: apenas saúde, educação/professores, operacionais, limpeza, obras, trânsito)?"
                ),
                "criteria": {
                    "true": "Todas as vagas são exclusivamente para áreas não-jurídicas, sem nenhuma vaga jurídica",
                    "false": "Há vagas jurídicas ou o certame não é restrito a outras áreas",
                },
            },
            "is_only_legislative_citation": {
                "type": "noul",
                "instructions": (
                    "O texto apenas cita leis, estatutos, decretos ou termos jurídicos genéricos "
                    "sem ofertar vagas para cargos da área de Direito?"
                ),
                "criteria": {
                    "true": "Apenas cita legislação como fundamentação legal, sem ofertar cargos para Direito",
                    "false": "Oferta vagas ou oportunidades reais para a área jurídica",
                },
            },
            "career": {
                "type": "choice",
                "instructions": "Qual carreira jurídica melhor descreve as vagas ou oportunidade do certame?",
                "criteria": {
                    "tribunais": "Juiz, Analista ou Técnico de Tribunais de Justiça (TJ, TRF, TRT, TRE, STJ, STF)",
                    "mp": "Promotor de Justiça ou servidores do Ministério Público (MPE, MPF, MPT)",
                    "defensoria": "Defensor Público ou servidores da Defensoria Pública (DPE, DPU)",
                    "procuradorias": "Procurador (Bacen, AGU, PGM, PGE, PGFN) ou Advogado Público de estatais",
                    "policiais": "Delegado de Polícia ou carreiras policiais estritamente jurídicas",
                    "cartorios": "Notários e Registradores (Delegações de Notas e Registro)",
                    "administrativo": "Assessor Jurídico, Consultor Jurídico ou Advogado em Prefeituras, Câmaras, Conselhos",
                    "estagio": "Residência Jurídica ou Estágio de Pós-graduação em Direito",
                    "none": "Não há carreira jurídica ou certame irrelevante para Direito",
                },
            },
            "stage": {
                "type": "choice",
                "instructions": "Em qual estágio/fase se encontra o concurso ou processo seletivo?",
                "criteria": {
                    "edital_publicado": "Edital publicado ou inscrições abertas",
                    "banca_definida": "Banca organizadora contratada ou escolhida",
                    "comissao_ou_autorizacao": "Comissão formada, certame autorizado ou estudos iniciados",
                    "retificacao_ou_resultado": "Retificação de edital, homologação de resultados ou convocação",
                    "indeterminado": "Estágio não informado ou notícia geral",
                },
            },
        }

    def _deep_probe_uncertainty(
        self,
        title: str,
        text: str,
        initial_career: str,
    ) -> tuple[bool, str]:
        """Deep Probe de segundo nível para resolver ambiguidades exclusivamente com o Jev"""
        snippet = self._extract_legal_snippet(text)
        state = {
            "title": title,
            "focused_excerpt": snippet,
        }

        probe_questions = {
            "requires_law_degree_explicitly": {
                "type": "noul",
                "instructions": (
                    "O trecho `focused_excerpt` comprova a existência de vagas ou cargos privativos "
                    "para quem tem formação em Direito (exige Bacharelado em Direito, OAB ou Residência Jurídica)?"
                ),
                "criteria": {
                    "true": "Sim, há requisito expresso ou cargo privativo da área de Direito",
                    "false": "Não há menção a exigência de formação jurídica",
                },
            },
            "is_purely_non_legal": {
                "type": "noul",
                "instructions": (
                    "O trecho `focused_excerpt` refere-se exclusivamente a cargos não-jurídicos "
                    "(ex: médicos, enfermagem, professores, engenheiros, técnicos operacionais)?"
                ),
                "criteria": {
                    "true": "Refere-se unicamente a cargos sem relação com Direito",
                    "false": "Contém cargo ou requisito jurídico",
                },
            },
        }

        try:
            res = self.call_system_one(state, probe_questions)
            answers = res.get("answers", {})

            law_req = answers.get("requires_law_degree_explicitly", {}).get("noul", 0.0)
            non_legal = answers.get("is_purely_non_legal", {}).get("noul", 0.0)

            logger.info(
                "TypeSafe Deep Probe -> law_req: %.2f, non_legal: %.2f para '%s'",
                law_req,
                non_legal,
                title[:60],
            )

            if law_req >= 0.50:
                career = initial_career if initial_career != "none" else "administrativo"
                return True, career

            if non_legal >= 0.80 and law_req < 0.20:
                return False, "none"

            # Se ainda houver leve sinal jurídico, fail-open mantendo como relevante
            if law_req >= 0.35 and non_legal < 0.65:
                career = initial_career if initial_career != "none" else "administrativo"
                return True, career

            return False, "none"

        except Exception as e:
            logger.error("Erro no Deep Probe do Jev para '%s': %s", title[:60], e)
            # Fail-open para garantir recall em caso de exceção no desempate
            return True, initial_career if initial_career != "none" else "administrativo"

    def triage(self, title: str, text: str) -> dict[str, Any]:
        """Executa a triagem completa e autônoma de um item usando o Jev (System One)

        Retorna dicionário no formato:
        {
            "relevant": bool,
            "career": str,
            "stage": str,
            "score": float,
            "confidence": float,
            "deep_probed": bool
        }
        """
        clean_text = text[:3500].strip()
        state = {
            "title": title.strip(),
            "text": clean_text,
        }

        questions = self._build_primary_questions()
        res = self.call_system_one(state, questions)
        answers = res.get("answers", {})

        p_vacancies = answers.get("has_legal_vacancies", {}).get("noul", 0.0)
        p_non_legal = answers.get("is_exclusive_non_legal", {}).get("noul", 0.0)
        p_citation = answers.get("is_only_legislative_citation", {}).get("noul", 0.0)

        career_ans = answers.get("career", {})
        career = career_ans.get("choice", "none")
        career_conf = career_ans.get("confidence", 0.0)

        stage_ans = answers.get("stage", {})
        stage = stage_ans.get("choice", "indeterminado")

        # Composite Decision Score
        composite_score = p_vacancies * (1.0 - p_non_legal) * (1.0 - p_citation)

        logger.debug(
            "Jev Triage '%s': score=%.3f, p_vac=%.2f, p_non=%.2f, p_cit=%.2f, career=%s(%.2f)",
            title[:50],
            composite_score,
            p_vacancies,
            p_non_legal,
            p_citation,
            career,
            career_conf,
        )

        # 1. Aprovação Direta com Alta Certeza (>= 90%)
        if (
            composite_score >= 0.80
            and career != "none"
            and (career_conf >= TYPESAFE_CERTAINTY_THRESHOLD or p_vacancies >= TYPESAFE_CERTAINTY_THRESHOLD)
        ):
            return {
                "relevant": True,
                "career": career,
                "stage": stage,
                "score": composite_score,
                "confidence": career_conf,
                "deep_probed": False,
            }

        # 2. Descarte Direto com Alta Certeza (<= 15%)
        if (
            composite_score <= TYPESAFE_DISCARD_THRESHOLD
            or (career == "none" and career_conf >= TYPESAFE_CERTAINTY_THRESHOLD and p_vacancies <= 0.20)
        ):
            return {
                "relevant": False,
                "career": "none",
                "stage": stage,
                "score": composite_score,
                "confidence": career_conf,
                "deep_probed": False,
            }

        # 3. Zona de Incerteza (Certeza < 90%): Deep Probe Focado
        logger.info(
            "Zona de Incerteza para '%s' (score=%.2f, conf=%.2f). Disparando Deep Probe no Jev...",
            title[:60],
            composite_score,
            career_conf,
        )

        is_relevant, final_career = self._deep_probe_uncertainty(title, text, career)

        return {
            "relevant": is_relevant,
            "career": final_career if is_relevant else "none",
            "stage": stage,
            "score": composite_score,
            "confidence": career_conf,
            "deep_probed": True,
        }
