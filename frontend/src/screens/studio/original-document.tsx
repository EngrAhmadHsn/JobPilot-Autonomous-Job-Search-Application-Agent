import { PlainText } from "@/components/common/plain-text"

import type { CandidateProfile } from "@/lib/api/types"

/*
  The "Original" tab of the Resume Studio (WS-42, design node `16:82`'s
  second pill): the candidate's own résumé, exactly as the parser read it —
  the untouched source every tailored claim is checked against.

  This is a reading of the parsed profile, not the binary file; the caption
  says so, because claiming to show "the file" would overpromise. The
  document canvas styling matches the Inline diff tab so the two read as
  the same paper.
*/

/** A section heading on the paper: `13/600`, forest, uppercase. */
function DocSectionLabel({ children }: { children: string }) {
  return (
    <h3 className="text-[13px] font-semibold uppercase leading-[19px] text-primary">
      {children}
    </h3>
  )
}

export function OriginalDocument({ profile }: { profile: CandidateProfile }) {
  const experience = profile.experience ?? []
  const projects = profile.projects ?? []
  const skills = profile.skills ?? []

  return (
    <article className="mx-auto flex w-full max-w-[869px] flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-[30px]">
      <h2 className="text-[22px] font-semibold uppercase leading-8 text-primary">
        Original résumé
      </h2>
      <p className="text-xs leading-[17px] text-muted-foreground">
        As the parser read your uploaded file — the delivered file is fixed,
        and this is the source every tailored claim is checked against.
      </p>
      <div className="h-px w-full shrink-0 bg-border-surface" aria-hidden />

      {profile.summary ? (
        <section className="min-w-0 space-y-2.5">
          <DocSectionLabel>Professional summary</DocSectionLabel>
          <PlainText className="text-sm leading-relaxed">
            {profile.summary}
          </PlainText>
        </section>
      ) : null}

      {skills.length > 0 ? (
        <section className="min-w-0 space-y-2.5">
          <DocSectionLabel>Skills</DocSectionLabel>
          <div className="flex flex-wrap items-center gap-2">
            {skills.map((skill) => (
              <span
                key={skill}
                className="inline-flex items-center rounded-[6px] bg-muted px-2.5 py-1 text-[11px] font-semibold text-foreground"
              >
                {skill}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {experience.length > 0 ? (
        <section className="min-w-0 space-y-2.5">
          <DocSectionLabel>Experience</DocSectionLabel>
          <div className="space-y-5">
            {experience.map((entry, index) => (
              <div
                key={`original-experience-${index}`}
                className="min-w-0 space-y-2"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-[13px] font-semibold text-primary">
                    {[entry.title, entry.company].filter(Boolean).join(" — ")}
                  </p>
                  {entry.dates ? (
                    <p className="text-xs text-muted-foreground tabular-nums">
                      {entry.dates}
                    </p>
                  ) : null}
                </div>
                <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
                  {(entry.bullets ?? []).map((bullet, bulletIndex) => (
                    <li key={`original-bullet-${index}-${bulletIndex}`}>
                      <PlainText as="span" className="text-sm">
                        {bullet}
                      </PlainText>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {projects.length > 0 ? (
        <section className="min-w-0 space-y-2.5">
          <DocSectionLabel>Projects</DocSectionLabel>
          <div className="space-y-4">
            {projects.map((project, index) => (
              <div
                key={`original-project-${index}`}
                className="min-w-0 space-y-1"
              >
                <p className="text-[13px] font-semibold text-primary">
                  {project.name}
                </p>
                {project.subtitle ? (
                  <p className="text-xs text-muted-foreground">
                    {project.subtitle}
                  </p>
                ) : null}
                <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
                  {(project.bullets ?? []).map((bullet, bulletIndex) => (
                    <li key={`original-project-bullet-${index}-${bulletIndex}`}>
                      <PlainText as="span" className="text-sm">
                        {bullet}
                      </PlainText>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </article>
  )
}
