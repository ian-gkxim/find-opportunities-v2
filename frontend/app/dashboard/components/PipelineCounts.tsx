"use client";

// ============================================================================
// Pipeline Counts — active pipeline counts by stage with real-time updates
// Requirement 8.1, 8.4
// ============================================================================

interface PipelineCountsProps {
  counts: Record<string, number>;
}

const STAGE_COLORS: Record<string, string> = {
  "Discovered": "border-l-blue-500",
  "Enriched": "border-l-indigo-500",
  "Drafted": "border-l-purple-500",
  "Sent": "border-l-amber-500",
  "Replied": "border-l-green-500",
  "Meeting Booked": "border-l-emerald-600",
  "Proposal Requested": "border-l-teal-500",
  "Won": "border-l-green-600",
  "Converted": "border-l-green-600",
};

export function PipelineCounts({ counts }: PipelineCountsProps) {
  const stages = Object.entries(counts);

  return (
    <section aria-label="Pipeline counts by stage">
      <div className="grid gap-3 grid-cols-2 tablet:grid-cols-3 desktop:grid-cols-5">
        {stages.map(([stage, count]) => (
          <div
            key={stage}
            className={`card border-l-4 ${STAGE_COLORS[stage] || "border-l-gray-400"}`}
          >
            <p className="text-xs font-medium text-[rgb(var(--muted-foreground))] uppercase tracking-wide">
              {stage}
            </p>
            <p className="mt-1 text-2xl font-bold text-[rgb(var(--foreground))]">
              {count}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
