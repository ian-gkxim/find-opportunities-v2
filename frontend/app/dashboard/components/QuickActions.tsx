"use client";

import { useState } from "react";

// ============================================================================
// Quick Actions — enroll, approve, trigger discovery with single click
// Requirement 8.5
// ============================================================================

interface QuickAction {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  action: () => Promise<void>;
}

export function QuickActions() {
  const [loading, setLoading] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ id: string; message: string } | null>(null);

  async function handleAction(action: QuickAction) {
    setLoading(action.id);
    setFeedback(null);
    try {
      await action.action();
      setFeedback({ id: action.id, message: "Done!" });
    } catch {
      setFeedback({ id: action.id, message: "Failed. Try again." });
    } finally {
      setLoading(null);
      // Clear feedback after 3 seconds
      setTimeout(() => setFeedback(null), 3000);
    }
  }

  const actions: QuickAction[] = [
    {
      id: "enroll",
      label: "Enroll Prospects",
      description: "Enroll top-scored prospects in active sequence",
      icon: (
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M18 7.5v3m0 0v3m0-3h3m-3 0h-3m-2.25-4.125a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zM3 19.235v-.11a6.375 6.375 0 0112.75 0v.109A12.318 12.318 0 019.374 21c-2.331 0-4.512-.645-6.374-1.766z" />
        </svg>
      ),
      action: async () => {
        // In production: POST /api/sequences/{id}/enroll with top prospects
        await new Promise((r) => setTimeout(r, 500));
      },
    },
    {
      id: "approve",
      label: "Approve Materials",
      description: "Review and approve drafted outreach materials",
      icon: (
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
      action: async () => {
        // In production: navigate to materials review page or modal
        await new Promise((r) => setTimeout(r, 300));
      },
    },
    {
      id: "discovery",
      label: "Run Discovery",
      description: "Trigger a manual discovery run across all sources",
      icon: (
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
      ),
      action: async () => {
        // In production: POST /api/discovery/run
        await new Promise((r) => setTimeout(r, 800));
      },
    },
  ];

  return (
    <section className="card" aria-label="Quick actions">
      <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">
        Quick Actions
      </h2>

      <div className="mt-4 grid gap-3 tablet:grid-cols-3">
        {actions.map((action) => (
          <button
            key={action.id}
            onClick={() => handleAction(action)}
            disabled={loading !== null}
            className="flex flex-col items-center gap-2 rounded-lg border border-[rgb(var(--border))]
                       p-4 text-center transition-colors
                       hover:bg-[rgb(var(--accent))] hover:text-[rgb(var(--accent-foreground))]
                       focus:outline-none focus:ring-2 focus:ring-[rgb(var(--primary))] focus:ring-offset-2
                       disabled:opacity-50 disabled:cursor-not-allowed
                       min-h-[88px]"
            aria-label={action.label}
          >
            {loading === action.id ? (
              <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
                <path fill="currentColor" className="opacity-75" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <span className="text-[rgb(var(--primary))]">{action.icon}</span>
            )}
            <div>
              <p className="text-sm font-medium text-[rgb(var(--foreground))]">
                {action.label}
              </p>
              <p className="text-xs text-[rgb(var(--muted-foreground))] mt-0.5">
                {action.description}
              </p>
            </div>
            {feedback?.id === action.id && (
              <span className="text-xs font-medium text-green-600 dark:text-green-400">
                {feedback.message}
              </span>
            )}
          </button>
        ))}
      </div>
    </section>
  );
}
