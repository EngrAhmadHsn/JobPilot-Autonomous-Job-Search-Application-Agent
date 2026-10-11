"""Milestone 1 demonstration script.

Demonstrates the first working milestone:
Resume → CandidateProfile → Search Jobs → Normalize → Deduplicate → Hybrid Match → Top 10 → Explanation
"""

from __future__ import annotations

from src.jobs.contracts import JobListing
from src.jobs.deduplicate import deduplicate
from src.matching.engine import calculate_match
from src.resume.parser import parse_resume


def main():
    print("=" * 60)
    print("MILESTONE 1 DEMONSTRATION")
    print("=" * 60)

    # 1. Resume parsing
    print("\n[1] Parsing resume...")
    profile = parse_resume("tests/fixtures/Ahmad_Hassan_AI_Engineer_Resume.docx")
    print(f"    Candidate: {profile.personal_information.name}")
    print(f"    Skills: {profile.skills}")

    # 2. Job search (placeholder adapter)
    print("\n[2] Searching jobs (placeholder adapter)...")
    # Note: a real search would call LinkedInAdapter().search(); the placeholder
    # returns []. For demonstration, we create mock job listings
    mock_jobs = [
        JobListing(
            id="job-1",
            source="linkedin",
            title="Python Engineer",
            company="Tech Corp",
            required_skills=["python", "sql"],
            preferred_skills=["aws"],
        ),
        JobListing(
            id="job-2",
            source="linkedin",
            title="ML Engineer",
            company="AI Labs",
            required_skills=["python", "aws"],
            preferred_skills=["sql"],
        ),
        JobListing(
            id="job-3",
            source="indeed",
            title="DevOps Engineer",
            company="Cloud Inc",
            required_skills=["kubernetes", "aws"],
        ),
    ]
    print(f"    Found {len(mock_jobs)} mock jobs")

    # 3. Normalization (already JobListing objects)
    print("\n[3] Normalized to JobListing schema...")
    for job in mock_jobs:
        print(f"    - {job.title} at {job.company}")

    # 4. Deduplication
    print("\n[4] Deduplicating...")
    unique_jobs = deduplicate(mock_jobs)
    print(f"    After dedup: {len(unique_jobs)} unique jobs")

    # 5. Hybrid matching
    print("\n[5] Running hybrid match engine...")
    results = []
    for job in unique_jobs:
        # semantic_score=None -> degraded mode (demo runs without embeddings;
        # the live pipeline passes the Chroma similarity instead).
        match_result = calculate_match(job, profile, semantic_score=None)
        results.append(
            (match_result.overall_score, job.title, job.company, match_result.explanation)
        )
        print(f"    {job.title} @ {job.company}: {match_result.overall_score:.1f}/100")

    # 6. Ranking (top 10 / explanation)
    print("\n[6] Ranking results (top matches)...")
    results.sort(key=lambda x: x[0], reverse=True)
    for score, title, company, explanation in results[:3]:
        print(
            f"    #{results.index((score, title, company, explanation)) + 1} {title} @ {company} — Score: {score:.1f}"
        )
        print(f"        Explanation: {explanation[:80]}...")

    print("\n" + "=" * 60)
    print("MILESTONE 1 COMPLETE")
    print(
        "Pipeline: Resume → Profile → Search → Normalize → Deduplicate → Match → Rank → Explanation"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
