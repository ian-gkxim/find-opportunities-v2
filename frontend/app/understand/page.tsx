"use client";

import { apiClient } from "@/lib/api";
import { BeneficiarySubTabs } from "@/components/layout/BeneficiarySubTabs";
import type { NavigationPanel } from "@/lib/api";

/**
 * Understand Us — schema-driven stage page.
 * Sub-tabs are derived from the SchemaRegistry. Adding a new beneficiary
 * in the schema YAML will produce a new sub-tab here automatically.
 *
 * Requirements: 12.2, 12.7
 */
export default function UnderstandPage() {
  const subTabs = apiClient.getSubTabsForStage("understand");

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-[rgb(var(--foreground))]">
          Understand Us
        </h1>
        <p className="mt-1 text-sm text-[rgb(var(--muted-foreground))]">
          Define who we are and what we offer
        </p>
      </header>

      <BeneficiarySubTabs
        subTabs={subTabs}
        renderPanel={(panel, beneficiaryId) => (
          <UnderstandPanel panel={panel} beneficiaryId={beneficiaryId} />
        )}
      />
    </div>
  );
}

function UnderstandPanel({
  panel,
  beneficiaryId,
}: {
  panel: NavigationPanel;
  beneficiaryId: string;
}) {
  return (
    <div className="card" role="region" aria-label={panel.label}>
      <h3 className="text-lg font-semibold text-[rgb(var(--foreground))]">
        {panel.label}
      </h3>
      <p className="mt-2 text-sm text-[rgb(var(--muted-foreground))]">
        Manage {panel.label.toLowerCase()} assets for the{" "}
        <span className="font-medium capitalize">{beneficiaryId}</span> beneficiary.
      </p>
      <div className="mt-4 rounded-lg border-2 border-dashed border-[rgb(var(--border))] p-8 text-center">
        <p className="text-sm text-[rgb(var(--muted-foreground))]">
          Asset management interface will be connected to the backend.
        </p>
        <p className="mt-1 text-xs text-[rgb(var(--muted-foreground))]">
          Panel type: {panel.type} | ID: {panel.id}
        </p>
      </div>
    </div>
  );
}
