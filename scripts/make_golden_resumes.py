"""Generate the synthetic golden resumes for the WS-09 evaluation harness.

The golden set must be *synthetic*: no real candidate data beyond what the
repository already carries. The resumes are generated from the content below
so the dataset is reproducible and reviewable — re-run this script to rebuild
``tests/evaluation/golden/resumes/``.

The documents follow the conventions the existing parser understands
(section headings, ``Title | Company`` experience headers, tab-separated
education lines, ``Category: a, b, c`` skill lines) so the golden set
measures the pipeline rather than the parser's tolerance for odd layouts.

Usage:
    python scripts/make_golden_resumes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

GOLDEN_DIR = REPO_ROOT / "tests" / "evaluation" / "golden" / "resumes"

# Each resume is a list of (style, text) lines. Style "bullet" renders a
# list item, "tab" is a plain paragraph (tabs are meaningful in education
# lines), everything else is a plain paragraph.
RESUMES: dict[str, list[tuple[str, str]]] = {
    "alex_rivera_backend.docx": [
        ("h", "Alex Rivera"),
        ("p", "Backend Engineer"),
        ("p", "alex.rivera@example.com | +1 415 555 0134 | Austin, Texas"),
        ("p", "github.com/alexrivera"),
        ("h", "PROFESSIONAL SUMMARY"),
        (
            "p",
            (
                "Backend engineer with six years building Python services and data "
                "pipelines for logistics and fintech teams."
            ),
        ),
        ("h", "TECHNICAL SKILLS"),
        ("p", "Languages: Python, Go, SQL"),
        ("p", "Frameworks: FastAPI, Django, Flask"),
        ("p", "Infrastructure: Docker, Kubernetes, AWS, Terraform"),
        ("h", "EXPERIENCE"),
        ("p", "Backend Engineer | Acme Corp | 2021-2024"),
        ("bullet", "Rebuilt the order API in FastAPI, cutting p95 latency from 900ms to 180ms."),
        ("bullet", "Migrated 40 services to Kubernetes with zero customer-visible downtime."),
        ("p", "Software Engineer | Lumen Data | 2019-2021"),
        ("bullet", "Built ETL pipelines in Python processing 2TB of event data daily."),
        ("bullet", "Introduced integration tests that cut release regressions by a third."),
        ("h", "PROJECTS"),
        ("p", "Order Service — Python, FastAPI, PostgreSQL"),
        ("bullet", "Designed an idempotent checkout service handling 120 requests per second."),
        ("h", "EDUCATION"),
        ("p", "BSc Computer Science\t2015-2019"),
        ("p", "Example University"),
        ("p", "GPA: 3.8/4.0"),
        ("h", "CERTIFICATIONS"),
        ("bullet", "AWS Certified Solutions Architect - Associate"),
    ],
    "mina_chen_ml.txt": [
        ("p", "Mina Chen"),
        ("p", "Machine Learning Engineer"),
        ("p", "mina.chen@example.org | +1 206 555 0177 | Seattle, Washington"),
        ("p", "SUMMARY"),
        (
            "p",
            (
                "Machine learning engineer focused on retrieval and evaluation for "
                "developer tooling, shipping models to production."
            ),
        ),
        ("p", "SKILLS"),
        ("p", "Languages: Python, R"),
        ("p", "ML: PyTorch, scikit-learn, Hugging Face, sentence-transformers"),
        ("p", "Serving: FastAPI, Docker, Redis"),
        ("p", "EXPERIENCE"),
        ("p", "Machine Learning Engineer | Northwind AI | 2022-2025"),
        ("bullet", "Shipped a semantic search service over 1.2M documents with 0.82 recall@10."),
        ("bullet", "Built an offline evaluation harness for retrieval regressions."),
        ("p", "PROJECTS"),
        ("p", "DocRetriever\tPython, PyTorch"),
        ("bullet", "Fine-tuned a bi-encoder and cut inference cost by 60 percent."),
        ("p", "ResumeRank\tPython, FastAPI"),
        ("bullet", "Ranked candidates against job descriptions with hybrid scoring."),
        ("p", "EDUCATION"),
        ("p", "MSc Computer Science\t2018-2022"),
        ("p", "Example Institute of Technology"),
    ],
    "sam_okoye_data.docx": [
        ("h", "Sam Okoye"),
        ("p", "Data Analyst"),
        ("p", "sam.okoye@example.net | +44 20 7946 0958 | London, United Kingdom"),
        ("p", "Preferences: open to remote work, Berlin"),
        ("h", "PROFESSIONAL SUMMARY"),
        (
            "p",
            (
                "Data analyst turning messy operational data into dashboards and "
                "decision-ready reports."
            ),
        ),
        ("h", "TECHNICAL SKILLS"),
        ("p", "Languages: SQL, Python"),
        ("p", "Analytics: dbt, Power BI, Looker, Excel"),
        ("h", "EXPERIENCE"),
        ("p", "Data Analyst | Harbour Retail Group | 2021-2024"),
        ("bullet", "Automated weekly reporting in dbt, saving 12 analyst hours per week."),
        ("bullet", "Built a Power BI adoption tracker used by 40 store managers."),
        ("h", "EDUCATION"),
        ("p", "BSc Statistics\t2017-2020"),
        ("p", "Example College"),
        ("p", "GPA: 3.6/4.0"),
        ("h", "ACHIEVEMENTS"),
        ("bullet", "Analytics team of the quarter award in 2023."),
    ],
    "lena_fischer_frontend.txt": [
        ("p", "Lena Fischer"),
        ("p", "Frontend Developer"),
        ("p", "lena.fischer@example.de | +49 30 901820 | Berlin, Germany"),
        ("p", "SUMMARY"),
        (
            "p",
            (
                "Frontend developer building accessible, tested interfaces for "
                "product teams, with a focus on design systems."
            ),
        ),
        ("p", "TECHNICAL SKILLS"),
        ("p", "Languages: TypeScript, JavaScript"),
        ("p", "Frontend: React, Next.js, Tailwind CSS"),
        ("p", "Testing: Jest, Playwright"),
        ("p", "PROJECTS"),
        ("p", "Design System — React, TypeScript, Storybook"),
        ("bullet", "Built 30 reusable components with 100 percent test coverage."),
        ("bullet", "Cut bundle size by 35 percent through code splitting and lazy loading."),
        ("p", "Storefront — Next.js, Stripe"),
        ("bullet", "Rebuilt the checkout flow, raising conversion by 8 percent."),
        ("p", "EDUCATION"),
        ("p", "Bachelor of Computer Science (BA)\t2016-2019"),
        ("p", "Example University"),
        ("p", "CERTIFICATIONS"),
        ("p", "- Accessibility Fundamentals"),
    ],
}


def write_docx(path: Path, lines: list[tuple[str, str]]) -> None:
    from docx import Document

    document = Document()
    for style, text in lines:
        if style == "bullet":
            document.add_paragraph(text, style="List Bullet")
        elif style == "h":
            paragraph = document.add_paragraph()
            run = paragraph.add_run(text)
            run.bold = True
        else:
            document.add_paragraph(text)
    document.save(str(path))


def write_txt(path: Path, lines: list[tuple[str, str]]) -> None:
    rendered = []
    for style, text in lines:
        rendered.append(f"- {text}" if style == "bullet" else text)
    path.write_text("\n".join(rendered) + "\n", encoding="utf-8")


def main() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name, lines in RESUMES.items():
        path = GOLDEN_DIR / name
        if path.suffix == ".docx":
            write_docx(path, lines)
        else:
            write_txt(path, lines)
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
