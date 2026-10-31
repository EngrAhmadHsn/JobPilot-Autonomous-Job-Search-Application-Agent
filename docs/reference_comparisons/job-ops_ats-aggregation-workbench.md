# Reference Project Analysis: JobOps

## 1. Project Overview & Purpose
- **Project Name:** JobOps (`job-ops`)
- **Primary Purpose:** All-in-one job search aggregation, ATS direct ingestion, CV tailoring, visa sponsorship cross-referencing, and application pipeline tracking workbench. Explicitly adopts an "Ironman Suit" philosophy: *empowers the user to apply 10x faster with high quality rather than spamming automated low-quality submissions*.
- **Primary Language / Ecosystem:** TypeScript (Node.js/React/Vite/Tailwind CSS/Fastify) monorepo managed with Biome and Docker, with auxiliary Python JobSpy wrappers.
- **Original Repository / Author:** `DaKheera47/job-ops`.

---

## 2. Core Architecture & Workflow
1. **Multi-Board Aggregation & Extractor Pipeline (`extractors/`):**
   - Integrates 15+ specialized board scrapers and extractors: Adzuna, HiringCafe, WorkingNomads, StartupJobs, JobIndex, Naukri, Seek, Wazzuf, FreeHire, FiveAmSat, and Python-based `JobSpy` (LinkedIn, Indeed, Glassdoor).
   - Normalizes raw postings into standard job listings with unified title, company, location, salary, and requirements fields.
2. **Direct Career-Board ATS Parsers (`career-boards/`):**
   - First-class API integrations for major enterprise ATS platforms: **Greenhouse**, **Lever**, and **Workday**.
   - Directly probes structured JSON endpoints (`boards-api.greenhouse.io`, Workday CXS endpoints) to retrieve canonical, un-scraped job requisitions with exact application question metadata.
3. **Official Government Visa Sponsorship Cross-Referencing (`visa-sponsor-providers/`):**
   - Automatically cross-checks hiring companies against official government visa sponsorship registers:
     - **US:** Ingests the official USCIS H-1B Employer Data Hub yearly exports (`h1b_datahubexport-[year].csv`) with approval/denial counts.
     - **UK:** Ingests the official UK Home Office Register of Worker and Temporary Worker licensed sponsors.
     - **Canada (CA) & Netherlands (NL):** Ingests official national sponsor registries.
   - Flags jobs with verified visa sponsorship credentials right in the listing card.
4. **Interactive Operator UI (`orchestrator/`):**
   - React + Vite + Tailwind CSS dashboard providing unified search across all extractors, instant CV rewriting, match scoring breakdown, and kanban-style application pipeline tracking (Saved, Applied, Interview, Offer, Rejected).

---

## 3. Comparison with Our Project

| Feature / Dimension | Our Project (`Autonomous AI Job Application Agent`) | `JobOps` |
| :--- | :--- | :--- |
| **Philosophy & Core Goal** | Autonomous end-to-end agent: discovery -> matching -> tailoring -> verification -> controlled browser application | Aggregation, tailoring, and tracking workbench: intentionally delegates final submission click to the human |
| **Backend & Pipeline** | Python 3.10+, FastAPI, LangGraph state machine, ChromaDB vector store | TypeScript monorepo, Fastify / Vite client, SQLite |
| **ATS Direct Ingestion** | Primary scraper modules in `src/jobs/` with HTTP fallback before browser | Dedicated `career-boards/` ATS API clients (Greenhouse, BambooHR, Workday) |
| **Visa Sponsorship Verification** | Candidate preference filters in profile | Deep automated ETL against official USCIS (US) and Home Office (UK) sponsor databases |
| **CV Tailoring Engine** | Factuality validator preventing skill hallucination + LaTeX/Typst compilation | Interactive LLM prompts with Typst template themes (`generate-typst-themes.mjs`) |

---

## 4. Valuable Ideas & Concepts to Adopt in Our Project
1. **Official Government Visa Sponsorship Database Verification:**
   - *Idea:* Instead of relying on unreliable LLM guesswork on whether an employer sponsors visas, `visa-sponsor-providers/` ingests the public USCIS H-1B Data Hub and UK Home Office CSVs. It matches company names against active licensed sponsors.
   - *Our Implementation Opportunity:* Create a lightweight lookup utility in `src/matching/visa_sponsors.py`. For candidates who require H-1B or UK Skilled Worker visas, candidate scoring can instantly elevate verified sponsor companies and demote/filter unverified ones.
2. **Direct ATS API Clients (`career-boards/`):**
   - *Idea:* Scraping front-facing HTML job boards is brittle. When a job URL points to Greenhouse (`boards.greenhouse.io/<company>/jobs/<id>`) or BambooHR, JobOps bypasses HTML scraping and calls the public JSON endpoint to retrieve clean JD text and form questions.
   - *Our Implementation Opportunity:* Implement direct ATS JSON resolvers in `src/jobs/` as the primary ingestion tier before resorting to Playwright HTML extraction. This is 100x faster, zero-token cost, and immune to UI changes.
3. **Typst Engine for Professional Resume PDF Generation:**
   - *Idea:* JobOps uses **Typst** (`scripts/generate-typst-themes.mjs`) for resume generation instead of heavy headless Chrome HTML-to-PDF or complex LaTeX dependencies. Typst compiles instantly to flawless vector PDFs with modern typography.
   - *Our Implementation Opportunity:* In WS-05 (`docs/implementation/05-tailoring-and-research.md`), adopt Typst CLI for compiling tailored resumes. It produces cleaner layouts, compiles in milliseconds, and avoids browser print-to-PDF quirks.

---

## 5. Potential Pitfalls / Anti-Patterns to Avoid
- **Total Relinquishment of Submission Automation:** JobOps refuses to automate any application submission, requiring the user to manually fill out every application. While safe, our project's goal is controlled, verified, evidence-backed automation with human approval gates. We bridge the gap between pure manual toil and reckless spam.
- **Monorepo Complexity:** JobOps' multi-package TypeScript structure has numerous sub-packages and tsconfigs that require careful maintenance across Docker builds. Our Python backend + clean `/frontend` React layout is simpler and more focused.
