"use client";

import type { ConversionRate } from "../types";

// ============================================================================
// Conversion Rates — 30-day conversion rates display
// Requirement 8.1
// ============================================================================

interface ConversionRatesProps {
  rates: ConversionRate[];
}

export function ConversionRates({ rates }: ConversionRatesProps) {
  return (
    <section className="card" aria-label="30-day conversion rates">
      <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">
        Conversion Rates
        <span className="ml-2 text-xs font-normal text-[rgb(var(--muted-foreground))]">
          Last 30 days
        </span>
      </h2>

      <div className="mt-4 space-y-3">
        {rates.map((rate) => (
          <div key={`${rate.fromStage}-${rate.toStage}`} className="flex items-center gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1 text-sm">
                <span className="truncate text-[rgb(var(--foreground))]">
                  {rate.fromStage}
                </span>
                <svg
                  className="h-3 w-3 flex-shrink-0 text-[rgb(var(--muted-foreground))]"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
                </svg>
                <span className="truncate text-[rgb(var(--foreground))]">
                  {rate.toStage}
                </span>
              </div>
              {/* Progress bar */}
              <div className="mt-1 h-2 rounded-full bg-[rgb(var(--muted))] overflow-hidden">
                <div
                  className="h-full rounded-full bg-[rgb(var(--primary))] transition-all duration-500"
                  style={{ width: `${Math.min(rate.rate, 100)}%` }}
                  role="progressbar"
                  aria-valuenow={rate.rate}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${rate.fromStage} to ${rate.toStage} conversion rate`}
                />
              </div>
            </div>
            <span className="text-sm font-semibold text-[rgb(var(--foreground))] w-14 text-right">
              {rate.rate.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>

      {rates.length === 0 && (
        <p className="mt-4 text-sm text-[rgb(var(--muted-foreground))]">
          No conversion data available yet.
        </p>
      )}
    </section>
  );
}
