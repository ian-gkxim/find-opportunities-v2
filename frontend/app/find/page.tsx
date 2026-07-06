"use client";

import { apiClient } from "@/lib/api";
import { BeneficiarySubTabs } from "@/components/layout/BeneficiarySubTabs";
import type { NavigationPanel } from "@/lib/api";

/**
 * Find Prospects — schema-driven stage page.
 * Sub-tabs are derived from the SchemaRegistry. Adding a new beneficiary
 * in the schema YAML will produce a new sub-tab here automatically.
 *
 * Requirements: 12.2, 12.7
 */
export default function FindPage() {
  const subTabs = apiClient.getSubTabsForStage("find");

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-[rgb(var(--foreground))]">
          Find Prospects
        </h1>
        <p className="mt-1 text-sm text-[rgb(var(--muted-foreground))]">
          Discover opportunities from configured sources
        </p>
      </header>

      <BeneficiarySubTabs
        subTabs={subTabs}
        renderPanel={(panel, beneficiaryId) => (
          <FindPanel panel={panel} beneficiaryId={beneficiaryId} />
        )}
      />
    </div>
  );
}

function FindPanel({
  panel,
  beneficiaryId,
}: {
  panel: NavigationPanel;
  beneficiaryId: string;
}) {
  return (
    <div className="card" role="region" aria-label={panel.label}>
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-[rgb(var(--foreground))]">
          {panel.label}
        </h3>
        <button
          className="min-h-[44px] rounded-lg bg-[rgb(var(--accent))] px-4 py-2 text-sm
                     font-medium text-[rgb(var(--accent-foreground))]
                     hover:opacity-90 transition-opacity
                     focus-visible:outline-2 focus-visible:outline-offset-2
                     focus-visible:outline-[rgb(var(--focus-ring))]"
          aria-label={`Run discovery for ${panel.label}`}
        >
          Run Discovery
        </button>
      </div>
      <p className="mt-2 text-sm text-[rgb(var(--muted-foreground))]">
        Discover prospects for the{" "}
        <span className="font-medium capitalize">{beneficiaryId}</span> beneficiary
        using the configured source.
      </p>
      <div className="mt-4 rounded-lg border-2 border-dashed border-[rgb(var(--border))] p-8 text-center">
        <p className="text-sm text-[rgb(var(--muted-foreground))]">
          Discovery results will be displayed here when connected to the backend.
        </p>
        <p className="mt-1 text-xs text-[rgb(var(--muted-foreground))]">
          Panel type: {panel.type} | ID: {panel.id}
        </p>
      </div>
    </div>
  );
}
