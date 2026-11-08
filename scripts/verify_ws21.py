"""WS-21 live acceptance — run against a running backend.

One command, one verdict. The script registers a real account over the real
cookie flow, uploads a real résumé, confirms target roles, runs the real
corpus search, and reads the ranked match view — so every claim in the
WS-21 report that can be checked over HTTP is checked over HTTP, not only
in the unit suite.

Usage (from the repo root, with the API running)::

    env/Scripts/python.exe scripts/verify_ws21.py

Exit code 0 means every check passed.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
RESUME = REPO / "tests" / "evaluation" / "golden" / "resumes" / "lena_fischer_frontend.txt"
BASE_URL = "http://127.0.0.1:8000"

TARGET_ROLES = ["Web Developer", "Frontend Developer", "Full-Stack Developer"]


class Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, bool(ok), detail))
        suffix = f" — {detail}" if detail else ""
        print(f"  [{'ok  ' if ok else 'FAIL'}] {name}{suffix}")


def main() -> int:
    report = Report()
    stamp = str(int(time.time()))
    email = f"ws21-verify-{stamp}@example.com"
    password = "a-long-enough-password"

    with httpx.Client(base_url=BASE_URL, timeout=900.0) as client:
        # -- the server is the WS-21 code ----------------------------------
        health = client.get("/api/health")
        report.check("health", health.status_code == 200)
        schema = client.get("/openapi.json").json()
        match_fields = schema["components"]["schemas"]["JobMatchResult"]["properties"]
        report.check(
            "the match schema carries the role fields",
            {"role_score", "role_family", "role_capped", "role_targets"} <= set(match_fields),
        )
        parameters = schema["paths"]["/api/profiles/{profile_id}/matches"]["get"]["parameters"]
        param_names = {parameter["name"] for parameter in parameters}
        report.check("the matches route exposes ranked + limit", {"ranked", "limit"} <= param_names)

        # -- a real account, the real flow ---------------------------------
        registered = client.post("/api/auth/register", json={"email": email, "password": password})
        report.check(
            "registration",
            registered.status_code in (200, 201),
            str(registered.status_code),
        )
        login = client.post(
            "/api/auth/cookie/login",
            data={"username": email, "password": password},
        )
        report.check("cookie login", login.status_code == 204, str(login.status_code))
        csrf = client.cookies.get("aja_csrf")
        headers = {"X-CSRF-Token": csrf} if csrf else {}
        me = client.get("/api/auth/me")
        report.check(
            "identity is the fresh account",
            me.status_code == 200 and me.json().get("email") == email,
        )

        # -- a profile from a real r\u00e9sum\u00e9 -------------------------------------
        with RESUME.open("rb") as handle:
            uploaded = client.post(
                "/api/resumes",
                files={"file": (RESUME.name, handle, "text/plain")},
                headers=headers,
            )
        report.check(
            "r\u00e9sum\u00e9 upload", uploaded.status_code == 200, str(uploaded.status_code)
        )
        if uploaded.status_code != 200:
            return _finish(report)
        profile_id = uploaded.json()["profile_id"]

        # -- confirmed target roles round-trip (Part 2.3) ------------------
        body = {
            "professional": {},
            "preferences": {"target_roles": TARGET_ROLES},
            "answers": {
                "work_authorization": {},
                "compensation": {},
                "notice": {},
            },
            "confirmed_fields": ["preferences.target_roles"],
        }
        saved = client.put(
            f"/api/profiles/{profile_id}/application-profile",
            json=body,
            headers=headers,
        )
        report.check("target roles save", saved.status_code == 200, str(saved.status_code))
        stored = client.get(f"/api/profiles/{profile_id}/application-profile").json()[
            "application_profile"
        ]
        report.check(
            "target roles round-trip",
            stored["preferences"]["target_roles"] == TARGET_ROLES,
        )
        report.check(
            "the confirmed marker round-trips",
            "preferences.target_roles" in stored.get("confirmed_fields", []),
        )

        # -- the search: the named unrelated roles must be gone ------------
        search = client.post(
            "/api/jobs/search",
            json={"profile_id": profile_id, "top_n": 10},
            headers=headers,
        )
        report.check("corpus search", search.status_code == 200, str(search.status_code))
        if search.status_code != 200:
            return _finish(report)
        payload = search.json()
        results = payload["results"]
        titles = [pair["job"]["title"] for pair in results]
        capped = [pair["job"]["title"] for pair in results if pair["match"].get("role_capped")]
        report.check("no role-capped listing in the top 10", not capped, "; ".join(capped[:3]))
        banned = ("Physical Design Engineer", "Senior Analyst")
        offending = [title for title in titles if any(name in title for name in banned)]
        report.check("the named unrelated listings are absent", not offending, "; ".join(offending))
        web_roles = [
            pair for pair in results if pair["match"].get("role_family") == "web_development"
        ]
        report.check(
            "web-development roles dominate the top", len(web_roles) >= 4, f"{len(web_roles)}/10"
        )
        report.check(
            "the semantic channel was available",
            payload["stats"]["semantic_covered"] > 0,
            f"{payload['stats']['semantic_covered']}/{payload['stats']['stored']}",
        )
        print("    top 5:")
        for pair in results[:5]:
            print(
                f"      {pair['match']['overall_score']:5.1f} "
                f"{pair['match'].get('role_family') or '(unclassified)'} — "
                f"{pair['job']['title'][:52]!r}"
            )

        # -- the ranked match view (Part 5) --------------------------------
        ranked = client.get(
            f"/api/profiles/{profile_id}/matches",
            params={"ranked": "true", "limit": 5},
        )
        report.check("ranked matches endpoint", ranked.status_code == 200)
        rows = ranked.json()["matches"]
        ids = [row["job_id"] for row in rows]
        report.check("one row per job", len(ids) == len(set(ids)), str(ids))
        scores = [row["scores"].get("overall_score") for row in rows]
        numeric = [score for score in scores if isinstance(score, (int, float))]
        report.check(
            "descending overall score",
            numeric == sorted(numeric, reverse=True),
            str(scores),
        )
        report.check("limit respected", len(rows) <= 5)

    return _finish(report)


def _finish(report: Report) -> int:
    passed = sum(1 for _name, ok, _detail in report.results if ok)
    total = len(report.results)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
