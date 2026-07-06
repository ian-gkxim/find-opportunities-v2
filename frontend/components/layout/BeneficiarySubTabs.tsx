"use client";

import { useState } from "react";
import type { BeneficiarySubTab, NavigationPanel } from "@/lib/api";

/**
 * Schema-driven beneficiary sub-tab navigation.
 * Renders sub-tabs derived from the SchemaRegistry navigation structure.
 * Adding a new beneficiary in the schema YAML will automatically produce
 * a new sub-tab here without frontend code changes.
 *
 * Requirements: 12.2, 12.7
 */

interface BeneficiarySubTabsProps {
  subTabs: BeneficiarySubTab[];
  renderPanel: (panel: NavigationPanel, beneficiaryId: string) => React.ReactNode;
}

export function BeneficiarySubTabs({ subTabs, renderPanel }: BeneficiarySubTabsProps) {
  const [activeTab, setActiveTab] = useState(subTabs[0]?.beneficiary_id ?? "");
  const [activePanel, setActivePanel] = useState(subTabs[0]?.panels[0]?.id ?? "");

  const currentTab = subTabs.find((t) => t.beneficiary_id === activeTab);
  const currentPanel = currentTab?.panels.find((p) => p.id === activePanel);

  // When switching beneficiary tabs, reset to first panel
  const handleTabChange = (beneficiaryId: string) => {
    setActiveTab(beneficiaryId);
    const tab = subTabs.find((t) => t.beneficiary_id === beneficiaryId);
    if (tab && tab.panels.length > 0) {
      setActivePanel(tab.panels[0].id);
    }
  };

  if (subTabs.length === 0) {
    return (
      <p className="text-sm text-[rgb(var(--muted-foreground))]">
        No beneficiaries configured for this stage.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {/* Beneficiary sub-tabs */}
      <nav aria-label="Beneficiary selection" role="tablist">
        <div className="flex rounded-lg border border-[rgb(var(--border))] overflow-hidden w-fit">
          {subTabs.map((tab) => (
            <button
              key={tab.beneficiary_id}
              role="tab"
              aria-selected={activeTab === tab.beneficiary_id}
              aria-controls={`tabpanel-${tab.beneficiary_id}`}
              id={`tab-${tab.beneficiary_id}`}
              onClick={() => handleTabChange(tab.beneficiary_id)}
              className={`min-h-[44px] px-4 py-2 text-sm font-medium transition-colors
                focus-visible:outline-2 focus-visible:outline-offset-2
                focus-visible:outline-[rgb(var(--focus-ring))]
                ${
                  activeTab === tab.beneficiary_id
                    ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                    : "text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))]"
                }`}
            >
              {tab.beneficiary_label}
            </button>
          ))}
        </div>
      </nav>

      {/* Panel pill navigation within selected beneficiary */}
      {currentTab && currentTab.panels.length > 1 && (
        <nav aria-label="Panel navigation" role="tablist">
          <div className="flex flex-wrap gap-2">
            {currentTab.panels.map((panel) => (
              <button
                key={panel.id}
                role="tab"
                aria-selected={activePanel === panel.id}
                aria-controls={`panel-${panel.id}`}
                id={`pill-${panel.id}`}
                onClick={() => setActivePanel(panel.id)}
                className={`min-h-[44px] rounded-full px-4 py-2 text-sm font-medium
                  transition-colors
                  focus-visible:outline-2 focus-visible:outline-offset-2
                  focus-visible:outline-[rgb(var(--focus-ring))]
                  ${
                    activePanel === panel.id
                      ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                      : "border border-[rgb(var(--border))] text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))]"
                  }`}
              >
                {panel.label}
              </button>
            ))}
          </div>
        </nav>
      )}

      {/* Active panel content */}
      <div
        role="tabpanel"
        id={currentTab ? `tabpanel-${currentTab.beneficiary_id}` : undefined}
        aria-labelledby={currentTab ? `tab-${currentTab.beneficiary_id}` : undefined}
        className="mt-4"
      >
        {currentPanel && renderPanel(currentPanel, activeTab)}
      </div>
    </div>
  );
}
