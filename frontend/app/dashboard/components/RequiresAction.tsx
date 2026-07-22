"use client";

import type { ActionItem } from "../types";

// ============================================================================
// Requires Action — stale follow-ups, failed sequences, enrichment errors
// Requirement 8.2
// ============================================================================

interface RequiresActionProps {
  items: ActionItem[];
}

const TYPE_ICONS: Record<ActionItem["type"], { icon: string; color: string }> = {
  stale_followup: {
    icon: "⏰",
    color: "border-l-amber-500",
  },
  failed_sequence: {
    icon: "⚠️",
    color: "border-l-red-500",
  },
  enrichment_error: {
    icon: "🔴",
    color: "border-l-red-400",
  },
  grounding_blocked: {
    icon: "🚫",
    color: "border-l-red-600",
  },
  grounding_unverified: {
    icon: "❓",
    color: "border-l-yellow-500",
  },
};

export function RequiresAction({ items }: RequiresActionProps) {
  return (
    <section className="card" aria-label="Items requiring action">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">
          Requires Action
        </h2>
        {items.length > 0 && (
          <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900 dark:text-red-200">
            {items.length}
          </span>
        )}
      </div>

      <div className="mt-4 space-y-2 max-h-80 overflow-y-auto">
        {items.map((item) => {
          const config = TYPE_ICONS[item.type];
          return (
            <div
              key={item.id}
              className={`rounded-lg border border-[rgb(var(--border))] border-l-4 ${config.color} p-3`}
            >
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 text-sm" aria-hidden="true">
                  {config.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-[rgb(var(--foreground))]">
                    {item.companyName}
                  </p>
                  <p className="text-xs text-[rgb(var(--muted-foreground))]">
                    {item.description}
                  </p>
                  {item.daysStale && (
                    <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                      {item.daysStale} days inactive
                    </p>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {items.length === 0 && (
        <p className="mt-4 text-sm text-[rgb(var(--muted-foreground))]">
          No items require attention. All clear!
        </p>
      )}
    </section>
  );
}
