# CuradorIA — Carreiras Jurídicas

Curadoria inteligente e automatizada de notícias e editais de concursos públicos voltada especificamente para bacharéis e profissionais da área jurídica no Brasil.

O sistema monitora diariamente as principais fontes de certames públicos, aplica um funil em camadas de Inteligência Artificial para eliminar falsos positivos e publica um painel interativo atualizado no GitHub Pages.

---

## 🎯 Carreiras Monitoradas

- **Tribunais:** Juiz, Analista e Técnico (TJ, TRF, TRE, TRT, STJ, STF, TSE, TST)
- **Ministério Público:** Promotor, Analista e Técnico (MPE, MPF, MPT, MPM)
- **Defensoria Pública:** Defensor, Analista e Técnico (DPE, DPU)
- **Procuradorias e Advocacia Pública:** PGM, PGE, PGFN, AGU, Procuradorias Legislativas
- **Carreiras Policiais:** Delegado de Polícia
- **Cartórios:** Outorga de Delegações de Notas e Registro
- **Residência & Estágio:** Residência Jurídica e Estágio de Pós-graduação em Direito
- **Administrativo Jurídico:** Cargos jurídicos em autarquias, prefeituras e câmaras

---

## ⚙️ Mecânica do Funil de IA (TypeSafe Jev + Google Gemini)

O sistema opera em uma arquitetura híbrida de alto desempenho e baixíssimo custo:

1. **Etapa 1: Triagem & Classificação (TypeSafe Jev - System One):**
   - Avalia rapidamente todos os novos links coletados em ~100 ms por notícia.
   - Aplica *Speculative Fan-Out* com 4 perguntas paralelas (`has_legal_vacancies`, `is_exclusive_non_legal`, `is_only_legislative_citation`, `career`, `stage`) e *Composite Decision Scoring*.
   - Aciona *Deep Probe* autônomo para resolver casos ambíguos na zona cinzenta (< 90% de certeza).
   - Descarta certames sem relação com Direito a um custo de \$0.042 / 1M tokens, sem consumir cotas de LLMs generativos.
2. **Etapa 2: Validação Analítica & Resumos (Gemini Flash Lite):**
   - Processa apenas os candidatos pré-aprovados em lotes de 2 a 3 notícias via `gemini-3.5-flash-lite` (15 RPM / 500 RPD).
   - Redige o resumo factual denso (status, vagas, remuneração, prazos) e o slug de grupo.
3. **Etapa 3: Consolidação e Harmonização (Gemini Flash Lite):**
   - Unifica as tags de grupo de notícias que tratam do mesmo certame/órgão.
4. **Resiliência e Cascata de Fallback:**
   - Jev com retentativas automáticas e backoff exponencial.
   - Alternância automática na família Lite (`gemini-3.5-flash-lite` $\rightarrow$ `gemini-3.1-flash-lite` $\rightarrow$ `gemini-flash-lite-latest` $\rightarrow$ `gemini-2.5-flash-lite`).

---

## 🚀 Como Executar

### 1. Pré-requisitos e Dependências

Requer Python 3.10+:

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. Configurar Chaves de API

Defina suas chaves de API no ambiente ou crie um arquivo `.env`:

```powershell
$env:TYPESAFE_API_KEY = "sua_chave_typesafe_aqui"
$env:AI_API_KEY = "sua_chave_do_google_gemini_aqui"
```

No GitHub Actions, configure os secrets correspondentes no repositório (`TYPESAFE_API_KEY` e `AI_API_KEY`).

### 3. Modos de Execução

- **Execução Completa (Coleta + IA + Relatório):**
  ```powershell
  python scraper.py
  ```

- **Modo Repovoamento Seguro (`--populate-only`):**
  Sincroniza a base de dados com as URLs ativas hoje **sem realizar chamadas de IA**:
  ```powershell
  python scraper.py --populate-only
  ```

### 4. Executar Testes Unitários

```powershell
python -m pytest
```

---

## 📖 Arquitetura e Detalhes Técnicos

Consulte o documento técnico [DEVGUIDE.md](DEVGUIDE.md) para detalhes sobre o fluxo de dados, ciclo de vida dos módulos e decisões críticas de engenharia.
