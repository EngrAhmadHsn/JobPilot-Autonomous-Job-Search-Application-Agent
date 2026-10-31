# Reference Project Analysis: JobHunter AI

## 1. Project Overview & Purpose
- **Project Name:** JobHunter AI (`jobhunter-ai-main`)
- **Primary Purpose:** 24/7 full-stack autonomous job hunting intelligence suite: multi-platform crawler (BOSS Zhipin, 51job, Liepin, Zhilian), two-tier data cleaning engine, LangGraph state-machine evaluation and resume tailoring, automated browser application, multi-platform online resume backfill, and Feishu/Lark ChatOps collaboration.
- **Primary Language / Ecosystem:** Python 3.10–3.13 (FastAPI, LangGraph, DrissionPage / Playwright CDP, SQLite, APScheduler, managed via `uv`) + Next.js 15 (Tailwind CSS v4, shadcn/ui, Zustand, Vitest). Original documentation in Chinese.
- **Original Repository / Author:** `jolie-z/jobhunter-ai`.

---

## 2. Core Architecture & Workflow
1. **LangGraph State-Machine Core Pipeline:**
   - Evaluates jobs via a 5-node state-machine cycle (`evaluate` -> `rewrite` / `greeting` -> `approval` -> `apply`).
   - Quantified scoring: 8 dimensions, 40-point rubric assessing JD alignment, tech-stack overlap, company risk, and recruiter activity.
   - Tiered strategy: Deep STAR-format resume tailoring for A/B-grade matches; fast-track greeting outreach for C/D-grade listings.
2. **Multi-Platform Scraper & CDP Execution Guard (`engine_guard.py`):**
   - Connects to dedicated persistent Chromium profiles across Chinese recruitment giants (BOSS Zhipin, Liepin, 51job, Zhilian).
   - **`engine_guard.py` (Fail-Closed CDP Port Protection):** A crucial security innovation preventing automation accidents. Before attaching to a CDP remote debugging port, it verifies the PID and profile owner. If an unexpected browser (such as the developer's personal browser) is listening on that port, it fails closed to prevent the bot from commandeering personal sessions.
3. **Two-Tier Cleaning Pipeline (`job_processor/`):**
   - **Tier 1 (Deterministic Structural Filter):** Zero-token regex/rule filtering eliminating headhunter outsourcing, sales disguised as tech roles, commission-only jobs, and expired listings.
   - **Tier 2 (AI Scout Evaluation):** Deep semantic evaluation detecting hidden toxic work conditions and company red flags.
4. **Anti-Hallucination & Anti-AI Jargon Resume Rewriter (`resume_rewrite.md`):**
   - Explicit "Headhunter-Grade Red Lines": Strict blacklist banning corporate/AI fluff ("empower", "closed-loop", "synergy", "paradigm shift").
   - Rigid anti-fabrication boundary (`01_truth.md`): Forbids inventing skills or metrics not present in the candidate profile.
5. **Feishu / Lark ChatOps & Bi-directional Bitable Sync:**
   - Real-time bi-directional database synchronization with Feishu multi-dimensional tables (Bitable).
   - ChatOps bot accepting conversational commands via WebSocket (search, evaluate, trigger apply, query status) with live Server-Sent Event (SSE) progress streams.
6. **Online Resume Backfill Engine (`resume_editor/`):**
   - Directly injects and synchronizes candidate profile fields (work experience, education, projects) back into the native online web resume forms of recruitment portals via DOM mutation.

---

## 3. Comparison with Our Project

| Feature / Dimension | Our Project (`Autonomous AI Job Application Agent`) | `JobHunter AI` |
| :--- | :--- | :--- |
| **Language & Architecture** | Python 3.10+, FastAPI backend, LangGraph state machine, separate React operator console (`/frontend` via WS-13) | Python 3.10–3.13, FastAPI backend, LangGraph state machine, Next.js 15 frontend, Feishu ChatOps |
| **Automation & Anti-Bot** | Server-side Playwright with strict accessibility-tree semantics, DOM sanitization, SSRF protection | Hybrid Playwright + DrissionPage via CDP with strict port verification guard (`engine_guard.py`) |
| **Target Job Portals** | US/Global tech ecosystem: Greenhouse, Lever, Workday, LinkedIn, Indeed, JobSpy boards | Chinese tech ecosystem: BOSS Zhipin, 51job, Liepin, Zhilian Zhaopin |
| **Matching & Embedding** | Local `EmbeddingGemma-2` via ONNX/fastembed (max 8,000 chars) + BM25 hybrid ranking | LLM-driven 8-dimension 40-point rubric + multi-tier rule filters |
| **Safety & Human Approval** | Mandatory human approval gate before submission; cryptographically auditable evidence ledger | Human approval gate for A/B tier submissions; mass apply option for C tier |

---

## 4. Valuable Ideas & Concepts to Adopt in Our Project
1. **Engine CDP Port Guard (`engine_guard.py` - Fail-Closed Attaching):**
   - *Idea:* When running browser automation via `--remote-debugging-port`, if another process or a user's personal browser is already running on port 9222, attaching blindly can hijack the user's personal session or send automated actions from an unintended identity. `engine_guard.py` checks PID and profile ownership, failing closed immediately if the port identity does not match the configured test runner.
   - *Our Implementation Opportunity:* Adopt this exact safety guard in `src/browser/` before launching or connecting to Chromium instances.
2. **Explicit "Anti-AI Jargon" Prompt Rules for Resume Tailoring:**
   - *Idea:* `resume_rewrite.md` enforces a strict negative keyword list against boilerplate AI corporate buzzwords ("empower", "leverage", "paradigm", "seamlessly orchestrate") and mandates high-frequency action verbs ("spearheaded", "refactored", "debugged", "scaled from X to Y").
   - *Our Implementation Opportunity:* Update WS-05 (`docs/implementation/05-tailoring-and-research.md`) tailoring prompts to include this anti-jargon filter, making generated resumes sound authentically human and senior.
3. **Two-Tier Cleaning Pipeline (Physical Rules -> AI Scout):**
   - *Idea:* Running full LLM evaluation on thousands of raw scraped jobs wastes money and time. Tier 1 eliminates 70% of irrelevant postings instantly using zero-cost regex filters (outsourcing agencies, contract roles, salary below threshold, missing tech keywords). Tier 2 evaluates only qualified candidates.
   - *Our Implementation Opportunity:* Formalize this in `src/matching/filter.py` prior to the embedding and LLM scoring stages to optimize throughput and keep token costs minimal.
4. **ChatOps Push Notifications & Approval Cards:**
   - *Idea:* Using Lark/Slack/Telegram interactive message cards to alert the candidate: *"Found strong match: Senior Backend Engineer at Acme Corp (Score: 36/40). Click [Approve] to submit or [View Diff]"*.
   - *Our Implementation Opportunity:* In WS-13 / WS-04, expose webhook endpoints allowing interactive approval via mobile messaging apps in addition to the web console.

---

## 5. Potential Pitfalls / Anti-Patterns to Avoid
- **Mass Apply Mode (海投):** JobHunter includes an unreviewed batch delivery mode (`mass_apply`) for lower-tier listings. Submitting unreviewed applications at scale violates our core project guidelines (`docs/SECURITY.md`), triggers ATS rate limits, and damages the candidate's professional reputation.
- **DrissionPage Dependency:** DrissionPage relies on undocumented Chromium DevTools Protocol quirks that can be fragile across OS environments and browser updates. Playwright's standardized accessibility selectors and official cross-browser drivers remain the superior, maintainable choice.
