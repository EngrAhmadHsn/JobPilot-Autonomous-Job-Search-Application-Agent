import { Banner } from "@/components/common/banner"
import { PlainText } from "@/components/common/plain-text"

import type { JobSearchResponse } from "@/lib/api/types"

/*
  The banners that say what went wrong with the corpus, if anything did (WS-36).

  `degraded: true` is honest data, not an error: on an unfiltered full-corpus
  search the vector store's known `count − 1` edge case can leave part of the
  corpus without semantic vectors, so the scores are weaker than a full run's.
  The notice says what the state means and what is *not* wrong (the listings
  themselves are complete) — it never reads as a failure of the search.
*/
export function SearchBanners({ data }: { data: JobSearchResponse }) {
  const sourceErrors = Object.entries(data.source_errors)
  return (
    <div className="space-y-3">
      {data.degraded ? (
        <Banner tone="warning" title="The scoring was degraded">
          <p>
            Semantic scoring was unavailable for part of the corpus, so the
            scores below are weaker than a full run would be. The listings
            themselves are complete.
          </p>
        </Banner>
      ) : null}

      {sourceErrors.length > 0 ? (
        <Banner
          tone="warning"
          title={`${sourceErrors.length} job source(s) failed`}
        >
          <p>
            A failing source degrades the report, it does not fail the search.
            The corpus below is what the working sources returned.
          </p>
          <ul className="mt-1 list-disc pl-5">
            {sourceErrors.map(([source, message]) => (
              <li key={source}>
                <span className="font-medium">{source}</span>:{" "}
                <PlainText as="span">{message}</PlainText>
              </li>
            ))}
          </ul>
        </Banner>
      ) : null}
    </div>
  )
}
