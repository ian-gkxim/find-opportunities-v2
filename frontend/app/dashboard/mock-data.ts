import type { Beneficiary, DashboardData } from "./types";

// ============================================================================
// Dashboard data fetcher — calls backend API with fallback to placeholder data
// ============================================================================

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Placeholder data shown when backend has no real data yet
const CONSULTANT_PLACEHOLDER: DashboardData = {
  pipelineCounts: {
    "Discovered": 42,
    "Enriched": 35,
    "Drafted": 18,
    "Sent": 12,
    "Replied": 5,
  },
  conversionRates: [
    { fromStage: "Discovered", toStage: "Enriched", rate: 83.3, period: "30d" },
    { fromStage: "Enriched", toStage: "Drafted", rate: 51.4, period: "30d" },
    { fromStage: "Drafted", toStage: "Sent", rate: 66.7, period: "30d" },
    { fromStage: "Sent", toStage: "Replied", rate: 41.7, period: "30d" },
  ],
  topProspects: [
    { id: "p1", companyName: "TechVentures Ltd", score: 92, tier: "A-tier", stage: "Enriched", intentStrength: "strong" },
    { id: "p2", companyName: "DataFlow Systems", score: 87, tier: "A-tier", stage: "Discovered", intentStrength: "moderate" },
    { id: "p3", companyName: "CloudFirst Solutions", score: 81, tier: "A-tier", stage: "Enriched", intentStrength: "strong" },
    { id: "p4", companyName: "Innovatech Group", score: 76, tier: "A-tier", stage: "Discovered" },
    { id: "p5", companyName: "NexGen Digital", score: 74, tier: "B-tier", stage: "Enriched", intentStrength: "weak" },
  ],
  requiresAction: [
    { id: "a1", type: "stale_followup", title: "Stale follow-up", description: "No activity for 9 days.", companyName: "Acme Corp", daysStale: 9, createdAt: "2024-01-15T10:00:00Z" },
    { id: "a2", type: "failed_sequence", title: "Sequence sync failed", description: "Cold Outreach v2 failed to sync to Lemlist.", companyName: "BuildRight Partners", createdAt: "2024-01-14T08:30:00Z" },
    { id: "a3", type: "enrichment_error", title: "Enrichment failed", description: "Apollo enrichment failed after 3 retries.", companyName: "MegaSoft Industries", createdAt: "2024-01-13T14:20:00Z" },
  ],
  hotProspects: [
    { id: "h1", companyName: "TechVentures Ltd", topic: "Cloud Migration", strength: "strong", detectedAt: "2024-01-16T12:00:00Z", score: 92 },
    { id: "h2", companyName: "CloudFirst Solutions", topic: "DevOps Automation", strength: "strong", detectedAt: "2024-01-15T09:00:00Z", score: 81 },
    { id: "h3", companyName: "DataFlow Systems", topic: "Data Engineering", strength: "moderate", detectedAt: "2024-01-16T08:00:00Z", score: 87 },
  ],
};

const TEAM_PLACEHOLDER: DashboardData = {
  pipelineCounts: {
    "Discovered": 28,
    "Enriched": 22,
    "Drafted": 10,
    "Sent": 8,
    "Replied": 3,
    "Proposal Requested": 1,
  },
  conversionRates: [
    { fromStage: "Discovered", toStage: "Enriched", rate: 78.6, period: "30d" },
    { fromStage: "Enriched", toStage: "Drafted", rate: 45.5, period: "30d" },
    { fromStage: "Drafted", toStage: "Sent", rate: 80.0, period: "30d" },
    { fromStage: "Sent", toStage: "Replied", rate: 37.5, period: "30d" },
  ],
  topProspects: [
    { id: "tp1", companyName: "UK Government Digital", score: 95, tier: "A-tier", stage: "Enriched", intentStrength: "strong" },
    { id: "tp2", companyName: "NHS Digital Services", score: 88, tier: "A-tier", stage: "Discovered", intentStrength: "moderate" },
    { id: "tp3", companyName: "FinTech Global Corp", score: 82, tier: "A-tier", stage: "Enriched" },
    { id: "tp4", companyName: "EnergyTech Solutions", score: 78, tier: "A-tier", stage: "Discovered", intentStrength: "weak" },
    { id: "tp5", companyName: "TransportCo Digital", score: 71, tier: "B-tier", stage: "Enriched" },
  ],
  requiresAction: [
    { id: "ta1", type: "stale_followup", title: "Stale follow-up", description: "No activity for 8 days on proposal enquiry.", companyName: "GovTech Solutions", daysStale: 8, createdAt: "2024-01-15T11:00:00Z" },
    { id: "ta2", type: "enrichment_error", title: "Enrichment failed", description: "Apollo returned no matching company.", companyName: "Defence Innovations Ltd", createdAt: "2024-01-14T16:00:00Z" },
  ],
  hotProspects: [
    { id: "th1", companyName: "UK Government Digital", topic: "Digital Transformation", strength: "strong", detectedAt: "2024-01-16T10:00:00Z", score: 95 },
    { id: "th2", companyName: "NHS Digital Services", topic: "Healthcare IT Modernization", strength: "strong", detectedAt: "2024-01-15T14:00:00Z", score: 88 },
  ],
};

/**
 * Fetch dashboard data from the backend API.
 * Falls back to placeholder data if the API is unavailable or returns empty.
 */
export async function fetchDashboardData(
  beneficiary: Beneficiary
): Promise<DashboardData> {
  const placeholder = beneficiary === "consultant" ? CONSULTANT_PLACEHOLDER : TEAM_PLACEHOLDER;

  try {
    const response = await fetch(
      `${API_BASE}/api/dashboard?beneficiary=${beneficiary}`,
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
        signal: AbortSignal.timeout(3000),
      }
    );

    if (!response.ok) {
      console.warn(`Dashboard API returned ${response.status}, using placeholder data`);
      return placeholder;
    }

    const data = await response.json();

    // If API returned empty data (no records in DB yet), use placeholder
    const hasData =
      Object.keys(data.pipelineCounts || {}).length > 0 ||
      (data.topProspects || []).length > 0 ||
      (data.hotProspects || []).length > 0;

    if (!hasData) {
      console.info("Dashboard API returned empty data, showing placeholder");
      return placeholder;
    }

    return data as DashboardData;
  } catch (error) {
    console.warn("Dashboard API unavailable, using placeholder data:", error);
    return placeholder;
  }
}
