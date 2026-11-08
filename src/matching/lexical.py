"""BM25 lexical retrieval and keyword matching (WS-20).

The structured skill component compares two *lists*. A posting that demands
Kubernetes without tagging it, or buries "distributed systems" in the fourth
paragraph of the description, is invisible to it. This module adds the missing
channel: **Okapi BM25 over the full posting**, plus precise keyword and phrase
matching.

No dependency is added. The corpus is small (bounded by
``max_corpus_listings``) and the formula is short, so it is implemented here —
deterministic, transparent, and free of a third-party tie to a specific BM25
variant.

Design points
-------------

- **Field-aware weighting.** A hit in the title or an explicitly required
  qualification matters more than an incidental word in the body. Fields are
  weighted by repeating their tokens (:data:`FIELD_WEIGHTS`), which is the
  documented way to do field weighting in a single-field BM25 index.
- **A stable, absolute scale.** Raw BM25 is corpus-relative; it is mapped to
  0-100 by the saturating transform ``100 · raw / (raw + K)``. This is
  monotonic and *absolute* — the same document and query give the same number
  in any corpus — and deliberately avoids per-query min-max normalisation,
  which would make a score mean different things in different searches.
- **No false substring matches.** Tokens are whole words. ``java`` never
  matches ``javascript``; single-character tokens are dropped so ``C`` cannot
  match an unrelated word.
- **No double counting with the skill component.** The structured
  ``required_skills``/``preferred_skills`` lists stay in the BM25 corpus (they
  help retrieval) but are **excluded from the keyword-coverage numerator**,
  because the ``skill`` component already measures exactly that overlap.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel, Field

from src.jobs.contracts import JobListing
from src.resume.profile import CandidateProfile

__all__ = [
    "BM25_HALF_SATURATION",
    "Bm25Index",
    "LexicalResult",
    "candidate_lexical_text",
    "candidate_tokens",
    "lexical_score",
    "normalize_term",
    "tokenize",
]

K1 = 1.5
B = 0.75

#: The raw BM25 score at which the scaled value reaches 50. Saturating rather
#: than min-max normalising keeps the number comparable across searches.
BM25_HALF_SATURATION = 6.0

#: How much the BM25 channel and the keyword-coverage channel each contribute
#: to the lexical component.
BM25_WEIGHT = 0.6
COVERAGE_WEIGHT = 0.4

#: Token multiplicity per field (field-aware weighting by repetition).
FIELD_WEIGHTS: dict[str, int] = {
    "title": 3,
    "required_skills": 3,
    "preferred_skills": 2,
    "requirements": 2,
    "description": 1,
}

#: Only genuinely equivalent terms. A wrong alias is a wrong match.
_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "psql": "postgresql",
    "golang": "go",
    "nodejs": "node",
    "node.js": "node",
    "csharp": "c#",
    "dotnet": ".net",
    "ml": "machine learning",
    "ai": "artificial intelligence",
}

#: Words too common to be evidence. Kept deliberately short: the IDF term
#: already discounts a common word, and a long stop-list would silently drop
#: a real requirement.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "any",
        "can",
        "her",
        "was",
        "one",
        "our",
        "out",
        "day",
        "get",
        "has",
        "him",
        "his",
        "how",
        "its",
        "new",
        "now",
        "old",
        "see",
        "two",
        "way",
        "who",
        "boy",
        "did",
        "use",
        "may",
        "with",
        "that",
        "this",
        "from",
        "they",
        "will",
        "have",
        "your",
        "team",
        "role",
        "work",
        "job",
        "well",
        "must",
        "able",
        "also",
        "into",
        "more",
        "than",
        "them",
        "then",
        "were",
        "what",
        "when",
        "which",
        "while",
        "would",
        "about",
        "across",
        "after",
        "other",
        "such",
        "over",
        "these",
        "those",
        "very",
        "been",
        "both",
        "each",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9#+._/-]*")


def tokenize(text: str | None) -> list[str]:
    """Whole-word tokens, lowercased, aliases applied, short tokens dropped.

    ``c++``, ``c#`` and ``node.js`` survive as single tokens; ``java`` and
    ``javascript`` do not collide; a one-letter token (``C``) is dropped so it
    cannot match an unrelated word.
    """
    if not text:
        return []
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        token = raw.strip("._-/")
        if not token:
            continue
        token = _ALIASES.get(token, token)
        if len(token) < 2:
            continue
        tokens.append(token)
    return tokens


def normalize_term(term: str) -> str:
    """A single term in canonical form (aliases applied, lowercased)."""
    tokens = tokenize(term)
    return tokens[0] if tokens else ""


def _document_tokens(job: JobListing) -> list[str]:
    """The weighted token bag for one listing."""
    fields: dict[str, list[str]] = {
        "title": tokenize(job.title),
        "required_skills": tokenize(" ".join(job.required_skills)),
        "preferred_skills": tokenize(" ".join(job.preferred_skills)),
        "requirements": tokenize(
            " ".join(filter(None, [job.experience_requirements, job.education_requirements]))
        ),
        "description": tokenize(job.description),
    }
    bag: list[str] = []
    for name, tokens in fields.items():
        bag.extend(tokens * FIELD_WEIGHTS.get(name, 1))
    return bag


class _Document:
    __slots__ = ("freq", "length")

    def __init__(self, tokens: list[str]) -> None:
        self.freq = Counter(tokens)
        self.length = len(tokens)


class Bm25Index:
    """One BM25 index over a set of listings (build once per search)."""

    def __init__(self, listings: Iterable[JobListing]) -> None:
        self._documents: dict[str, _Document] = {}
        df: Counter[str] = Counter()
        for job in listings:
            document = _Document(_document_tokens(job))
            self._documents[job.id] = document
            for term in document.freq:
                df[term] += 1
        self._n = len(self._documents)
        self._avgdl = (
            sum(document.length for document in self._documents.values()) / self._n
            if self._n
            else 0.0
        )
        self._idf = {
            term: math.log(1.0 + (self._n - count + 0.5) / (count + 0.5))
            for term, count in df.items()
        }

    def __len__(self) -> int:
        return self._n

    def score(self, job_id: str, query_tokens: list[str]) -> float:
        """Raw BM25 relevance of one document for the query terms."""
        document = self._documents.get(job_id)
        if document is None or not document.length or not query_tokens:
            return 0.0
        avgdl = self._avgdl or 1.0
        total = 0.0
        for term in dict.fromkeys(query_tokens):
            freq = document.freq.get(term)
            if not freq:
                continue
            idf = self._idf.get(term, 0.0)
            denominator = freq + K1 * (1.0 - B + B * document.length / avgdl)
            total += idf * (freq * (K1 + 1.0)) / denominator
        return total

    @staticmethod
    def scale(raw: float) -> float:
        """Map a raw BM25 score onto 0-100 (saturating, absolute, stable)."""
        if raw <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * raw / (raw + BM25_HALF_SATURATION)))


class LexicalResult(BaseModel):
    """The lexical component's value and the evidence behind it."""

    score: float = Field(0.0, ge=0.0, le=100.0)
    bm25_score: float = Field(0.0, ge=0.0, le=100.0)
    keyword_coverage: float = Field(0.0, ge=0.0, le=100.0)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    matched_phrases: list[str] = Field(default_factory=list)
    missing_phrases: list[str] = Field(default_factory=list)


def candidate_lexical_text(profile: CandidateProfile) -> str:
    """The candidate's professional text, for the lexical query.

    Uses the whole professional record — title, summary, skills, experience
    titles and bullets, project technologies and descriptions, education and
    certifications. **No contact information** is included: an email or phone
    number in a search string is noise at best and a leak at worst.
    """
    parts: list[str] = []
    info = profile.personal_information
    if info.title:
        parts.append(info.title)
    if profile.summary:
        parts.append(profile.summary)
    if profile.skills:
        parts.append(" ".join(profile.skills))
    for entry in profile.experience:
        if entry.title:
            parts.append(entry.title)
        parts.extend(entry.bullets)
    for project in profile.projects:
        parts.append(project.name)
        if project.tech:
            parts.append(project.tech)
        parts.extend(project.bullets)
    for education in profile.education:
        if education.degree:
            parts.append(education.degree)
    parts.extend(profile.certifications)
    parts.extend(profile.achievements)
    return " ".join(part for part in parts if part)


def candidate_tokens(profile: CandidateProfile) -> list[str]:
    """Tokenised candidate query, with the title and skills weighted higher."""
    info = profile.personal_information
    weighted: list[str] = []
    weighted.extend(tokenize(info.title) * 2)
    weighted.extend(tokenize(" ".join(profile.skills)) * 2)
    weighted.extend(tokenize(candidate_lexical_text(profile)))
    return weighted


def _important_terms(job: JobListing) -> list[tuple[str, float]]:
    """The job's important terms and their weight, from title + description.

    The structured skill lists are deliberately **not** included: the ``skill``
    component already scores exactly that overlap, and counting it again here
    would double-weight it.
    """
    terms: list[tuple[str, float]] = []
    seen: set[str] = set()
    for token in tokenize(job.title):
        if token not in seen:
            seen.add(token)
            terms.append((token, 2.0))
    for token in tokenize(job.description):
        if token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append((token, 1.0))
    return terms


def _required_phrases(job: JobListing) -> list[str]:
    """Multi-word phrases from the required-skill list, preserved as phrases."""
    phrases: list[str] = []
    for skill in job.required_skills:
        cleaned = " ".join((skill or "").split())
        if cleaned and " " in cleaned:
            phrases.append(cleaned)
    return phrases


def lexical_score(
    job: JobListing,
    *,
    index: Bm25Index | None,
    candidate_token_list: list[str],
    candidate_text: str,
    important_terms: list[tuple[str, float]] | None = None,
) -> LexicalResult:
    """The lexical component for one listing.

    Combines the absolute BM25 relevance with keyword coverage. A missing
    index (no corpus statistics) leaves only keyword coverage; an empty
    candidate leaves zero — but that is the caller's signal of *missing data*,
    not a measured zero.

    ``important_terms`` is the precomputed weight list for this listing
    (``_important_terms(job)``): it depends only on the listing, so a bulk
    search passes the corpus cache's copy instead of re-tokenizing every
    posting on every request.
    """
    bm25 = 0.0
    if index is not None:
        bm25 = Bm25Index.scale(index.score(job.id, candidate_token_list))

    candidate_set = set(candidate_token_list)
    terms = important_terms if important_terms is not None else _important_terms(job)
    total_weight = sum(weight for _term, weight in terms)
    matched_weight = 0.0
    matched: list[str] = []
    missing: list[str] = []
    for term, weight in terms:
        if term in candidate_set:
            matched.append(term)
            matched_weight += weight
        else:
            missing.append(term)
    coverage = (matched_weight / total_weight * 100.0) if total_weight else 0.0

    lowered_candidate = candidate_text.lower()
    matched_phrases: list[str] = []
    missing_phrases: list[str] = []
    for phrase in _required_phrases(job):
        if phrase.lower() in lowered_candidate:
            matched_phrases.append(phrase)
        else:
            missing_phrases.append(phrase)

    score = BM25_WEIGHT * bm25 + COVERAGE_WEIGHT * coverage
    return LexicalResult(
        score=max(0.0, min(100.0, score)),
        bm25_score=bm25,
        keyword_coverage=coverage,
        matched_keywords=matched[:25],
        missing_keywords=missing[:25],
        matched_phrases=matched_phrases,
        missing_phrases=missing_phrases,
    )
