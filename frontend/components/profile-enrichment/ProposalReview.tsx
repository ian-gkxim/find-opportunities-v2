"use client";

import { useState, useEffect, useCallback } from "react";
import { useProposalNotifications } from "./useProposalNotifications";

/**
 * Proposal Review UI Component
 *
 * Displays competency proposals in the Understand stage, allowing the
 * Consultant to accept (with optional edit), reject, or bulk-manage proposals.
 * Auto-refreshes when new proposals arrive via WebSocket.
 *
 * Requirements: 1.4, 3.1
 */

// ============================================================================
// Types
// ============================================================================

export type ProposalStatus = "pending" | "accepted" | "rejected";
export type ProposalConfidence = "strong" | "inferred";

export interface CompetencyProposal {
  id: string;
  category: string;
  name: string;
  evidence_summary: string;
  confidence: ProposalConfidence;
  source_url: string;
  source_label: string;
  status: ProposalStatus;
  created_at: string;
}

interface BulkActionResult {
  processed: number;
  failed: number;
}

// ============================================================================
// API helpers
// ============================================================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchProposals(status: ProposalStatus): Promise<CompetencyProposal[]> {
  const response = await fetch(
    `${API_BASE_URL}/api/profile-enrichment/proposals?status=${status}`,
    {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(10000),
    }
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch proposals: ${response.status}`);
  }
  return response.json();
}

async function acceptProposal(
  proposalId: string,
  editedContent?: string
): Promise<void> {
  const body = editedContent ? { edited_content: editedContent } : {};
  const response = await fetch(
    `${API_BASE_URL}/api/profile-enrichment/proposals/${proposalId}/accept`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!response.ok) {
    throw new Error(`Failed to accept proposal: ${response.status}`);
  }
}

async function rejectProposal(proposalId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/profile-enrichment/proposals/${proposalId}/reject`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );
  if (!response.ok) {
    throw new Error(`Failed to reject proposal: ${response.status}`);
  }
}

async function bulkAction(
  proposalIds: string[],
  action: "accept" | "reject"
): Promise<BulkActionResult> {
  const response = await fetch(
    `${API_BASE_URL}/api/profile-enrichment/proposals/bulk`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposal_ids: proposalIds, action }),
    }
  );
  if (!response.ok) {
    throw new Error(`Bulk action failed: ${response.status}`);
  }
  return response.json();
}

// ============================================================================
// Sub-components
// ============================================================================

function ConfidenceBadge({ confidence }: { confidence: ProposalConfidence }) {
  const styles =
    confidence === "strong"
      ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
      : "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300";

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles}`}
      aria-label={`Confidence: ${confidence}`}
    >
      {confidence}
    </span>
  );
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-[rgb(var(--muted))] px-2.5 py-0.5 text-xs font-medium text-[rgb(var(--muted-foreground))]">
      {category}
    </span>
  );
}

function StatusFilterTabs({
  activeStatus,
  onStatusChange,
}: {
  activeStatus: ProposalStatus;
  onStatusChange: (status: ProposalStatus) => void;
}) {
  const statuses: { value: ProposalStatus; label: string }[] = [
    { value: "pending", label: "Pending" },
    { value: "accepted", label: "Accepted" },
    { value: "rejected", label: "Rejected" },
  ];

  return (
    <nav aria-label="Proposal status filter" role="tablist">
      <div className="flex rounded-lg border border-[rgb(var(--border))] overflow-hidden w-fit">
        {statuses.map((s) => (
          <button
            key={s.value}
            role="tab"
            aria-selected={activeStatus === s.value}
            onClick={() => onStatusChange(s.value)}
            className={`min-h-[44px] px-4 py-2 text-sm font-medium transition-colors
              focus-visible:outline-2 focus-visible:outline-offset-2
              focus-visible:outline-[rgb(var(--focus-ring))]
              ${
                activeStatus === s.value
                  ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                  : "text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))]"
              }`}
          >
            {s.label}
          </button>
        ))}
      </div>
    </nav>
  );
}

// ============================================================================
// Proposal Card (with inline edit for accept)
// ============================================================================

function ProposalCard({
  proposal,
  isSelected,
  onToggleSelect,
  onAccept,
  onReject,
  isPending,
}: {
  proposal: CompetencyProposal;
  isSelected: boolean;
  onToggleSelect: (id: string) => void;
  onAccept: (id: string, editedContent?: string) => void;
  onReject: (id: string) => void;
  isPending: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedName, setEditedName] = useState(proposal.name);
  const [isProcessing, setIsProcessing] = useState(false);

  const handleAcceptClick = () => {
    if (!isEditing) {
      // Enter edit mode (edit-then-accept flow)
      setIsEditing(true);
    }
  };

  const handleConfirmAccept = async () => {
    setIsProcessing(true);
    const edited = editedName !== proposal.name ? editedName : undefined;
    await onAccept(proposal.id, edited);
    setIsProcessing(false);
    setIsEditing(false);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditedName(proposal.name);
  };

  const handleReject = async () => {
    setIsProcessing(true);
    await onReject(proposal.id);
    setIsProcessing(false);
  };

  return (
    <div
      className="card flex flex-col gap-3"
      role="article"
      aria-label={`Proposal: ${proposal.name}`}
    >
      <div className="flex items-start gap-3">
        {/* Checkbox for bulk selection (only for pending) */}
        {isPending && (
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => onToggleSelect(proposal.id)}
            aria-label={`Select proposal: ${proposal.name}`}
            className="mt-1 h-4 w-4 rounded border-[rgb(var(--border))] text-[rgb(var(--accent))] focus:ring-[rgb(var(--focus-ring))]"
          />
        )}

        <div className="flex-1 min-w-0">
          {/* Header row: name + badges */}
          <div className="flex flex-wrap items-center gap-2">
            {isEditing ? (
              <input
                type="text"
                value={editedName}
                onChange={(e) => setEditedName(e.target.value)}
                className="flex-1 min-w-0 rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--background))] px-3 py-1.5 text-sm text-[rgb(var(--foreground))] focus:outline-none focus:ring-2 focus:ring-[rgb(var(--focus-ring))]"
                aria-label="Edit proposal name"
                autoFocus
              />
            ) : (
              <span className="text-sm font-semibold text-[rgb(var(--foreground))]">
                {proposal.name}
              </span>
            )}
            <CategoryBadge category={proposal.category} />
            <ConfidenceBadge confidence={proposal.confidence} />
          </div>

          {/* Evidence summary */}
          <p className="mt-1.5 text-sm text-[rgb(var(--muted-foreground))]">
            {proposal.evidence_summary}
          </p>

          {/* Source link */}
          <a
            href={proposal.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-xs text-[rgb(var(--accent))] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
            aria-label={`Source: ${proposal.source_label} (opens in new tab)`}
          >
            <svg
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
              />
            </svg>
            {proposal.source_label}
          </a>
        </div>
      </div>

      {/* Action buttons (only for pending proposals) */}
      {isPending && (
        <div className="flex items-center gap-2 pt-2 border-t border-[rgb(var(--border))]">
          {isEditing ? (
            <>
              <button
                onClick={handleConfirmAccept}
                disabled={isProcessing || !editedName.trim()}
                className="min-h-[44px] rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
                aria-label="Confirm accept"
              >
                {isProcessing ? "Accepting…" : "Confirm Accept"}
              </button>
              <button
                onClick={handleCancelEdit}
                disabled={isProcessing}
                className="min-h-[44px] rounded-lg border border-[rgb(var(--border))] px-4 py-2 text-sm font-medium text-[rgb(var(--muted-foreground))] transition-colors hover:bg-[rgb(var(--muted))] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
                aria-label="Cancel edit"
              >
                Cancel
              </button>
            </>
          ) : (
            <>
              <button
                onClick={handleAcceptClick}
                disabled={isProcessing}
                className="min-h-[44px] rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
                aria-label={`Accept proposal: ${proposal.name}`}
              >
                Accept
              </button>
              <button
                onClick={handleReject}
                disabled={isProcessing}
                className="min-h-[44px] rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
                aria-label={`Reject proposal: ${proposal.name}`}
              >
                {isProcessing ? "Rejecting…" : "Reject"}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Main Proposal Review Component
// ============================================================================

export function ProposalReview() {
  const [status, setStatus] = useState<ProposalStatus>("pending");
  const [proposals, setProposals] = useState<CompetencyProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkProcessing, setBulkProcessing] = useState(false);

  const MAX_BULK_SIZE = 50;

  const loadProposals = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSelectedIds(new Set());
    try {
      const data = await fetchProposals(status);
      setProposals(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load proposals");
      setProposals([]);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    loadProposals();
  }, [loadProposals]);

  // Subscribe to WebSocket for real-time proposal updates (Requirement 1.4)
  useProposalNotifications({
    onNewProposals: useCallback(() => {
      // Auto-refresh when viewing pending proposals
      if (status === "pending") {
        loadProposals();
      }
    }, [status, loadProposals]),
  });

  // Selection handlers
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < MAX_BULK_SIZE) {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === proposals.length) {
      setSelectedIds(new Set());
    } else {
      const allIds = proposals.slice(0, MAX_BULK_SIZE).map((p) => p.id);
      setSelectedIds(new Set(allIds));
    }
  };

  // Action handlers
  const handleAccept = async (id: string, editedContent?: string) => {
    try {
      await acceptProposal(id, editedContent);
      setProposals((prev) => prev.filter((p) => p.id !== id));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to accept proposal");
    }
  };

  const handleReject = async (id: string) => {
    try {
      await rejectProposal(id);
      setProposals((prev) => prev.filter((p) => p.id !== id));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject proposal");
    }
  };

  const handleBulkAction = async (action: "accept" | "reject") => {
    if (selectedIds.size === 0) return;
    setBulkProcessing(true);
    setError(null);
    try {
      await bulkAction(Array.from(selectedIds), action);
      setProposals((prev) => prev.filter((p) => !selectedIds.has(p.id)));
      setSelectedIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk action failed");
    } finally {
      setBulkProcessing(false);
    }
  };

  const isPending = status === "pending";

  return (
    <div className="space-y-4" role="region" aria-label="Proposal Review">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">
            Competency Proposals
          </h2>
          <p className="text-sm text-[rgb(var(--muted-foreground))]">
            Review discovered competencies from your public sources
          </p>
        </div>
        <StatusFilterTabs activeStatus={status} onStatusChange={setStatus} />
      </div>

      {/* Bulk actions bar (only shown when pending and items selected) */}
      {isPending && selectedIds.size > 0 && (
        <div
          className="flex items-center gap-3 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--muted))] p-3"
          role="toolbar"
          aria-label="Bulk actions"
        >
          <span className="text-sm font-medium text-[rgb(var(--foreground))]">
            {selectedIds.size} selected
          </span>
          <button
            onClick={() => handleBulkAction("accept")}
            disabled={bulkProcessing}
            className="min-h-[44px] rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
            aria-label={`Bulk accept ${selectedIds.size} proposals`}
          >
            {bulkProcessing ? "Processing…" : "Accept All Selected"}
          </button>
          <button
            onClick={() => handleBulkAction("reject")}
            disabled={bulkProcessing}
            className="min-h-[44px] rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
            aria-label={`Bulk reject ${selectedIds.size} proposals`}
          >
            {bulkProcessing ? "Processing…" : "Reject All Selected"}
          </button>
        </div>
      )}

      {/* Select all toggle (only for pending) */}
      {isPending && proposals.length > 0 && (
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={selectedIds.size === proposals.length && proposals.length > 0}
            onChange={toggleSelectAll}
            aria-label="Select all proposals"
            className="h-4 w-4 rounded border-[rgb(var(--border))] text-[rgb(var(--accent))] focus:ring-[rgb(var(--focus-ring))]"
          />
          <span className="text-sm text-[rgb(var(--muted-foreground))]">
            Select all ({Math.min(proposals.length, MAX_BULK_SIZE)} max)
          </span>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-12" aria-live="polite">
          <div className="flex items-center gap-2 text-sm text-[rgb(var(--muted-foreground))]">
            <svg
              className="h-4 w-4 animate-spin"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            Loading proposals…
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20"
          role="alert"
        >
          <p className="text-sm text-red-800 dark:text-red-300">{error}</p>
          <button
            onClick={loadProposals}
            className="mt-2 text-sm font-medium text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
          >
            Try again
          </button>
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && proposals.length === 0 && (
        <div className="rounded-lg border-2 border-dashed border-[rgb(var(--border))] p-8 text-center">
          <p className="text-sm text-[rgb(var(--muted-foreground))]">
            No {status} proposals found.
          </p>
          {status === "pending" && (
            <p className="mt-1 text-xs text-[rgb(var(--muted-foreground))]">
              New proposals will appear here after your sources are scanned.
            </p>
          )}
        </div>
      )}

      {/* Proposals list */}
      {!loading && proposals.length > 0 && (
        <div className="space-y-3" role="list" aria-label={`${status} proposals`}>
          {proposals.map((proposal) => (
            <ProposalCard
              key={proposal.id}
              proposal={proposal}
              isSelected={selectedIds.has(proposal.id)}
              onToggleSelect={toggleSelect}
              onAccept={handleAccept}
              onReject={handleReject}
              isPending={isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}
