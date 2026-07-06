import type { Metadata } from "next";
import { DashboardContent } from "./DashboardContent";

export const metadata: Metadata = {
  title: "Dashboard | GKIM Opportunity Finder",
  description: "Pipeline health, actionable insights, and key metrics at a glance",
};

/**
 * Dashboard — the primary entry point (Requirement 8.1).
 * Displays within 2 seconds: active pipeline counts, conversion rates,
 * top 5 highest-scored pending prospects.
 */
export default function DashboardPage() {
  return <DashboardContent />;
}
