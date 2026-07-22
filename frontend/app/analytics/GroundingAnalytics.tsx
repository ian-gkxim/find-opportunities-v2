"use client";

import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// ============================================================================
// Grounding Analytics — ungrounded-claim rate per technique per week
// Requirements: 4.2
//
// Displays in the Reports/Analytics stage. Shows a line chart of the
// ungrounded-claim rate trend over trailing 12 weeks per prepare technique,
// using GET /grounding/analytics/rates and GET /grounding/analytics/trend.
// ============================================================================

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface WeeklyRateEntry {
  prepare_technique_id: string;
  week_start: string;
  week_end: string;
  total_claims_extracted: number;
  ungrounded_claims: number;
  partially_grounded_claims: number;
  ungrounded_rate: number;
  partially_grounded_rate: number;
}

interface GroundingRatesResponse {
  rates: WeeklyRateEntry[];
  period_weeks: number;
}

interface GroundingTrendResponse {
  technique_id: string;
  weeks: number;
  trend: WeeklyRateEntry[];
}

// Chart data point for recharts
interface ChartDataPoint {
  week: string;
  ungrounded_rate: number;
  partially_grounded_rate: number;
  total_claims: number;
}

// Color palette for technique lines
const TECHNIQUE_COLORS: Record<string, string> = {
  cv_and_cover_letter: "#6366f1",
  cold_email_composition: "#ec4899",
  proposal_composition: "#10b981",
};

const TECHNIQUE_LABELS: Record<string, string> = {
  cv_and_cover_letter: "CV & Cover Letter",
  cold_email_composition: "Cold Email",
  proposal_composition: "Proposal",
};

/**
 * Grounding Analytics section for the Reports stage.
 *
 * Shows ungrounded-claim rate per prepare technique per week as a line chart
 * over the trailing 12 weeks. Helps detect prompt regressions that introduce
 * more ungrounded content in generated materials.
 *
 * Requirements: 4.2
 */
export function GroundingAnalytics() {
  const [ratesData, setRatesData] = useState<GroundingRatesResponse | null>(
    null
  );
  const [selectedTechnique, setSelectedTechnique] = useState<string | null>(
    null
  );
  const [trendData, setTrendData] = useState<GroundingTrendResponse | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch rates overview on mount
  useEffect(() => {
    fetchRates();
  }, []);

  // Fetch trend when a technique is selected
  useEffect(() => {
    if (selectedTechnique) {
      fetchTrend(selectedTechnique);
    }
  }, [selectedTechnique]);

  async function fetchRates() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `${API_BASE}/api/grounding/analytics/rates?period_weeks=12`,
        {
          method: "GET",
          headers: { "Content-Type": "application/json" },
          signal: AbortSignal.timeout(10000),
        }
      );

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      const data: GroundingRatesResponse = await response.json();
      setRatesData(data);

      // Auto-select first technique if available
      if (data.rates.length > 0 && !selectedTechnique) {
        const techniques = Array.from(
          new Set(data.rates.map((r) => r.prepare_technique_id))
        );
        setSelectedTechnique(techniques[0]);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load grounding analytics"
      );
    } finally {
      setLoading(false);
    }
  }

  async function fetchTrend(techniqueId: string) {
    try {
      const response = await fetch(
        `${API_BASE}/api/grounding/analytics/trend/${techniqueId}?weeks=12`,
        {
          method: "GET",
          headers: { "Content-Type": "application/json" },
          signal: AbortSignal.timeout(10000),
        }
      );

      if (!response.ok) return;

      const data: GroundingTrendResponse = await response.json();
      setTrendData(data);
    } catch {
      // Silently fail — rates view still available
    }
  }

  // Derive unique techniques from rates data
  const techniques = ratesData
    ? Array.from(new Set(ratesData.rates.map((r) => r.prepare_technique_id)))
    : [];

  // Transform trend data for chart
  const chartData: ChartDataPoint[] = trendData
    ? trendData.trend.map((entry) => ({
        week: formatWeek(entry.week_start),
        ungrounded_rate: Math.round(entry.ungrounded_rate * 1000) / 10,
        partially_grounded_rate:
          Math.round(entry.partially_grounded_rate * 1000) / 10,
        total_claims: entry.total_claims_extracted,
      }))
    : [];

  // Compute summary stats from rates
  const summaryStats = computeSummaryStats(ratesData);

  return (
    <section className="card" aria-labelledby="grounding-analytics-heading">
      <div className="flex items-center justify-between">
        <div>
          <h2
            id="grounding-analytics-heading"
            className="text-lg font-semibold text-[rgb(var(--foreground))]"
          >
            Claim Grounding Rates
          </h2>
          <p className="text-xs text-[rgb(var(--muted-foreground))] mt-0.5">
            Ungrounded-claim rate per prepare technique — trailing 12 weeks
          </p>
        </div>
      </div>

      {/* Summary stats row */}
      {summaryStats && (
        <div className="mt-4 grid grid-cols-3 gap-4">
          <div className="rounded-lg border border-[rgb(var(--border))] p-3 text-center">
            <p className="text-xs text-[rgb(var(--muted-foreground))]">
              Avg. Ungrounded Rate
            </p>
            <p className="mt-1 text-xl font-bold text-red-600 dark:text-red-400">
              {summaryStats.avgUngroundedRate}%
            </p>
          </div>
          <div className="rounded-lg border border-[rgb(var(--border))] p-3 text-center">
            <p className="text-xs text-[rgb(var(--muted-foreground))]">
              Total Claims Checked
            </p>
            <p className="mt-1 text-xl font-bold text-[rgb(var(--foreground))]">
              {summaryStats.totalClaims}
            </p>
          </div>
          <div className="rounded-lg border border-[rgb(var(--border))] p-3 text-center">
            <p className="text-xs text-[rgb(var(--muted-foreground))]">
              Avg. Partially Grounded
            </p>
            <p className="mt-1 text-xl font-bold text-amber-600 dark:text-amber-400">
              {summaryStats.avgPartiallyGroundedRate}%
            </p>
          </div>
        </div>
      )}

      {/* Technique selector */}
      {techniques.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Prepare technique selector">
          {techniques.map((technique) => (
            <button
              key={technique}
              role="tab"
              aria-selected={selectedTechnique === technique}
              onClick={() => setSelectedTechnique(technique)}
              className={`min-h-[36px] rounded-lg px-3 py-1.5 text-xs font-medium transition-colors
                focus-visible:outline-2 focus-visible:outline-offset-2
                focus-visible:outline-[rgb(var(--focus-ring))]
                ${
                  selectedTechnique === technique
                    ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                    : "border border-[rgb(var(--border))] text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))]"
                }`}
            >
              {TECHNIQUE_LABELS[technique] || technique}
            </button>
          ))}
        </div>
      )}

      {/* Chart area */}
      {loading && (
        <div className="mt-4 h-64 flex items-center justify-center">
          <p className="text-sm text-[rgb(var(--muted-foreground))] animate-pulse">
            Loading grounding analytics...
          </p>
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/20">
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
          <button
            onClick={fetchRates}
            className="mt-2 text-xs font-medium text-red-600 underline hover:no-underline dark:text-red-400"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && chartData.length > 0 && (
        <div className="mt-4 h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis
                dataKey="week"
                tick={{ fontSize: 11 }}
                tickMargin={8}
              />
              <YAxis
                tick={{ fontSize: 11 }}
                tickFormatter={(value) => `${value}%`}
                domain={[0, "auto"]}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "rgb(var(--card))",
                  border: "1px solid rgb(var(--border))",
                  borderRadius: "0.5rem",
                  color: "rgb(var(--foreground))",
                  fontSize: "12px",
                }}
                formatter={(value: number, name: string) => [
                  `${value}%`,
                  name === "ungrounded_rate"
                    ? "Ungrounded"
                    : "Partially Grounded",
                ]}
                labelFormatter={(label) => `Week of ${label}`}
              />
              <Legend
                formatter={(value) =>
                  value === "ungrounded_rate"
                    ? "Ungrounded Rate"
                    : "Partially Grounded Rate"
                }
              />
              <Line
                type="monotone"
                dataKey="ungrounded_rate"
                stroke="#ef4444"
                strokeWidth={2}
                dot={{ r: 3, fill: "#ef4444" }}
                activeDot={{ r: 5 }}
                name="ungrounded_rate"
              />
              <Line
                type="monotone"
                dataKey="partially_grounded_rate"
                stroke="#f59e0b"
                strokeWidth={2}
                strokeDasharray="4 2"
                dot={{ r: 3, fill: "#f59e0b" }}
                activeDot={{ r: 5 }}
                name="partially_grounded_rate"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {!loading && !error && chartData.length === 0 && (
        <div className="mt-4 h-64 flex items-center justify-center rounded-lg border border-dashed border-[rgb(var(--border))]">
          <div className="text-center">
            <p className="text-sm text-[rgb(var(--muted-foreground))]">
              No grounding data available yet
            </p>
            <p className="mt-1 text-xs text-[rgb(var(--muted-foreground))]">
              Grounding analytics appear once materials are verified
            </p>
          </div>
        </div>
      )}
    </section>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatWeek(weekStart: string): string {
  const date = new Date(weekStart);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function computeSummaryStats(data: GroundingRatesResponse | null) {
  if (!data || data.rates.length === 0) return null;

  const totalClaims = data.rates.reduce(
    (sum, r) => sum + r.total_claims_extracted,
    0
  );
  const totalUngrounded = data.rates.reduce(
    (sum, r) => sum + r.ungrounded_claims,
    0
  );
  const totalPartiallyGrounded = data.rates.reduce(
    (sum, r) => sum + r.partially_grounded_claims,
    0
  );

  const avgUngroundedRate =
    totalClaims > 0
      ? Math.round((totalUngrounded / totalClaims) * 1000) / 10
      : 0;
  const avgPartiallyGroundedRate =
    totalClaims > 0
      ? Math.round((totalPartiallyGrounded / totalClaims) * 1000) / 10
      : 0;

  return {
    avgUngroundedRate,
    avgPartiallyGroundedRate,
    totalClaims,
  };
}
