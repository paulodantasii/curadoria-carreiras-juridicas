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

## ⚙️ Mecânica do Funil de IA (Google Gemini)

O sistema utiliza a API do **Google Gemini** em uma arquitetura de funil de 3 etapas otimizada para cotas e precisão:

1. **Etapa 1: Triagem Ampla (Gemini Flash Lite):**
   - Avalia rapidamente todos os novos links coletados.
   - Configurado com alta sensibilidade para não perder nenhum edital potencial (`fail-open`).
   - Desmarca e descarta certames 100% não jurídicos (saúde, educação, etc.) consumindo zero cotas dos modelos analíticos.
2. **Etapa 2: Validação & Extração em Lotes (Gemini Flash + Extended Thinking):**
   - Processa os candidatos em lotes de 2 a 3 notícias.
   - Utiliza raciocínio analítico profundo para eliminar falsos positivos.
   - Extrai resumo factual denso (status, vagas, remuneração, prazos), categoriza carreira e slug de grupo.
3. **Etapa 3: Consolidação e Harmonização (Gemini Flash):**
   - Unifica as tags de grupo de itens que tratam do mesmo certame.
4. **Resiliência e Cascata de Fallback:**
   - Alternância automática entre modelos da família Flash (`gemini-3.8-flash`, `gemini-3.7-flash`, etc.) caso limites de cota (HTTP 429) sejam atingidos, com fallback de emergência para Flash Lite.

---

## 🚀 Como Executar

### 1. Pré-requisitos e Dependências

Requer Python 3.10+:

```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. Configurar Chave de API

Defina sua chave da API Google Gemini no ambiente:

```powershell
$env:AI_API_KEY = "sua_chave_do_google_aqui"
```

No GitHub Actions, configure o secret do repositório com o nome `AI_API_KEY`.

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
