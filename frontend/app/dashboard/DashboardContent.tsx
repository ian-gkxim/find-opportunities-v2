"use client";

import { useCallback, useEffect, useState } from "react";
import { useWebSocket, useWebSocketMessage } from "@/components/providers/WebSocketProvider";
import { PipelineCounts } from "./components/PipelineCounts";
import { ConversionRates } from "./components/ConversionRates";
import { TopProspects } from "./components/TopProspects";
import { RequiresAction } from "./components/RequiresAction";
import { HotProspects } from "./components/HotProspects";
import { QuickActions } from "./components/QuickActions";
import { BeneficiaryToggle } from "./components/BeneficiaryToggle";
import type { DashboardData, Beneficiary } from "./types";
import { fetchDashboardData } from "./mock-data";

// ============================================================================
// Dashboard Content — client component with real-time updates
// Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 3.4
// ============================================================================

export function DashboardContent() {
  const [beneficiary, setBeneficiary] = useState<Beneficiary>("consultant");
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const { stateSync } = useWebSocket();

  // Initial data load
  useEffect(() => {
    loadDashboardData(beneficiary);
  }, [beneficiary]);

  // Apply state sync from WebSocket reconnections
  useEffect(() => {
    if (stateSync) {
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          pipelineCounts: stateSync.pipeline_counts,
        };
      });
    }
  }, [stateSync]);

  // Listen for pipeline updates (< 10s reflect requirement)
  useWebSocketMessage("pipeline_update", useCallback((msg) => {
    const update = msg as unknown as {
      record_id: string;
      status: string;
      beneficiary_id?: string;
    };
    // If this update matches our beneficiary, refresh counts
    if (!update.beneficiary_id || update.beneficiary_id === beneficiary) {
      loadDashboardData(beneficiary);
    }
  }, [beneficiary]));

  async function loadDashboardData(ben: Beneficiary) {
    setLoading(true);
    try {
      const result = await fetchDashboardData(ben);
      setData(result);
    } catch (error) {
      console.error("Failed to load dashboard data:", error);
    } finally {
      setLoading(false);
    }
  }

  if (loading && !data) {
    return <DashboardSkeleton />;
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-[rgb(var(--muted-foreground))]">
          Failed to load dashboard data.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with beneficiary toggle */}
      <div className="flex flex-col gap-4 tablet:flex-row tablet:items-center tablet:justify-between">
        <h1 className="text-2xl font-bold text-[rgb(var(--foreground))]">
          Dashboard
        </h1>
        <BeneficiaryToggle
          value={beneficiary}
          onChange={setBeneficiary}
        />
      </div>

      {/* Real-time updates region — WCAG aria-live for pipeline changes */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        Pipeline data updated for {beneficiary} beneficiary
      </div>

      {/* Pipeline counts by stage — Requirement 8.1 */}
      <section aria-labelledby="pipeline-counts-heading">
        <h2 id="pipeline-counts-heading" className="sr-only">Pipeline Counts by Stage</h2>
        <PipelineCounts counts={data.pipelineCounts} />
      </section>

      {/* Conversion rates and top prospects row */}
      <div className="grid gap-6 desktop:grid-cols-2">
        {/* 30-day conversion rates — Requirement 8.1 */}
        <section aria-labelledby="conversion-rates-heading">
          <h2 id="conversion-rates-heading" className="sr-only">30-Day Conversion Rates</h2>
          <ConversionRates rates={data.conversionRates} />
        </section>

        {/* Top 5 highest-scored pending prospects — Requirement 8.1 */}
        <section aria-labelledby="top-prospects-heading">
          <h2 id="top-prospects-heading" className="sr-only">Top Scored Prospects</h2>
          <TopProspects prospects={data.topProspects} />
        </section>
      </div>

      {/* Requires Action and Hot Prospects row */}
      <div className="grid gap-6 desktop:grid-cols-2">
        {/* Requires Action — Requirement 8.2 */}
        <section aria-labelledby="requires-action-heading">
          <h2 id="requires-action-heading" className="sr-only">Requires Action</h2>
          <RequiresAction items={data.requiresAction} />
        </section>

        {/* Hot Prospects — Requirement 3.4 */}
        <section aria-labelledby="hot-prospects-heading">
          <h2 id="hot-prospects-heading" className="sr-only">Hot Prospects</h2>
          <HotProspects prospects={data.hotProspects} />
        </section>
      </div>

      {/* Quick Actions — Requirement 8.5 */}
      <section aria-labelledby="quick-actions-heading">
        <h2 id="quick-actions-heading" className="sr-only">Quick Actions</h2>
        <QuickActions />
      </section>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-8 w-40 rounded bg-[rgb(var(--muted))]" />
        <div className="h-10 w-60 rounded bg-[rgb(var(--muted))]" />
      </div>
      <div className="grid gap-4 tablet:grid-cols-2 desktop:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-24 rounded-lg bg-[rgb(var(--muted))]" />
        ))}
      </div>
      <div className="grid gap-6 desktop:grid-cols-2">
        <div className="h-64 rounded-lg bg-[rgb(var(--muted))]" />
        <div className="h-64 rounded-lg bg-[rgb(var(--muted))]" />
      </div>
    </div>
  );
}
