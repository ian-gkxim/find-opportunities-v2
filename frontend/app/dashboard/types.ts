// ============================================================================
// Dashboard Types
// ============================================================================

export type Beneficiary = "consultant" | "team";

export interface PipelineCount {
  stage: string;
  count: number;
  trend: "up" | "down" | "flat";
}

export interface ConversionRate {
  fromStage: string;
  toStage: string;
  rate: number; // 0-100 as percentage with 1dp
  period: "30d";
}

export interface TopProspect {
  id: string;
  companyName: string;
  score: number;
  tier: "A-tier" | "B-tier" | "C-tier" | "D-tier";
  stage: string;
  intentStrength?: "strong" | "moderate" | "weak";
}

export interface ActionItem {
  id: string;
  type: "stale_followup" | "failed_sequence" | "enrichment_error";
  title: string;
  description: string;
  companyName: string;
  daysStale?: number;
  createdAt: string;
}

export interface HotProspect {
  id: string;
  companyName: string;
  topic: string;
  strength: "strong" | "moderate" | "weak";
  detectedAt: string;
  score: number;
}

export interface DashboardData {
  pipelineCounts: Record<string, number>;
  conversionRates: ConversionRate[];
  topProspects: TopProspect[];
  requiresAction: ActionItem[];
  hotProspects: HotProspect[];
}
