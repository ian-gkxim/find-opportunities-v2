"use client";

import { apiClient } from "@/lib/api";
import { BeneficiarySubTabs } from "@/components/layout/BeneficiarySubTabs";
import type { NavigationPanel } from "@/lib/api";

/**
 * Define Where to Look — schema-driven stage page.
 * Sub-tabs are derived from the SchemaRegistry. Adding a new beneficiary
 * in the schema YAML will produce a new sub-tab here automatically.
 *
 * Requirements: 12.2, 12.7
 */
export default function ConfigurePage() {
  const subTabs = apiClient.getSubTabsForStage("configure");

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-[rgb(var(--foreground))]">
          Define Where to Look
        </h1>
        <p className="mt-1 text-sm text-[rgb(var(--muted-foreground))]">
          Configure opportunity sources per type
        </p>
      </header>

      <BeneficiarySubTabs
        subTabs={subTabs}
        renderPanel={(panel, beneficiaryId) => (
          <ConfigurePanel panel={panel} beneficiaryId={beneficiaryId} />
        )}
      />
    </div>
  );
}

function ConfigurePanel({
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
        Configure discovery sources for the{" "}
        <span className="font-medium capitalize">{beneficiaryId}</span> beneficiary.
      </p>
      <div className="mt-4 rounded-lg border-2 border-dashed border-[rgb(var(--border))] p-8 text-center">
        <p className="text-sm text-[rgb(var(--muted-foreground))]">
          Source configuration will be connected to the backend.
        </p>
        <p className="mt-1 text-xs text-[rgb(var(--muted-foreground))]">
          Panel type: {panel.type} | ID: {panel.id}
        </p>
      </div>
    </div>
  );
}
