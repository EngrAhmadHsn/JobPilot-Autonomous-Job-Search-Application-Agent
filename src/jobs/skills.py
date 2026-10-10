"""Deterministic skill extraction from job text (WS-02 task 2).

A curated lexicon of ~150 technology skills with regex-safe aliases is
scanned word-boundary, case-insensitively over listing text. No LLM, no
fabrication: a skill is reported only when its text (or an alias) literally
appears. Used by all three source adapters to populate
``required_skills``/``preferred_skills``.

Precision-first decisions (deliberate omissions):

- Bare ``C`` is excluded: ``C`` matches inside "C-level", "C suite" and
  cannot be separated from prose reliably; C/C++ postings always match the
  ``C++`` entry anyway.
- Bare ``Go`` is excluded ("go to market", "let's go"); ``Golang`` is kept.
- Bare ``R`` is excluded ("R&D", bullet-list letters); no unambiguous short
  alias exists.

Word boundaries keep "Java" from matching "JavaScript" and "JS" from
matching "NodeJS"; aliases with symbols (``C++``, ``C#``, ``.NET``,
``CI/CD``) use explicit non-letter boundaries so "C++17" still matches.
"""

from __future__ import annotations

import re

# Canonical skill name -> list of textual aliases (case-insensitive).
# The canonical name itself must always be included in its alias list.
SKILL_LEXICON: dict[str, list[str]] = {
    # --- Languages ---
    "Python": ["Python"],
    "Java": ["Java"],
    "JavaScript": ["JavaScript", "JS", "ECMAScript"],
    "TypeScript": ["TypeScript", "TS"],
    "Golang": ["Golang", "Go language"],
    "Rust": ["Rust"],
    "C++": ["C++"],
    "C#": ["C#", "C Sharp"],
    "Ruby": ["Ruby"],
    "PHP": ["PHP"],
    "Swift": ["Swift"],
    "Kotlin": ["Kotlin"],
    "Scala": ["Scala"],
    "Dart": ["Dart"],
    "MATLAB": ["MATLAB"],
    "SQL": ["SQL"],
    "PL/SQL": ["PL/SQL"],
    "Bash": ["Bash", "Shell scripting", "Shell"],
    "Perl": ["Perl"],
    "Elixir": ["Elixir"],
    "Haskell": ["Haskell"],
    "Lua": ["Lua"],
    "Groovy": ["Groovy"],
    "Objective-C": ["Objective-C"],
    "Solidity": ["Solidity"],
    "Julia": ["Julia"],
    # --- Web frameworks / libraries ---
    "React": ["React", "ReactJS", "React.js"],
    "Angular": ["Angular", "AngularJS"],
    "Vue": ["Vue", "VueJS", "Vue.js"],
    "Next.js": ["Next.js", "NextJS"],
    "Svelte": ["Svelte", "SvelteKit"],
    "Django": ["Django"],
    "Flask": ["Flask"],
    "FastAPI": ["FastAPI"],
    "Spring": ["Spring Boot", "Spring"],
    "Ruby on Rails": ["Ruby on Rails", "Rails"],
    "Laravel": ["Laravel"],
    "Symfony": ["Symfony"],
    "Express": ["Express.js", "ExpressJS", "Express"],
    "NestJS": ["NestJS", "Nest.js"],
    "ASP.NET": ["ASP.NET"],
    ".NET": [".NET", ".NET Core", "dotnet"],
    "Node.js": ["Node.js", "NodeJS", "Node"],
    "Deno": ["Deno"],
    "Electron": ["Electron"],
    "Tailwind CSS": ["Tailwind CSS", "Tailwind"],
    "Bootstrap": ["Bootstrap"],
    "jQuery": ["jQuery"],
    "GraphQL": ["GraphQL"],
    "REST": ["REST API", "RESTful", "REST"],
    "gRPC": ["gRPC"],
    "WebSocket": ["WebSocket", "WebSockets"],
    "Redux": ["Redux"],
    # --- AI / ML / data science ---
    "Machine Learning": ["Machine Learning", "ML"],
    "Deep Learning": ["Deep Learning"],
    "Natural Language Processing": ["Natural Language Processing", "NLP"],
    "Computer Vision": ["Computer Vision"],
    "PyTorch": ["PyTorch", "Torch"],
    "TensorFlow": ["TensorFlow"],
    "Keras": ["Keras"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "OpenCV": ["OpenCV"],
    "pandas": ["pandas"],
    "NumPy": ["NumPy"],
    "Polars": ["Polars"],
    "LLM": ["LLM", "LLMs", "Large Language Model", "Large Language Models"],
    "RAG": ["RAG", "Retrieval-Augmented Generation", "Retrieval Augmented Generation"],
    "LangChain": ["LangChain"],
    "LangGraph": ["LangGraph"],
    "LlamaIndex": ["LlamaIndex", "Llama Index"],
    "Hugging Face": ["Hugging Face", "HuggingFace"],
    "Prompt Engineering": ["Prompt Engineering"],
    "Fine-tuning": ["Fine-tuning", "Finetuning", "Fine tuning"],
    "Embeddings": ["Embeddings", "Embedding"],
    "MLOps": ["MLOps"],
    "CUDA": ["CUDA"],
    "ONNX": ["ONNX"],
    "FAISS": ["FAISS"],
    "pgvector": ["pgvector"],
    "Pinecone": ["Pinecone"],
    "Weaviate": ["Weaviate"],
    "Qdrant": ["Qdrant"],
    "Milvus": ["Milvus"],
    "ChromaDB": ["ChromaDB", "Chroma DB"],
    # --- Databases / data stores ---
    "PostgreSQL": ["PostgreSQL", "Postgres"],
    "MySQL": ["MySQL"],
    "SQLite": ["SQLite"],
    "MongoDB": ["MongoDB", "Mongo"],
    "Redis": ["Redis"],
    "Elasticsearch": ["Elasticsearch", "Elastic Search"],
    "OpenSearch": ["OpenSearch"],
    "DynamoDB": ["DynamoDB"],
    "Cassandra": ["Cassandra"],
    "Snowflake": ["Snowflake"],
    "BigQuery": ["BigQuery", "BigQuery SQL"],
    "Redshift": ["Redshift"],
    "ClickHouse": ["ClickHouse"],
    "MariaDB": ["MariaDB"],
    "SQL Server": ["SQL Server", "MSSQL", "Microsoft SQL Server"],
    "Oracle": ["Oracle DB", "Oracle"],
    "Neo4j": ["Neo4j"],
    "Supabase": ["Supabase"],
    "Prisma": ["Prisma"],
    "SQLAlchemy": ["SQLAlchemy"],
    # --- Data engineering ---
    "Apache Spark": ["Apache Spark", "Spark", "PySpark"],
    "Hadoop": ["Hadoop"],
    "Kafka": ["Kafka"],
    "RabbitMQ": ["RabbitMQ"],
    "Celery": ["Celery"],
    "Airflow": ["Airflow"],
    "dbt": ["dbt"],
    "ETL": ["ETL", "ELT"],
    "Data Engineering": ["Data Engineering"],
    "Data Modeling": ["Data Modeling", "Data Modelling"],
    # --- Cloud / infrastructure / DevOps ---
    "AWS": ["AWS", "Amazon Web Services"],
    "Azure": ["Azure", "Microsoft Azure"],
    "Google Cloud": ["Google Cloud", "GCP"],
    "Kubernetes": ["Kubernetes", "K8s"],
    "Docker": ["Docker"],
    "Terraform": ["Terraform"],
    "Pulumi": ["Pulumi"],
    "Ansible": ["Ansible"],
    "Helm": ["Helm"],
    "Istio": ["Istio"],
    "ArgoCD": ["ArgoCD", "Argo CD"],
    "Jenkins": ["Jenkins"],
    "GitHub Actions": ["GitHub Actions"],
    "GitLab CI": ["GitLab CI", "GitLab CI/CD"],
    "CircleCI": ["CircleCI"],
    "CloudFormation": ["CloudFormation"],
    "Serverless": ["Serverless"],
    "AWS Lambda": ["AWS Lambda", "Lambda functions"],
    "Nginx": ["Nginx", "nginx"],
    "Linux": ["Linux"],
    "Git": ["Git"],
    "GitOps": ["GitOps"],
    "CI/CD": ["CI/CD", "Continuous Integration", "Continuous Delivery", "Continuous Deployment"],
    "DevOps": ["DevOps"],
    "SRE": ["SRE", "Site Reliability Engineering"],
    "Microservices": ["Microservices", "Microservices Architecture"],
    "Distributed Systems": ["Distributed Systems"],
    "System Design": ["System Design"],
    "Prometheus": ["Prometheus"],
    "Grafana": ["Grafana"],
    "Datadog": ["Datadog"],
    "OpenTelemetry": ["OpenTelemetry", "OTel"],
    "Observability": ["Observability"],
    "Splunk": ["Splunk"],
    # --- Security ---
    "OAuth": ["OAuth 2.0", "OAuth2", "OAuth 2", "OAuth"],
    "OIDC": ["OIDC", "OpenID Connect"],
    "JWT": ["JWT", "JSON Web Token"],
    "SSO": ["SSO", "Single Sign-On", "Single Sign On"],
    "SAML": ["SAML"],
    "RBAC": ["RBAC", "Role-Based Access Control"],
    "OWASP": ["OWASP"],
    "TLS": ["TLS", "mTLS"],
    "Cryptography": ["Cryptography", "Cryptographic"],
    "IAM": ["IAM", "Identity and Access Management"],
    # --- Mobile ---
    "Android": ["Android"],
    "iOS": ["iOS"],
    "React Native": ["React Native"],
    "Flutter": ["Flutter"],
    "SwiftUI": ["SwiftUI"],
    # --- Practices ---
    "Agile": ["Agile"],
    "Scrum": ["Scrum"],
    "Kanban": ["Kanban"],
    "TDD": ["TDD", "Test-Driven Development"],
    "BDD": ["BDD", "Behavior-Driven Development"],
    "pytest": ["pytest"],
    "JUnit": ["JUnit"],
    "Selenium": ["Selenium"],
    "Playwright": ["Playwright"],
    "Cypress": ["Cypress"],
    "Jest": ["Jest"],
}

# Plain aliases use \b word boundaries (digits count as boundary chars, so
# "Java" cannot match "JavaScript"). Aliases containing symbols (C++, C#,
# .NET, CI/CD) use explicit non-letter boundaries: symbols may be followed
# by digits ("C++17", ".NET 8") but not letters, and must not be preceded by
# a letter/digit/symbol (so "ASP.NET" is not matched by ".NET" — it is its
# own entry).
_PLAIN_ALIAS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _compile_alias(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    if _PLAIN_ALIAS_RE.fullmatch(alias) and alias[0].isalnum():
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return re.compile(rf"(?<![A-Za-z0-9+.#]){escaped}(?![A-Za-z])", re.IGNORECASE)


# (canonical, alias, compiled pattern) — sorted longest-alias-first is not
# needed because each alias is an independent search; ordering only affects
# position reporting, handled per canonical below.
_COMPILED: list[tuple[str, str, re.Pattern[str]]] = [
    (canonical, alias, _compile_alias(alias))
    for canonical, aliases in SKILL_LEXICON.items()
    for alias in aliases
]


def extract_skills(text: str | None) -> list[str]:
    """Extract lexicon skills mentioned in ``text``.

    Returns canonical skill names in order of first appearance in the text
    (ties broken alphabetically), deduplicated. Empty/None input returns [].
    Deterministic: same text always yields the same list.
    """
    if not text:
        return []
    first_pos: dict[str, int] = {}
    for canonical, _alias, pattern in _COMPILED:
        if canonical in first_pos:
            continue
        match = pattern.search(text)
        if match:
            first_pos[canonical] = match.start()
    return sorted(first_pos, key=lambda name: (first_pos[name], name))


_PREFERRED_HEADING_RE = re.compile(
    r"^\s*(?:[#*\->]*\s*)?"
    r"(nice to have|preferred|bonus|good to have|desirable|plus points|bonus points|pluses?)"
    r"\b[^\n]{0,60}$",
    re.IGNORECASE,
)


def split_required_preferred(text: str | None) -> tuple[list[str], list[str]]:
    """Split extracted skills into required and preferred by section.

    Heuristic per WS-02: skills mentioned before the first "nice to have" /
    "preferred" / "bonus" style heading are required; skills first appearing
    inside that trailing section are preferred. A skill mentioned in both is
    required (first mention wins). Without a preferred section, every
    extracted skill is required.
    """
    if not text:
        return [], []
    preferred_start = None
    for line in text.splitlines():
        if _PREFERRED_HEADING_RE.match(line):
            preferred_start = text.find(line)
            break
    if preferred_start is None:
        return extract_skills(text), []
    required = extract_skills(text[:preferred_start])
    required_set = set(required)
    preferred = [
        skill for skill in extract_skills(text[preferred_start:]) if skill not in required_set
    ]
    return required, preferred
