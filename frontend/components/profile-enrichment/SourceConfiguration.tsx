"use client";

import { useState, useEffect, useCallback } from "react";

/**
 * Source Configuration UI — Manage public sources for profile enrichment.
 *
 * Allows Consultants to:
 * - View configured public sources with status (last scanned, failure count)
 * - Add new sources (type + URL + label, max 10)
 * - Delete sources with confirmation
 * - See failure notices for sources with 3+ consecutive failures
 *
 * Requirements: 1.1, 1.4
 */

// ============================================================================
// Types
// ============================================================================

export interface PublicSource {
  id: string;
  source_type: string;
  url: string;
  label: string;
  last_scanned_at: string | null;
  consecutive_failures: number;
  created_at: string;
}

interface AddSourcePayload {
  source_type: string;
  url: string;
  label: string;
}

// ============================================================================
// Constants
// ============================================================================

const SOURCE_TYPES = [
  { value: "github", label: "GitHub" },
  { value: "portfolio", label: "Portfolio" },
  { value: "google_scholar", label: "Google Scholar" },
  { value: "certification_badge", label: "Certification Badge" },
  { value: "personal_blog", label: "Personal Blog" },
  { value: "npm_pypi", label: "npm / PyPI" },
  { value: "stack_overflow", label: "Stack Overflow" },
  { value: "speaker_profile", label: "Speaker Profile" },
  { value: "other", label: "Other" },
] as const;

const MAX_SOURCES = 10;
const FAILURE_THRESHOLD = 3;

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ============================================================================
// Component
// ============================================================================

export function SourceConfiguration() {
  const [sources, setSources] = useState<PublicSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Form state
  const [formSourceType, setFormSourceType] = useState<string>("github");
  const [formUrl, setFormUrl] = useState("");
  const [formLabel, setFormLabel] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  // --------------------------------------------------------------------------
  // Data fetching
  // --------------------------------------------------------------------------

  const fetchSources = useCallback(async () => {
    try {
      setError(null);
      const response = await fetch(`${API_BASE_URL}/api/profile-enrichment/sources`, {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch sources (${response.status})`);
      }

      const data: PublicSource[] = await response.json();
      setSources(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sources");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSources();
  }, [fetchSources]);

  // --------------------------------------------------------------------------
  // Actions
  // --------------------------------------------------------------------------

  const handleAddSource = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!formUrl.trim()) {
      setFormError("URL is required");
      return;
    }

    if (!formLabel.trim()) {
      setFormError("Label is required");
      return;
    }

    if (sources.length >= MAX_SOURCES) {
      setFormError(`Maximum of ${MAX_SOURCES} sources allowed`);
      return;
    }

    const payload: AddSourcePayload = {
      source_type: formSourceType,
      url: formUrl.trim(),
      label: formLabel.trim(),
    };

    setSubmitting(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/profile-enrichment/sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(
          errorData?.detail || `Failed to add source (${response.status})`
        );
      }

      // Reset form and refresh
      setFormSourceType("github");
      setFormUrl("");
      setFormLabel("");
      setShowAddForm(false);
      await fetchSources();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to add source");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteSource = async (sourceId: string) => {
    setSubmitting(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/profile-enrichment/sources/${sourceId}`,
        { method: "DELETE", headers: { "Content-Type": "application/json" } }
      );

      if (!response.ok) {
        throw new Error(`Failed to delete source (${response.status})`);
      }

      setDeleteConfirmId(null);
      await fetchSources();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete source");
    } finally {
      setSubmitting(false);
    }
  };

  // --------------------------------------------------------------------------
  // Helpers
  // --------------------------------------------------------------------------

  const getSourceTypeLabel = (type: string): string => {
    return SOURCE_TYPES.find((st) => st.value === type)?.label ?? type;
  };

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return "Never";
    const date = new Date(dateStr);
    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  const hasFailureNotice = (source: PublicSource): boolean => {
    return source.consecutive_failures >= FAILURE_THRESHOLD;
  };

  // --------------------------------------------------------------------------
  // Render
  // --------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="card" role="status" aria-label="Loading sources">
        <div className="animate-pulse space-y-3">
          <div className="h-5 w-48 rounded bg-[rgb(var(--muted))]" />
          <div className="h-4 w-full rounded bg-[rgb(var(--muted))]" />
          <div className="h-4 w-3/4 rounded bg-[rgb(var(--muted))]" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-[rgb(var(--foreground))]">
            Public Sources
          </h3>
          <p className="mt-0.5 text-sm text-[rgb(var(--muted-foreground))]">
            Configure public URLs for profile enrichment scanning ({sources.length}/{MAX_SOURCES})
          </p>
        </div>
        {sources.length < MAX_SOURCES && (
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="min-h-[44px] rounded-lg bg-[rgb(var(--accent))] px-4 py-2 text-sm font-medium text-[rgb(var(--accent-foreground))] transition-colors hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
            aria-expanded={showAddForm}
            aria-controls="add-source-form"
          >
            {showAddForm ? "Cancel" : "Add Source"}
          </button>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* Add source form */}
      {showAddForm && (
        <form
          id="add-source-form"
          onSubmit={handleAddSource}
          className="card space-y-4"
          aria-label="Add new source"
        >
          <h4 className="text-sm font-medium text-[rgb(var(--foreground))]">
            Add New Source
          </h4>

          {formError && (
            <div
              className="rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400"
              role="alert"
            >
              {formError}
            </div>
          )}

          <div className="grid gap-4 tablet:grid-cols-3">
            {/* Source type selector */}
            <div>
              <label
                htmlFor="source-type"
                className="block text-sm font-medium text-[rgb(var(--foreground))]"
              >
                Source Type
              </label>
              <select
                id="source-type"
                value={formSourceType}
                onChange={(e) => setFormSourceType(e.target.value)}
                className="mt-1 min-h-[44px] w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--card))] px-3 py-2 text-sm text-[rgb(var(--foreground))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
              >
                {SOURCE_TYPES.map((st) => (
                  <option key={st.value} value={st.value}>
                    {st.label}
                  </option>
                ))}
              </select>
            </div>

            {/* URL input */}
            <div>
              <label
                htmlFor="source-url"
                className="block text-sm font-medium text-[rgb(var(--foreground))]"
              >
                URL
              </label>
              <input
                id="source-url"
                type="url"
                value={formUrl}
                onChange={(e) => setFormUrl(e.target.value)}
                placeholder="https://github.com/username"
                required
                className="mt-1 min-h-[44px] w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--card))] px-3 py-2 text-sm text-[rgb(var(--foreground))] placeholder:text-[rgb(var(--muted-foreground))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
              />
            </div>

            {/* Label input */}
            <div>
              <label
                htmlFor="source-label"
                className="block text-sm font-medium text-[rgb(var(--foreground))]"
              >
                Label
              </label>
              <input
                id="source-label"
                type="text"
                value={formLabel}
                onChange={(e) => setFormLabel(e.target.value)}
                placeholder="My GitHub Profile"
                maxLength={100}
                required
                className="mt-1 min-h-[44px] w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--card))] px-3 py-2 text-sm text-[rgb(var(--foreground))] placeholder:text-[rgb(var(--muted-foreground))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={submitting}
              className="min-h-[44px] rounded-lg bg-[rgb(var(--accent))] px-4 py-2 text-sm font-medium text-[rgb(var(--accent-foreground))] transition-colors hover:opacity-90 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
            >
              {submitting ? "Adding…" : "Add Source"}
            </button>
          </div>
        </form>
      )}

      {/* Source list */}
      {sources.length === 0 ? (
        <div className="card text-center">
          <p className="text-sm text-[rgb(var(--muted-foreground))]">
            No sources configured yet. Add a public source to start profile enrichment scanning.
          </p>
        </div>
      ) : (
        <ul className="space-y-3" aria-label="Configured sources">
          {sources.map((source) => (
            <li
              key={source.id}
              className={`card flex items-start justify-between gap-4 ${
                hasFailureNotice(source)
                  ? "border-yellow-400 dark:border-yellow-600"
                  : ""
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-[rgb(var(--foreground))]">
                    {source.label}
                  </span>
                  <span className="rounded-full bg-[rgb(var(--muted))] px-2 py-0.5 text-xs text-[rgb(var(--muted-foreground))]">
                    {getSourceTypeLabel(source.source_type)}
                  </span>
                </div>

                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-0.5 block truncate text-xs text-[rgb(var(--accent))] hover:underline"
                >
                  {source.url}
                </a>

                <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-[rgb(var(--muted-foreground))]">
                  <span>Last scanned: {formatDate(source.last_scanned_at)}</span>

                  {source.consecutive_failures > 0 && (
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${
                        hasFailureNotice(source)
                          ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
                          : "bg-[rgb(var(--muted))] text-[rgb(var(--muted-foreground))]"
                      }`}
                    >
                      {source.consecutive_failures} failure{source.consecutive_failures !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>

                {/* Failure notice for 3+ consecutive failures */}
                {hasFailureNotice(source) && (
                  <div
                    className="mt-2 rounded-md bg-yellow-50 p-2 text-xs text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400"
                    role="alert"
                  >
                    ⚠️ This source has failed for {source.consecutive_failures} consecutive
                    cycles. Please verify the URL is still accessible.
                  </div>
                )}
              </div>

              {/* Delete button / confirmation */}
              <div className="flex-shrink-0">
                {deleteConfirmId === source.id ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleDeleteSource(source.id)}
                      disabled={submitting}
                      className="min-h-[44px] rounded-lg bg-red-600 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
                      aria-label={`Confirm delete ${source.label}`}
                    >
                      {submitting ? "Deleting…" : "Confirm"}
                    </button>
                    <button
                      onClick={() => setDeleteConfirmId(null)}
                      className="min-h-[44px] rounded-lg border border-[rgb(var(--border))] px-3 py-2 text-xs font-medium text-[rgb(var(--muted-foreground))] transition-colors hover:bg-[rgb(var(--muted))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
                      aria-label="Cancel delete"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setDeleteConfirmId(source.id)}
                    className="min-h-[44px] rounded-lg border border-[rgb(var(--border))] px-3 py-2 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
                    aria-label={`Delete ${source.label}`}
                  >
                    Delete
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
