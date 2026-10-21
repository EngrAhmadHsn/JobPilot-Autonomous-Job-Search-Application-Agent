import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import { PlainText } from "@/components/common/plain-text"
import { SectionTitle } from "@/components/common/field-list"
import type { CandidateProfile } from "@/lib/api/types"

/**
 * The parsed profile, in sections.
 *
 * Everything the parser found is shown, including the empty parts: a screen
 * that silently omits "no certifications" would leave the operator
 * guessing whether the parser looked and found nothing, or never looked.
 * The values are the parser's output and are rendered as plain text.
 */
export function ProfileView({ profile }: { profile: CandidateProfile }) {
  const info = profile.personal_information
  const preferences = profile.work_preferences

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Personal information</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          <p>
            <span className="font-medium">{info.name || "—"}</span>
            {info.title ? (
              <span className="text-muted-foreground"> · {info.title}</span>
            ) : null}
          </p>
          <p className="text-muted-foreground">
            {info.email || "No email parsed"}
          </p>
          <p className="text-muted-foreground">
            {info.phone || "No phone parsed"}
          </p>
          <p className="text-muted-foreground">
            {info.location || "No location parsed"}
          </p>
          {info.website ? (
            <p className="break-all text-muted-foreground">{info.website}</p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Summary</CardTitle>
        </CardHeader>
        <CardContent>
          {profile.summary ? (
            <PlainText>{profile.summary}</PlainText>
          ) : (
            <p className="text-sm text-muted-foreground">
              The parser found no summary.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Skills ({profile.skills.length})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {profile.skills.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              The parser found no skills.
            </p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {profile.skills.map((skill) => (
                <li
                  key={skill}
                  className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs"
                >
                  {skill}
                </li>
              ))}
            </ul>
          )}
          {Object.keys(profile.skill_categories).length > 0 ? (
            <div className="space-y-1">
              <SectionTitle>Categories</SectionTitle>
              <dl className="space-y-1 text-sm">
                {Object.entries(profile.skill_categories).map(
                  ([category, skills]) => (
                    <div
                      key={category}
                      className="grid grid-cols-[10rem_1fr] gap-2"
                    >
                      <dt className="text-muted-foreground">{category}</dt>
                      <dd>{skills.join(", ") || "—"}</dd>
                    </div>
                  )
                )}
              </dl>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Experience ({profile.experience.length})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {profile.experience.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              The parser found no experience entries.
            </p>
          ) : (
            profile.experience.map((entry, index) => (
              <div
                key={`${entry.title}-${entry.company}-${index}`}
                className="text-sm"
              >
                <p className="font-medium">
                  {entry.title || "Untitled role"}
                  {entry.company ? ` · ${entry.company}` : ""}
                </p>
                {entry.dates ? (
                  <p className="text-xs text-muted-foreground">{entry.dates}</p>
                ) : null}
                {entry.bullets.length > 0 ? (
                  <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                    {entry.bullets.map((bullet, bulletIndex) => (
                      <li key={bulletIndex}>
                        <PlainText as="span">{bullet}</PlainText>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Projects ({profile.projects.length})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {profile.projects.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              The parser found no projects.
            </p>
          ) : (
            profile.projects.map((project, index) => (
              <div key={`${project.name}-${index}`} className="text-sm">
                <p className="font-medium">{project.name}</p>
                {project.subtitle ? (
                  <p className="text-xs text-muted-foreground">
                    {project.subtitle}
                  </p>
                ) : null}
                {project.tech ? (
                  <p className="text-xs text-muted-foreground">
                    {project.tech}
                  </p>
                ) : null}
                {project.bullets.length > 0 ? (
                  <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                    {project.bullets.map((bullet, bulletIndex) => (
                      <li key={bulletIndex}>
                        <PlainText as="span">{bullet}</PlainText>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Education ({profile.education.length})</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {profile.education.length === 0 ? (
            <p className="text-muted-foreground">
              The parser found no education entries.
            </p>
          ) : (
            profile.education.map((entry, index) => (
              <div key={`${entry.degree}-${index}`}>
                <p className="font-medium">
                  {entry.degree || "Unnamed qualification"}
                  {entry.institution ? ` · ${entry.institution}` : ""}
                </p>
                {entry.dates ? (
                  <p className="text-xs text-muted-foreground">{entry.dates}</p>
                ) : null}
                {entry.gpa ? (
                  <p className="text-xs text-muted-foreground">
                    GPA {entry.gpa}
                  </p>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Work preferences</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          <p>
            <span className="text-muted-foreground">Remote:</span>{" "}
            {preferences.remote_preference || "not stated"}
          </p>
          <p>
            <span className="text-muted-foreground">Locations:</span>{" "}
            {preferences.preferred_locations.join(", ") || "not stated"}
          </p>
          <p>
            <span className="text-muted-foreground">Employment types:</span>{" "}
            {preferences.employment_types.join(", ") || "not stated"}
          </p>
          <p>
            <span className="text-muted-foreground">Minimum salary:</span>{" "}
            {preferences.min_salary || "not stated"}
          </p>
          <p>
            <span className="text-muted-foreground">Work authorization:</span>{" "}
            {preferences.work_authorization || "not stated"}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Certifications and achievements</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div>
            <p className="font-medium">
              Certifications ({profile.certifications.length})
            </p>
            {profile.certifications.length === 0 ? (
              <p className="text-muted-foreground">None.</p>
            ) : (
              <ul className="list-disc pl-5 text-muted-foreground">
                {profile.certifications.map((item, index) => (
                  <li key={index}>
                    <PlainText as="span">{item}</PlainText>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <p className="font-medium">
              Achievements ({profile.achievements.length})
            </p>
            {profile.achievements.length === 0 ? (
              <p className="text-muted-foreground">None.</p>
            ) : (
              <ul className="list-disc pl-5 text-muted-foreground">
                {profile.achievements.map((item, index) => (
                  <li key={index}>
                    <PlainText as="span">{item}</PlainText>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
