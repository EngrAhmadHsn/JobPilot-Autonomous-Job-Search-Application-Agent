
import httpx


def main():
    url = "http://127.0.0.1:8010/api/jobs/search"
    payload = {"profile_id": "efc2ac94359b", "top_n": 10}
    print(f"POST {url} with {payload}...")
    r = httpx.post(url, json=payload, timeout=120)
    print("HTTP Status:", r.status_code)
    data = r.json()
    print("Degraded:", data.get("degraded"))
    print("Stored listings considered:", data.get("stats", {}).get("stored"))
    print("Source errors:", data.get("source_errors"))
    print("\n--- TOP 10 MATCHES ---")
    for i, res in enumerate(data.get("results", [])):
        job = res["job"]
        m = res["match"]
        print(f"#{i+1}: {job['title']} @ {job['company']}")
        print(f"    Overall: {m['overall_score']:.1f} | Semantic: {m['semantic_score']:.1f} | Skills: {m['skill_score']:.1f} | Location: {m['location_score']:.1f}")
        print(f"    Matched Skills: {m['matched_requirements']}")
        print(f"    Explanation: {m['explanation']}")

if __name__ == "__main__":
    main()
