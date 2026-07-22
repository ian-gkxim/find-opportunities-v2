"use client";

import { useCallback, useState } from "react";
import {
  useProposalNotifications,
  type SourceFailureEvent,
} from "@/components/profile-enrichment/useProposalNotifications";

// ============================================================================
// Source Failure Notifications — toast-style notices on Dashboard
// Requirements: 1.4, 3.1
//
// Listens for "source_failure_notice" WebSocket notifications pushed by the
// Profile Enrichment Worker when a public source has been unreachable for
// 3 consecutive scan cycles. Displays dismissible toast alerts.
// ============================================================================

interface SourceFailureNotice {
  id: string;
  source_label: string;
  source_url: string;
  message: string;
  timestamp: string;
}

interface SourceFailureNotificationsProps {
  /** Maximum number of notices visible at once */
  maxVisible?: number;
}

export function SourceFailureNotifications({
  maxVisible = 5,
}: SourceFailureNotificationsProps) {
  const [notices, setNotices] = useState<SourceFailureNotice[]>([]);

  const handleSourceFailure = useCallback(
    (event: SourceFailureEvent) => {
      const notice: SourceFailureNotice = {
        id: `${event.source_id}-${Date.now()}`,
        source_label: event.source_label,
        source_url: event.source_url,
        message: event.message,
        timestamp: new Date().toISOString(),
      };

      setNotices((prev) => [notice, ...prev].slice(0, maxVisible));
    },
    [maxVisible]
  );

  useProposalNotifications({
    onSourceFailure: handleSourceFailure,
  });

  const dismissNotice = useCallback((id: string) => {
    setNotices((prev) => prev.filter((n) => n.id !== id));
  }, []);

  if (notices.length === 0) {
    return null;
  }

  return (
    <div
      className="space-y-2 mt-3"
      role="log"
      aria-label="Source failure notifications"
      aria-live="polite"
    >
      {notices.map((notice) => (
        <SourceFailureCard
          key={notice.id}
          notice={notice}
          onDismiss={() => dismissNotice(notice.id)}
        />
      ))}
    </div>
  );
}

// ─── Individual Source Failure Card ──────────────────────────────────────────

interface SourceFailureCardProps {
  notice: SourceFailureNotice;
  onDismiss: () => void;
}

function SourceFailureCard({ notice, onDismiss }: SourceFailureCardProps) {
  return (
    <div
      className="rounded-lg border border-l-4 border-orange-500 border-l-orange-500 bg-orange-50 p-3 dark:bg-orange-950/20"
      role="alert"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span className="flex-shrink-0 text-sm" aria-hidden="true">
            ⚠️
          </span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-[rgb(var(--foreground))]">
              Public source unreachable
            </p>
            <p className="text-xs text-[rgb(var(--muted-foreground))] mt-0.5">
              {notice.message}
            </p>
            <a
              href={notice.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-xs text-[rgb(var(--accent))] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
              aria-label={`Check source: ${notice.source_label} (opens in new tab)`}
            >
              {notice.source_label}
            </a>
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="flex-shrink-0 rounded p-1 text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
          aria-label={`Dismiss source failure notice for ${notice.source_label}`}
        >
          <span aria-hidden="true" className="text-xs">
            ✕
          </span>
        </button>
      </div>
    </div>
  );
}
