"use client";

import type { Beneficiary } from "../types";

// ============================================================================
// Beneficiary Toggle — switch between Consultant / Team views
// Requirement 8.3
// ============================================================================

interface BeneficiaryToggleProps {
  value: Beneficiary;
  onChange: (value: Beneficiary) => void;
}

export function BeneficiaryToggle({ value, onChange }: BeneficiaryToggleProps) {
  return (
    <div
      className="inline-flex rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--muted))] p-1"
      role="radiogroup"
      aria-label="Select beneficiary view"
    >
      <button
        role="radio"
        aria-checked={value === "consultant"}
        onClick={() => onChange("consultant")}
        className={`rounded-md px-4 py-2 text-sm font-medium transition-colors
          ${
            value === "consultant"
              ? "bg-[rgb(var(--card))] text-[rgb(var(--foreground))] shadow-sm"
              : "text-[rgb(var(--muted-foreground))] hover:text-[rgb(var(--foreground))]"
          }`}
      >
        Consultant
      </button>
      <button
        role="radio"
        aria-checked={value === "team"}
        onClick={() => onChange("team")}
        className={`rounded-md px-4 py-2 text-sm font-medium transition-colors
          ${
            value === "team"
              ? "bg-[rgb(var(--card))] text-[rgb(var(--foreground))] shadow-sm"
              : "text-[rgb(var(--muted-foreground))] hover:text-[rgb(var(--foreground))]"
          }`}
      >
        Team
      </button>
    </div>
  );
}
