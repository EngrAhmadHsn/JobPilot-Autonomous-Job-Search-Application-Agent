"""Generate the golden job listings for the WS-09 evaluation harness.

Twenty-five normalized listings with graded relevance labels per golden
profile (2 = relevant, 1 = partial, 0 = irrelevant) and annotated duplicate
groups (``dup_of``) for the dedup metrics. The duplicates share a
``source_job_id`` — the realistic "same posting seen twice" case — so
``deduplicate()`` collapses them.

Usage:
    python scripts/make_golden_jobs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

OUT = REPO_ROOT / "tests" / "evaluation" / "golden" / "jobs.jsonl"

ALEX = "alex_rivera_backend"
MINA = "mina_chen_ml"
SAM = "sam_okoye_data"
LENA = "lena_fischer_frontend"


def labels(alex=0, mina=0, sam=0, lena=0) -> dict[str, int]:
    return {ALEX: alex, MINA: mina, SAM: sam, LENA: lena}


def job(
    job_id: str,
    source_job_id: str,
    title: str,
    company: str,
    location: str,
    required: list[str],
    preferred: list[str],
    description: str,
    graded: dict[str, int],
    dup_of: str | None = None,
    seniority: str | None = None,
) -> dict:
    record = {
        # The listing id is unique per record; duplicates share the
        # ``source_job_id`` (the same posting seen twice), which is what
        # ``deduplicate()`` collapses on.
        "id": f"golden:{job_id}",
        "source": "greenhouse",
        "source_job_id": source_job_id,
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "required_skills": required,
        "preferred_skills": preferred,
        "seniority": seniority,
        "labels": graded,
    }
    if dup_of:
        record["dup_of"] = dup_of
    return record


PYTHON_BACKEND = (
    "Build and operate Python services with FastAPI on Docker and AWS. You will own APIs, "
    "migrations and on-call for a high-traffic checkout platform."
)
PYTHON_DJANGO = (
    "Own backend services in Django and Python, design PostgreSQL schemas and improve "
    "reliability of data pipelines across the organisation."
)
ML_RETRIEVAL = (
    "Build retrieval and ranking models with PyTorch and Hugging Face. Ship semantic search "
    "over large document corpora and evaluate recall with offline metrics."
)
ML_PLATFORM = (
    "Run model inference in production with Docker and Kubernetes. Expose services with "
    "FastAPI and keep Redis caches warm for low latency retrieval."
)
DATA_ANALYST = (
    "Turn operational data into dashboards. Write SQL, maintain dbt models and publish "
    "reporting in Power BI for commercial stakeholders."
)
DATA_ENGINEER = (
    "Design batch and streaming pipelines with Airflow and Spark. Own SQL models end to end "
    "and mentor analysts on dbt modelling."
)
FRONTEND = (
    "Build accessible React interfaces in TypeScript. Collaborate with design on CSS systems "
    "and cover components with Jest tests."
)

ROWS = [
    job(
        "job-001",
        "1001",
        "Backend Engineer",
        "Acme Corp",
        "Austin, Texas",
        ["Python", "FastAPI", "Docker"],
        ["AWS", "Kubernetes"],
        PYTHON_BACKEND,
        labels(alex=2, mina=1),
    ),
    job(
        "job-002",
        "1002",
        "Senior Python Engineer",
        "Lumen Data",
        "Remote",
        ["Python", "Django", "PostgreSQL"],
        ["AWS", "Redis"],
        PYTHON_DJANGO,
        labels(alex=2, mina=1),
        seniority="senior",
    ),
    job(
        "job-003",
        "1003",
        "Machine Learning Engineer",
        "Northwind AI",
        "Seattle, Washington",
        ["Python", "PyTorch", "Hugging Face"],
        ["sentence-transformers", "Docker"],
        ML_RETRIEVAL,
        labels(alex=1, mina=2),
    ),
    job(
        "job-004",
        "1004",
        "ML Platform Engineer",
        "Northwind AI",
        "Remote",
        ["Python", "Docker", "Kubernetes"],
        ["FastAPI", "Redis"],
        ML_PLATFORM,
        labels(alex=1, mina=2),
    ),
    job(
        "job-005",
        "1005",
        "Data Analyst",
        "Harbour Retail Group",
        "London, United Kingdom",
        ["SQL", "dbt", "Power BI"],
        ["Looker", "Excel"],
        DATA_ANALYST,
        labels(sam=2),
    ),
    job(
        "job-006",
        "1006",
        "Senior Data Engineer",
        "Harbour Retail Group",
        "London, United Kingdom",
        ["SQL", "Airflow", "Spark"],
        ["Python", "dbt"],
        DATA_ENGINEER,
        labels(alex=1, sam=2),
        seniority="senior",
    ),
    job(
        "job-007",
        "1007",
        "Frontend Engineer",
        "Kite Studio",
        "Berlin, Germany",
        ["React", "TypeScript", "CSS"],
        ["Next.js", "Jest"],
        FRONTEND,
        labels(lena=2),
    ),
    job(
        "job-008",
        "1008",
        "Fullstack Engineer",
        "Kite Studio",
        "Berlin, Germany",
        ["TypeScript", "Node.js", "PostgreSQL"],
        ["React", "Docker"],
        "Ship features across a TypeScript stack: React on the front, Node.js services and "
        "PostgreSQL storage, deployed with Docker.",
        labels(alex=1, lena=1),
    ),
    job(
        "job-009",
        "1009",
        "DevOps Engineer",
        "Beacon Systems",
        "Remote",
        ["Kubernetes", "Terraform", "AWS"],
        ["Docker", "Python"],
        "Automate infrastructure with Terraform on AWS and run workloads on Kubernetes. Write "
        "Python tooling for deployment pipelines.",
        labels(alex=1),
    ),
    job(
        "job-010",
        "1010",
        "Backend Engineering Intern",
        "Lumen Data",
        "Austin, Texas",
        ["Python"],
        ["Git"],
        "Support backend engineers with Python tooling and small service improvements during a "
        "twelve week internship.",
        labels(alex=1),
    ),
    job(
        "job-011",
        "1011",
        "Sales Engineer",
        "Brightline",
        "New York, New York",
        ["CRM", "SQL"],
        ["Presentation"],
        "Partner with prospects, run product demonstrations and support technical evaluations "
        "for new customers.",
        labels(),
    ),
    job(
        "job-012",
        "1012",
        "Product Manager",
        "Kite Studio",
        "Berlin, Germany",
        ["Roadmapping", "Discovery"],
        ["SQL"],
        "Own product discovery and roadmap for the analytics product line. Partner with "
        "engineering and research.",
        labels(),
    ),
    job(
        "job-013",
        "1013",
        "Data Scientist",
        "Harbour Retail Group",
        "London, United Kingdom",
        ["Python", "SQL", "Statistics"],
        ["dbt", "Power BI"],
        "Develop statistical models for demand forecasting and experiment analysis, and present "
        "findings to commercial teams.",
        labels(mina=1, sam=1),
    ),
    job(
        "job-014",
        "1014",
        "QA Automation Engineer",
        "Beacon Systems",
        "Remote",
        ["Python", "Playwright", "Jest"],
        ["TypeScript", "React"],
        "Automate end to end testing with Playwright and unit testing with Jest. Write Python "
        "tooling around the release pipeline.",
        labels(alex=1, lena=1),
    ),
    job(
        "job-015",
        "1015",
        "Solutions Architect",
        "Beacon Systems",
        "Austin, Texas",
        ["AWS", "Kubernetes", "Python"],
        ["Terraform"],
        "Design cloud architectures on AWS and Kubernetes, and write proof of concept services "
        "in Python for customers.",
        labels(alex=1),
    ),
    job(
        "job-016",
        "1016",
        "MLOps Engineer",
        "Northwind AI",
        "Seattle, Washington",
        ["Python", "Docker", "FastAPI"],
        ["Kubernetes", "Redis"],
        "Own the model deployment path: containerise models with Docker, serve them through "
        "FastAPI and monitor inference quality.",
        labels(alex=1, mina=2),
    ),
    job(
        "job-017",
        "1017",
        "Data Engineer",
        "Kite Studio",
        "Berlin, Germany",
        ["Python", "Airflow", "SQL"],
        ["dbt"],
        "Build and schedule data pipelines with Airflow, write transformation models in SQL and "
        "maintain Python jobs for ingestion.",
        labels(alex=1, sam=1),
    ),
    job(
        "job-018",
        "1018",
        "UI Engineer",
        "Kite Studio",
        "Berlin, Germany",
        ["React", "TypeScript", "Tailwind CSS"],
        ["Next.js", "Jest"],
        "Implement accessible interfaces in React and TypeScript with Tailwind CSS, and keep "
        "component tests green with Jest.",
        labels(lena=2),
    ),
    # -- duplicate groups: the same posting seen through another id ----------
    job(
        "job-019",
        "1001",
        "Backend Engineer",
        "Acme Corp",
        "Austin, Texas",
        ["Python", "FastAPI", "Docker"],
        ["AWS", "Kubernetes"],
        PYTHON_BACKEND,
        labels(alex=2, mina=1),
        dup_of="job-001",
    ),
    job(
        "job-020",
        "1001",
        "Backend Engineer",
        "Acme Corp",
        "Austin, Texas",
        ["Python", "FastAPI", "Docker"],
        ["AWS", "Kubernetes"],
        PYTHON_BACKEND,
        labels(alex=2, mina=1),
        dup_of="job-001",
    ),
    job(
        "job-021",
        "1003",
        "Machine Learning Engineer",
        "Northwind AI",
        "Seattle, Washington",
        ["Python", "PyTorch", "Hugging Face"],
        ["sentence-transformers", "Docker"],
        ML_RETRIEVAL,
        labels(alex=1, mina=2),
        dup_of="job-003",
    ),
    job(
        "job-022",
        "1005",
        "Data Analyst",
        "Harbour Retail Group",
        "London, United Kingdom",
        ["SQL", "dbt", "Power BI"],
        ["Looker", "Excel"],
        DATA_ANALYST,
        labels(sam=2),
        dup_of="job-005",
    ),
    job(
        "job-023",
        "1007",
        "Frontend Engineer",
        "Kite Studio",
        "Berlin, Germany",
        ["React", "TypeScript", "CSS"],
        ["Next.js", "Jest"],
        FRONTEND,
        labels(lena=2),
        dup_of="job-007",
    ),
    job(
        "job-024",
        "1024",
        "Security Engineer",
        "Beacon Systems",
        "Remote",
        ["Linux", "Python", "Security"],
        ["AWS"],
        "Harden platforms and services. Run vulnerability reviews and write Python tooling for "
        "security automation.",
        labels(),
    ),
    job(
        "job-025",
        "1025",
        "Engineering Manager",
        "Brightline",
        "New York, New York",
        ["Leadership", "Delivery"],
        ["SQL"],
        "Lead a team of engineers, own delivery and hiring for the platform group.",
        labels(),
    ),
]


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in ROWS) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(ROWS)} golden jobs to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
