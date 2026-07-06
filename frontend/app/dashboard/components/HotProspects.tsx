"use client";

import type { HotProspect } from "../types";

// ============================================================================
// Hot Prospects — companies with intent signals, sorted by strength then date
// Maximum 50 displayed. Requirement 3.4
// ============================================================================

interface HotProspectsProps {
  prospects: HotProspect[];
}

const STRENGTH_STYLES: Record<string, { badge: string; dot: string }> = {
  strong: {
    badge: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    dot: "bg-red-500",
  },
  moderate: {
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    dot: "bg-amber-500",
  },
  weak: {
    badge: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
    dot: "bg-gray-400",
  },
};

/**
 * Sorts hot prospects by signal strength descending, then by detection date descending.
 * Caps display at 50 items per Requirement 3.4.
 */
function sortHotProspects(prospects: HotProspect[]): HotProspect[] {
  const strengthOrder: Record<string, number> = { strong: 0, moderate: 1, weak: 2 };

  return [...prospects]
    .sort((a, b) => {
      const strengthDiff = (strengthOrder[a.strength] ?? 3) - (strengthOrder[b.strength] ?? 3);
      if (strengthDiff !== 0) return strengthDiff;
      // Then by detection date descending
      return new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime();
    })
    .slice(0, 50);
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function HotProspects({ prospects }: HotProspectsProps) {
  const sorted = sortHotProspects(prospects);

  return (
    <section className="card" aria-label="Hot prospects with intent signals">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">
          🔥 Hot Prospects
        </h2>
        {sorted.length > 0 && (
          <span className="text-xs text-[rgb(var(--muted-foreground))]">
            {sorted.length} signal{sorted.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      <div className="mt-4 space-y-2 max-h-80 overflow-y-auto">
        {sorted.map((prospect) => {
          const styles = STRENGTH_STYLES[prospect.strength];
          return (
            <div
              key={prospect.id}
              className="flex items-center gap-3 rounded-lg border border-[rgb(var(--border))] p-3"
            >
              {/* Strength indicator */}
              <span className={`h-2.5 w-2.5 flex-shrink-0 rounded-full ${styles.dot}`} />

              {/* Company and topic */}
              <div className="flex-1 min-w-0">
                <p className="truncate text-sm font-medium text-[rgb(var(--foreground))]">
                  {prospect.companyName}
                </p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${styles.badge}`}>
                    {prospect.strength}
                  </span>
                  <span className="text-xs text-[rgb(var(--muted-foreground))] truncate">
                    {prospect.topic}
                  </span>
                </div>
              </div>

              {/* Date and score */}
              <div className="flex flex-col items-end flex-shrink-0">
                <span className="text-xs text-[rgb(var(--muted-foreground))]">
                  {formatRelativeDate(prospect.detectedAt)}
                </span>
                <span className="text-xs font-medium text-[rgb(var(--foreground))]">
                  Score: {prospect.score}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {sorted.length === 0 && (
        <p className="mt-4 text-sm text-[rgb(var(--muted-foreground))]">
          No intent signals detected in the last 30 days.
        </p>
      )}
    </section>
  );
}
