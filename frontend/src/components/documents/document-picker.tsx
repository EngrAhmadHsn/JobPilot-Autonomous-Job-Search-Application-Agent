import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FileText, Upload } from "lucide-react"
import { useRef, useState } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import { Pagination } from "@/components/common/pagination"
import { EmptyState, ProgressState } from "@/components/common/progress-state"
import { Button } from "@/components/ui/button"

import { apiUrl } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { formatBytes, formatDateTime } from "@/lib/format"
import { stagger } from "@/lib/stagger"
import type { DocumentRecord } from "@/lib/api/types"

/** How many documents one page of the library shows. */
export const DOCUMENTS_PER_PAGE = 5

/**
 * The account's documents.
 *
 * One query, shared by every screen that lists them: the résumé the operator
 * uploaded and every tailored résumé the agent produced. The backend returns
 * the whole library newest first (there is no paging parameter), so the
 * console pages what it already has.
 */
export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: ({ signal }) => api.documents(signal),
  })
}

/** How a document is described in the list. */
function DocumentRow({
  document,
  index = 0,
  selected,
  onSelect,
  onUse,
}: {
  document: DocumentRecord
  index?: number
  selected: boolean
  onSelect?: () => void
  onUse?: () => void
}) {
  const content = (
    <>
      <span
        aria-hidden="true"
        className={
          "flex size-8 shrink-0 items-center justify-center rounded-lg " +
          (document.kind === "tailored"
            ? "bg-lime-soft text-forest"
            : "bg-muted text-muted-foreground")
        }
      >
        <FileText className="size-4" strokeWidth={1.7} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">
          {document.title}
        </span>
        <span className="block truncate text-xs text-muted-foreground">
          {document.kind === "tailored" ? "Tailored résumé" : "Uploaded résumé"}
          {document.size_bytes ? ` · ${formatBytes(document.size_bytes)}` : ""}
          {document.created_at
            ? ` · ${formatDateTime(document.created_at)}`
            : ""}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-4">
        {onUse ? (
          selected ? (
            // The console is reading this document right now. Saying so beats
            // a "Use" button that would do what is already true.
            <span className="text-xs font-medium text-primary">In use</span>
          ) : (
            <button
              type="button"
              onClick={onUse}
              aria-label={`Use ${document.title}`}
              className="text-xs font-medium text-primary underline underline-offset-4 transition-colors hover:text-foreground"
            >
              Use
            </button>
          )
        ) : null}
        <a
          href={apiUrl(
            `/api/documents/${encodeURIComponent(document.id)}/download`
          )}
          className="text-xs font-medium text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground"
          onClick={(event) => event.stopPropagation()}
        >
          Open
        </a>
      </span>
    </>
  )

  if (!onSelect) {
    return (
      <li
        aria-current={selected || undefined}
        {...stagger(
          index,
          "flex items-center gap-3 rounded-xl border px-3 py-2.5 " +
            (selected
              ? "border-primary bg-accent/50"
              : "border-border bg-card")
        )}
      >
        {content}
      </li>
    )
  }

  return (
    <li>
      <label
        className={
          "flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors " +
          (selected
            ? "border-primary bg-accent/50"
            : "border-border bg-card hover:border-border/80 hover:bg-accent/30")
        }
      >
        <input
          type="radio"
          name="document"
          className="sr-only"
          checked={selected}
          onChange={onSelect}
        />
        <span
          aria-hidden="true"
          className={
            "size-2 shrink-0 rounded-full border " +
            (selected
              ? "border-primary bg-primary"
              : "border-border bg-transparent")
          }
        />
        {content}
      </label>
    </li>
  )
}

/** A paged list of rows, with the counter and the page control. */
function DocumentPages({
  items,
  selectedId,
  onSelect,
  onUse,
  page,
  onPageChange,
}: {
  items: DocumentRecord[]
  selectedId?: string | null
  onSelect?: (document: DocumentRecord) => void
  onUse?: (document: DocumentRecord) => void
  page: number
  onPageChange: (page: number) => void
}) {
  const pages = Math.max(1, Math.ceil(items.length / DOCUMENTS_PER_PAGE))
  const safePage = Math.min(page, pages - 1)
  const visible = items.slice(
    safePage * DOCUMENTS_PER_PAGE,
    (safePage + 1) * DOCUMENTS_PER_PAGE
  )

  return (
    <>
      <ul className="space-y-2">
        {visible.map((document, index) => (
          <DocumentRow
            key={document.id}
            index={index}
            document={document}
            selected={selectedId === document.id}
            onSelect={onSelect ? () => onSelect(document) : undefined}
            onUse={onUse ? () => onUse(document) : undefined}
          />
        ))}
      </ul>
      <Pagination
        page={safePage}
        pageSize={DOCUMENTS_PER_PAGE}
        total={items.length}
        onPageChange={onPageChange}
        label="documents"
      />
    </>
  )
}

/**
 * The account's documents, as a list.
 *
 * `selectedId` marks the document the console is currently working with, so
 * the operator can see which one the screens are reading — the same
 * highlight the approvals picker uses.
 */
export function DocumentList({
  selectedId,
  onUse,
}: {
  /** The document the console is working with, when there is one. */
  selectedId?: string | null
  /** Called with the document the operator chose to work with. */
  onUse?: (document: DocumentRecord) => void
} = {}) {
  const documents = useDocuments()
  const [page, setPage] = useState(0)

  if (documents.isPending) {
    return <ProgressState key="documents" title="Loading your documents" />
  }

  if (documents.isError) {
    return (
      <ErrorNotice
        error={documents.error}
        onRetry={() => documents.refetch()}
      />
    )
  }

  const items = documents.data.documents
  if (items.length === 0) {
    return (
      <EmptyState
        title="No documents yet"
        description="Upload a résumé and it appears here, together with every tailored résumé the agent writes for you."
      />
    )
  }

  return (
    <DocumentPages
      items={items}
      selectedId={selectedId}
      onUse={onUse}
      page={page}
      onPageChange={setPage}
    />
  )
}

/**
 * A picker over the account's documents.
 *
 * The operator picks a document; the form carries the path the *server*
 * gave for it. The alternative — a text field for a server-side path — is
 * a request to type something the operator cannot know.
 */
export function DocumentPicker({
  value,
  onChange,
  label = "Résumé to attach",
}: {
  value: string
  onChange: (path: string) => void
  label?: string
}) {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [page, setPage] = useState(0)

  const documents = useDocuments()

  /*
    The upload selects the document it just created.

    The console cannot work out the path of the stored file — the server
    decides it — so the upload waits for the refreshed library and picks
    the new document out of it. Doing that inside the mutation (rather
    than in an effect) keeps the selection tied to the upload that caused
    it.
  */
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const result = await api.uploadResume(file)
      const { documents } = await queryClient.fetchQuery({
        queryKey: ["documents"],
        queryFn: ({ signal }) => api.documents(signal),
      })
      const document = documents.find(
        (item) => item.id === `profile-${result.profile_id}`
      )
      if (document) onChange(document.path)
      return result
    },
  })

  const items = documents.data?.documents ?? []
  const selected = items.find((document) => document.path === value)

  return (
    <div className="space-y-3">
      <span className="text-sm font-medium text-foreground">{label}</span>

      {documents.isPending ? (
        <ProgressState key="documents" title="Loading your documents" />
      ) : null}

      {documents.isError ? (
        <ErrorNotice
          error={documents.error}
          onRetry={() => documents.refetch()}
        />
      ) : null}

      {items.length === 0 && !documents.isPending ? (
        <p className="text-sm text-muted-foreground">
          You have no documents yet. Upload a résumé and it will be attached to
          this application.
        </p>
      ) : null}

      {items.length > 0 ? (
        <DocumentPages
          items={items}
          selectedId={selected?.id ?? null}
          onSelect={(document) => onChange(document.path)}
          page={page}
          onPageChange={setPage}
        />
      ) : null}

      <input
        ref={inputRef}
        type="file"
        className="sr-only"
        accept=".docx,.txt,.md"
        aria-label="Upload a résumé"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) upload.mutate(file)
        }}
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={upload.isPending}
        onClick={() => inputRef.current?.click()}
      >
        <Upload className="size-4" aria-hidden="true" />
        {upload.isPending ? "Uploading…" : "Upload a résumé"}
      </Button>

      {upload.isError ? <ErrorNotice error={upload.error} /> : null}
    </div>
  )
}