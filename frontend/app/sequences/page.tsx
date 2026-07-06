"use client";

import { useState, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type SyncStatus = "synced" | "sync_failed" | "pending";
type Channel = "email" | "linkedin" | "manual_task";

interface SequenceStep {
  order: number;
  channel: Channel;
  delay_days: number;
  content_template: string;
}

interface Sequence {
  id: string;
  name: string;
  beneficiary_id: string;
  step_count: number;
  sync_status: SyncStatus;
  created_at: string;
  steps?: SequenceStep[];
}

// Placeholder data when backend is empty
const PLACEHOLDER_SEQUENCES: Sequence[] = [
  {
    id: "seq-1",
    name: "Tech Outreach v2",
    beneficiary_id: "consultant",
    step_count: 4,
    sync_status: "synced",
    created_at: "2024-01-10T09:00:00Z",
    steps: [
      { order: 1, channel: "email", delay_days: 1, content_template: "Hi {{first_name}}, I noticed {{company}} is expanding their engineering team..." },
      { order: 2, channel: "email", delay_days: 3, content_template: "Following up on my previous email..." },
      { order: 3, channel: "linkedin", delay_days: 5, content_template: "Connect request with personalized note" },
      { order: 4, channel: "email", delay_days: 7, content_template: "Final follow-up — would love to chat about..." },
    ],
  },
  {
    id: "seq-2",
    name: "Enterprise Cold",
    beneficiary_id: "team",
    step_count: 3,
    sync_status: "synced",
    created_at: "2024-01-08T14:00:00Z",
    steps: [
      { order: 1, channel: "email", delay_days: 1, content_template: "Dear {{first_name}}, GKIM specializes in..." },
      { order: 2, channel: "email", delay_days: 5, content_template: "I wanted to follow up on our capabilities..." },
      { order: 3, channel: "manual_task", delay_days: 10, content_template: "Call to discuss proposal" },
    ],
  },
  {
    id: "seq-3",
    name: "Job Application Follow-up",
    beneficiary_id: "consultant",
    step_count: 2,
    sync_status: "pending",
    created_at: "2024-01-12T11:30:00Z",
    steps: [
      { order: 1, channel: "email", delay_days: 3, content_template: "I recently applied for the {{role}} position..." },
      { order: 2, channel: "linkedin", delay_days: 7, content_template: "Connect with hiring manager" },
    ],
  },
];

function SyncStatusBadge({ status }: { status: SyncStatus }) {
  const config: Record<SyncStatus, { color: string; label: string }> = {
    synced: { color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400", label: "Synced" },
    sync_failed: { color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400", label: "Sync Failed" },
    pending: { color: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400", label: "Pending" },
  };
  const { color, label } = config[status];
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {label}
    </span>
  );
}

function ChannelBadge({ channel }: { channel: Channel }) {
  const config: Record<Channel, { color: string; label: string; icon: string }> = {
    email: { color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400", label: "Email", icon: "✉" },
    linkedin: { color: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400", label: "LinkedIn", icon: "in" },
    manual_task: { color: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300", label: "Manual", icon: "✋" },
  };
  const { color, label, icon } = config[channel];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      <span>{icon}</span> {label}
    </span>
  );
}

export default function SequencesPage() {
  const [sequences, setSequences] = useState<Sequence[]>(PLACEHOLDER_SEQUENCES);
  const [selectedSequence, setSelectedSequence] = useState<Sequence | null>(null);
  const [beneficiaryFilter, setBeneficiaryFilter] = useState<"all" | "consultant" | "team">("all");
  const [showCreateForm, setShowCreateForm] = useState(false);

  // Fetch sequences from backend
  useEffect(() => {
    async function fetchSequences() {
      try {
        const params = new URLSearchParams({ page: "1", page_size: "50" });
        if (beneficiaryFilter !== "all") params.set("beneficiary_id", beneficiaryFilter);

        const response = await fetch(`${API_BASE}/api/sequences?${params}`, {
          signal: AbortSignal.timeout(3000),
        });

        if (response.ok) {
          const data = await response.json();
          if (data.items && data.items.length > 0) {
            setSequences(data.items);
            return;
          }
        }
        setSequences(PLACEHOLDER_SEQUENCES);
      } catch {
        setSequences(PLACEHOLDER_SEQUENCES);
      }
    }
    fetchSequences();
  }, [beneficiaryFilter]);

  const filteredSequences = sequences.filter((seq) => {
    if (beneficiaryFilter !== "all" && seq.beneficiary_id !== beneficiaryFilter) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 tablet:flex-row tablet:items-center tablet:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[rgb(var(--foreground))]">Sequences</h1>
          <p className="text-sm text-[rgb(var(--muted-foreground))]">
            Manage multi-channel outreach sequences synced to Lemlist
          </p>
        </div>
        <button
          onClick={() => setShowCreateForm(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-[rgb(var(--accent))] px-4 py-2.5 text-sm font-medium text-[rgb(var(--accent-foreground))] hover:opacity-90 transition-opacity"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          New Sequence
        </button>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex items-center gap-3">
          <fieldset>
            <legend className="sr-only">Filter by beneficiary</legend>
            <div className="flex rounded-lg border border-[rgb(var(--border))] overflow-hidden" role="radiogroup" aria-label="Beneficiary filter">
              {(["all", "consultant", "team"] as const).map((b) => (
                <button
                  key={b}
                  role="radio"
                  aria-checked={beneficiaryFilter === b}
                  onClick={() => setBeneficiaryFilter(b)}
                  className={`min-h-[44px] px-3 py-1.5 text-sm font-medium transition-colors
                    focus-visible:outline-2 focus-visible:outline-offset-2
                    focus-visible:outline-[rgb(var(--focus-ring))]
                    ${
                      beneficiaryFilter === b
                        ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                        : "text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))]"
                    }`}
                >
                  {b === "all" ? "All" : b === "consultant" ? "Consultant" : "Team"}
                </button>
              ))}
            </div>
          </fieldset>
          <span className="text-sm text-[rgb(var(--muted-foreground))]">
            {filteredSequences.length} sequence{filteredSequences.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Sequences List */}
      <div className="grid gap-4">
        {filteredSequences.map((seq) => (
          <button
            key={seq.id}
            onClick={() => setSelectedSequence(seq)}
            className="card text-left hover:ring-2 hover:ring-[rgb(var(--accent))] transition-all cursor-pointer w-full"
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-semibold text-[rgb(var(--foreground))]">{seq.name}</h3>
                  <SyncStatusBadge status={seq.sync_status} />
                </div>
                <p className="mt-1 text-sm text-[rgb(var(--muted-foreground))]">
                  {seq.step_count} steps · {seq.beneficiary_id === "consultant" ? "Consultant" : "Team"}
                </p>
              </div>
              <span className="text-xs text-[rgb(var(--muted-foreground))]">
                Created {new Date(seq.created_at).toLocaleDateString()}
              </span>
            </div>
            {/* Step preview */}
            {seq.steps && (
              <div className="mt-3 flex items-center gap-2">
                {seq.steps.map((step, i) => (
                  <div key={step.order} className="flex items-center gap-1">
                    <ChannelBadge channel={step.channel} />
                    {i < seq.steps!.length - 1 && (
                      <span className="text-xs text-[rgb(var(--muted-foreground))]">→</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </button>
        ))}

        {filteredSequences.length === 0 && (
          <div className="card text-center py-12">
            <p className="text-[rgb(var(--muted-foreground))]">No sequences found.</p>
            <button
              onClick={() => setShowCreateForm(true)}
              className="mt-3 text-sm font-medium text-[rgb(var(--accent))] hover:underline"
            >
              Create your first sequence
            </button>
          </div>
        )}
      </div>

      {/* Sequence Detail Panel */}
      {selectedSequence && (
        <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Sequence detail">
          <div className="absolute inset-0 bg-black/50" onClick={() => setSelectedSequence(null)} />
          <div className="relative w-full max-w-lg bg-[rgb(var(--card))] shadow-xl overflow-y-auto">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[rgb(var(--border))] bg-[rgb(var(--card))] px-6 py-4">
              <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">{selectedSequence.name}</h2>
              <button
                onClick={() => setSelectedSequence(null)}
                className="rounded-lg p-1 hover:bg-[rgb(var(--muted))] text-[rgb(var(--muted-foreground))]"
                aria-label="Close detail panel"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-6 space-y-6">
              {/* Metadata */}
              <div className="flex items-center gap-3">
                <SyncStatusBadge status={selectedSequence.sync_status} />
                <span className="text-sm text-[rgb(var(--muted-foreground))] capitalize">
                  {selectedSequence.beneficiary_id}
                </span>
              </div>

              {/* Steps */}
              <div>
                <h3 className="text-sm font-semibold text-[rgb(var(--foreground))] mb-3">Steps</h3>
                <div className="space-y-3">
                  {selectedSequence.steps?.map((step) => (
                    <div key={step.order} className="rounded-lg border border-[rgb(var(--border))] p-3">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-[rgb(var(--muted-foreground))]">
                            Step {step.order}
                          </span>
                          <ChannelBadge channel={step.channel} />
                        </div>
                        <span className="text-xs text-[rgb(var(--muted-foreground))]">
                          +{step.delay_days} day{step.delay_days !== 1 ? "s" : ""}
                        </span>
                      </div>
                      <p className="text-sm text-[rgb(var(--foreground))] line-clamp-3">
                        {step.content_template}
                      </p>
                    </div>
                  ))}
                  {(!selectedSequence.steps || selectedSequence.steps.length === 0) && (
                    <p className="text-sm text-[rgb(var(--muted-foreground))]">No steps configured.</p>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div className="border-t border-[rgb(var(--border))] pt-4 space-y-2">
                <button className="w-full rounded-lg bg-[rgb(var(--accent))] px-4 py-2.5 text-sm font-medium text-[rgb(var(--accent-foreground))] hover:opacity-90 transition-opacity">
                  Enroll Prospects
                </button>
                {selectedSequence.sync_status === "sync_failed" && (
                  <button className="w-full rounded-lg border border-[rgb(var(--border))] px-4 py-2.5 text-sm font-medium text-[rgb(var(--foreground))] hover:bg-[rgb(var(--muted))] transition-colors">
                    Retry Sync to Lemlist
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Create Sequence Modal (placeholder) */}
      {showCreateForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-label="Create sequence">
          <div className="absolute inset-0 bg-black/50" onClick={() => setShowCreateForm(false)} />
          <div className="relative w-full max-w-md bg-[rgb(var(--card))] rounded-xl shadow-xl p-6">
            <h2 className="text-lg font-semibold text-[rgb(var(--foreground))] mb-4">Create New Sequence</h2>
            <p className="text-sm text-[rgb(var(--muted-foreground))] mb-4">
              Sequence creation will be available once Lemlist API key is configured in Settings.
            </p>
            <button
              onClick={() => setShowCreateForm(false)}
              className="w-full rounded-lg border border-[rgb(var(--border))] px-4 py-2.5 text-sm font-medium text-[rgb(var(--foreground))] hover:bg-[rgb(var(--muted))] transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
