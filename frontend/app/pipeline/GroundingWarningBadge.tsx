"use client";

import { useEffect, useState } from "react";

// ============================================================================
// Grounding Warning Badge — displays on pipeline records with partially_grounded claims
// Requirements: 3.4
//
// Calls PipelineGateService.get_warning_badge() via the API and displays a
// warning badge when a pipeline record has partially_grounded claims but no
// ungrounded claims (pipeline can advance with warning).
// ============================================================================

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface GroundingWarningBadgeProps {
  /** Pipeline record ID to check for warning badge */
  pipelineRecordId: string;
  /** Optional: skip the API call and use a pre-fetched value */
  showWarning?: boolean;
  /** Optional: compact variant for inline use */
  compact?: boolean;
}

/**
 * Warning badge indicator for pipeline records with partially_grounded claims.
 *
 * When partially_grounded_count > 0 and ungrounded_count == 0, the pipeline
 * can advance but should display this badge to indicate some claims are
 * supported but imprecise.
 *
 * Requirements: 3.4
 */
export function GroundingWarningBadge({
  pipelineRecordId,
  showWarning: showWarningProp,
  compact = false,
}: GroundingWarningBadgeProps) {
  const [shouldShow, setShouldShow] = useState<boolean>(
    showWarningProp ?? false
  );
  const [loading, setLoading] = useState<boolean>(showWarningProp === undefined);

  useEffect(() => {
    // If the prop is explicitly provided, use it directly
    if (showWarningProp !== undefined) {
      setShouldShow(showWarningProp);
      setLoading(false);
      return;
    }

    // Otherwise fetch from the API
    let cancelled = false;

    async function fetchWarningBadge() {
      try {
        const response = await fetch(
          `${API_BASE}/api/grounding/reports/${pipelineRecordId}`,
          {
            method: "GET",
            headers: { "Content-Type": "application/json" },
            signal: AbortSignal.timeout(5000),
          }
        );

        if (!response.ok) {
          // No report or error — no badge
          if (!cancelled) setShouldShow(false);
          return;
        }

        const report = await response.json();
        // Warning badge logic: partially_grounded > 0 AND ungrounded == 0
        const hasWarning =
          report.partially_grounded_count > 0 &&
          report.ungrounded_count === 0;

        if (!cancelled) setShouldShow(hasWarning);
      } catch {
        // Network error or timeout — don't show badge
        if (!cancelled) setShouldShow(false);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchWarningBadge();

    return () => {
      cancelled = true;
    };
  }, [pipelineRecordId, showWarningProp]);

  if (loading || !shouldShow) {
    return null;
  }

  if (compact) {
    return (
      <span
        className="inline-flex items-center rounded-full bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
        title="Some claims are partially grounded — supported but imprecise"
        role="status"
        aria-label="Partially grounded claims warning"
      >
        ⚠
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
      role="status"
      aria-label="Partially grounded claims warning"
    >
      <span aria-hidden="true">⚠️</span>
      <span>Partially grounded</span>
    </span>
  );
}
