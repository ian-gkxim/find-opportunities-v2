"use client";

import type { TopProspect } from "../types";

// ============================================================================
// Top Prospects — top 5 highest-scored pending prospects
// Requirement 8.1
// ============================================================================

interface TopProspectsProps {
  prospects: TopProspect[];
}

const TIER_BADGE_STYLES: Record<string, string> = {
  "A-tier": "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  "B-tier": "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  "C-tier": "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  "D-tier": "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
};

const INTENT_STYLES: Record<string, string> = {
  strong: "text-red-600 dark:text-red-400",
  moderate: "text-amber-600 dark:text-amber-400",
  weak: "text-gray-500 dark:text-gray-400",
};

export function TopProspects({ prospects }: TopProspectsProps) {
  return (
    <section className="card" aria-label="Top 5 highest-scored prospects">
      <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">
        Top Prospects
      </h2>

      <div className="mt-4 space-y-3">
        {prospects.map((prospect, index) => (
          <div
            key={prospect.id}
            className="flex items-center gap-3 rounded-lg border border-[rgb(var(--border))] p-3"
          >
            {/* Rank */}
            <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-[rgb(var(--muted))] text-xs font-medium text-[rgb(var(--muted-foreground))]">
              {index + 1}
            </span>

            {/* Company info */}
            <div className="flex-1 min-w-0">
              <p className="truncate text-sm font-medium text-[rgb(var(--foreground))]">
                {prospect.companyName}
              </p>
              <p className="text-xs text-[rgb(var(--muted-foreground))]">
                {prospect.stage}
                {prospect.intentStrength && (
                  <span className={`ml-2 ${INTENT_STYLES[prospect.intentStrength]}`}>
                    ● {prospect.intentStrength} intent
                  </span>
                )}
              </p>
            </div>

            {/* Score and tier */}
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-sm font-bold text-[rgb(var(--foreground))]">
                {prospect.score}
              </span>
              <span
                className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                  TIER_BADGE_STYLES[prospect.tier] || ""
                }`}
              >
                {prospect.tier.charAt(0)}
              </span>
            </div>
          </div>
        ))}
      </div>

      {prospects.length === 0 && (
        <p className="mt-4 text-sm text-[rgb(var(--muted-foreground))]">
          No pending prospects scored yet.
        </p>
      )}
    </section>
  );
}
