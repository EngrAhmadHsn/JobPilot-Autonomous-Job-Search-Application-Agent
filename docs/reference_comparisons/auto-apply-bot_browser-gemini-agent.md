# Reference Project Analysis: auto-apply-bot

## 1. Project Overview & Purpose
- **Project Name:** auto-apply-bot (`auto-apply-bot-main`)
- **Primary Purpose:** Autonomous job application bot designed for Brazilian and global portals (Gupy, Vagas.com, LinkedIn, Indeed) powered by Google Gemini and browser automation via Playwright MCP over Chrome DevTools Protocol (CDP).
- **Primary Language / Ecosystem:** TypeScript / Node.js (with Playwright MCP, SQLite, Google GenAI SDK). Original documentation is in Portuguese.
- **Original Repository / Author:** `LuisMIguelFurlanettoSousa/auto-apply-bot`.

---

## 2. Core Architecture & Workflow
1. **Agent Orchestration (`agente.ts` / `index.ts`):** Uses Google Gemini Flash (`@google/genai`) configured with MCP tools from Playwright MCP and internal custom tools (`pontuar_vaga`, `gerar_curriculo_tailored`, `gerar_cover_letter`, `buscar_resposta_cache`, `registrar_candidatura`, etc.).
2. **Session Persistence via Real Chrome CDP:** Connects to an existing Chrome browser running with `--remote-debugging-port` and a persistent user profile directory (`--user-data-dir`). This reuses human-logged sessions without exposing credentials.
3. **PII Anonymization Pipeline (`anonimizacao.ts`):** Deterministically redacts candidate sensitive data (Candidate Name, Email, Phone, LinkedIn, GitHub, Portfolio) with standard placeholders (`[CANDIDATO_NOME]`, `[CANDIDATO_EMAIL]`, etc.) before passing profiles to external LLMs, and replaces them back upon output synthesis.
4. **Factuality & Fabrication Guard (`validacao-skills.ts`):** Extracts ground truth skills from candidate profile JSON and scans generated resumes/cover letters for fabricated technical skills. If hallucinations are detected, it falls back to a curated pre-existing resume.
5. **Human-in-the-Loop Anti-Bot Handler:** Explicitly acknowledges that anti-bot challenges (Cloudflare, reCAPTCHA, Turnstile, hCaptcha) cannot and should not be bypassed autonomously. When detected, it captures a screenshot, notifies the user via Telegram bot, and halts execution until the human confirms resolution in the browser with "OK".
6. **Form Answer Cache (`database.ts`):** Sanitizes form question strings and caches answers in SQLite to save LLM tokens and ensure uniform questionnaire responses across repetitive applications.
7. **Sliding Context Window & Cost Tracking:** Implements token trimming (`podarHistorico` in `historico.ts`) to avoid Gemini token limit blowups and tracks exact cumulative token consumption and USD costs (`token-tracker.ts`).

---

## 3. Comparison with Our Project

| Feature / Dimension | Our Project (`Autonomous AI Job Application Agent`) | `auto-apply-bot` |
| :--- | :--- | :--- |
| **Language & Core Framework** | Python 3.10+, FastAPI, LangGraph workflow state machine, Pydantic data schemas | TypeScript / Node.js, imperative agentic while-loop with tool calling |
| **Browser Layer** | Controlled Playwright runtime with accessibility-tree semantics, DOM sanitization, and evidence capture (`src/browser/`) | Playwright MCP server connected to local Chrome CDP port |
| **Anti-Bot & Security** | Strict SSRF defense, prompt injection isolation, audit trails, human approval gates (`SECURITY.md`) | Telegram-based manual intervention pause on CAPTCHA detection |
| **Privacy / PII Redaction** | Candidate data treated as strictly confidential; isolated prompts | Deterministic two-way regex anonymizer (`anonimizacao.ts`) before LLM calls |
| **Verification & Evidence** | Structured DB evidence ledger (`src/db/evidence.py`), hash verification, before/after diffs | Screenshot snapshot saved locally and path stored in SQLite |
| **Matching & Tailoring** | Hybrid embedding + BM25 ranker (`EmbeddingGemma-2`), strict factuality validator | 1-10 numerical scoring prompt, HTML-to-PDF resume generation with skill diff checks |
| **Target Job Portals** | Multi-board scrapers + Greenhouse/Lever/Workday API & form submission | Gupy, Vagas.com, LinkedIn Easy Apply, Indeed |

---

## 4. Valuable Ideas & Concepts to Adopt in Our Project
1. **Pre-LLM Two-Way PII Anonymization Engine:**
   - *Idea:* `anonimizacao.ts` replaces personal candidate identifiers (Name, Email, Phone, Address, Social URLs) with deterministic tokens prior to sending prompts to cloud models (e.g. Gemini, OpenAI, Claude), then re-injects real credentials locally during form filling or final PDF compilation.
   - *Our Implementation Opportunity:* Enhance `src/security/sanitizer.py` or `src/tailoring/` to include a reversible PII redaction layer. This satisfies enterprise privacy standards and prevents LLM providers from storing sensitive candidate identity data.
2. **Telegram Bot Emergency Pause & Remote CAPTCHA Relay:**
   - *Idea:* When the browser automation hits Cloudflare Turnstile, hCaptcha, or MFA, the bot takes a viewport screenshot, sends it via Telegram with an interactive inline button, and enters an async wait state until the user solves it in the attached browser.
   - *Our Implementation Opportunity:* Integrate into WS-08 (Browser Automation) and WS-13 (Frontend/Operator Console) an alert webhook (Telegram / Slack / WebSocket push to React UI) allowing the user to unblock challenges remotely.
3. **Form Question-Answer Cache (`buscarRespostaCache`):**
   - *Idea:* Persisting sanitized question stems (e.g., "years of experience in Python", "willing to relocate", "authorized to work") and user-approved answers in SQLite prevents redundant LLM evaluations on standard application questions.
   - *Our Implementation Opportunity:* Extend `src/db/` with an `application_qa_cache` table to speed up browser autofill runs and keep answers deterministic.
4. **Token Usage & USD Cost Ledger:**
   - *Idea:* `token-tracker.ts` aggregates prompt and completion tokens per run and computes monetary burn rates.
   - *Our Implementation Opportunity:* Add model token tracking into our LangGraph pipeline metadata, recording exact inference costs per candidate run in our telemetry.

---

## 5. Potential Pitfalls / Anti-Patterns to Avoid
- **Unbounded Agentic Loops:** `auto-apply-bot` relies on an open-ended loop (`while (iteracao < MAX_ITERACOES)`) asking the LLM for next tool calls. In real-world job forms, dynamic SPAs can trap the agent in circular clicks. Our LangGraph state-graph architecture with explicit state checkpoints is much more deterministic and resilient.
- **MCP for Production Runtime:** Using Playwright MCP as the runtime execution engine introduces an unnecessary process boundary and protocol overhead. As specified in our architectural guidelines, Playwright MCP is great for development-time inspection, but runtime automation must be directly managed via native Playwright Python code.
