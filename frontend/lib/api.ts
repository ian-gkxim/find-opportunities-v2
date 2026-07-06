/**
 * API Client for schema-driven navigation and backend communication.
 *
 * This module fetches navigation structure from the backend's /api/navigation
 * endpoint (powered by SchemaRegistry.derive_navigation()). Until the backend
 * is connected, it provides a hardcoded structure matching config/schema.yaml.
 *
 * Requirements: 12.2, 12.7 — Adding a new beneficiary in the schema YAML
 * derives correct navigation without frontend code changes.
 */

// ============================================================================
// Types — mirrors the backend SchemaRegistry output
// ============================================================================

export interface Beneficiary {
  id: string;
  label: string;
  description: string;
}

export interface OpportunityType {
  id: string;
  label: string;
  beneficiaries: string[];
  find_label: string;
  source_label: string;
  pipeline_states: string[];
}

export interface NavigationStage {
  id: string;
  label: string;
  description: string;
  sub_tabs: BeneficiarySubTab[];
}

export interface BeneficiarySubTab {
  beneficiary_id: string;
  beneficiary_label: string;
  panels: NavigationPanel[];
}

export interface NavigationPanel {
  id: string;
  label: string;
  type: "asset" | "discovery" | "config";
}

export interface SchemaNavigation {
  stages: NavigationStage[];
  beneficiaries: Beneficiary[];
  opportunity_types: OpportunityType[];
}

// ============================================================================
// Hardcoded navigation matching the schema YAML — replaced by API call in prod
// ============================================================================

const SCHEMA_NAVIGATION: SchemaNavigation = {
  beneficiaries: [
    {
      id: "consultant",
      label: "Consultant",
      description: "Individual GKIM consultants deployed against opportunities",
    },
    {
      id: "team",
      label: "Team",
      description: "GKIM as a firm pursuing project and contract opportunities",
    },
  ],
  opportunity_types: [
    {
      id: "job_site",
      label: "Job Sites",
      beneficiaries: ["consultant"],
      find_label: "From Job Sites",
      source_label: "Manage Job Sites",
      pipeline_states: ["Personalise", "Approve", "Applied", "Interview", "Offer", "Accepted", "Rejected", "Abandoned"],
    },
    {
      id: "company",
      label: "Companies",
      beneficiaries: ["consultant"],
      find_label: "From Companies",
      source_label: "Manage Company Search Criteria",
      pipeline_states: ["Personalise", "Approve", "Applied", "Interview", "Offer", "Accepted", "Rejected", "Abandoned"],
    },
    {
      id: "project_marketplace",
      label: "Project Marketplaces",
      beneficiaries: ["team"],
      find_label: "From Marketplaces",
      source_label: "Manage Project Marketplaces",
      pipeline_states: ["Expression of Interest", "Proposal Submitted", "Shortlisted", "Won", "Lost"],
    },
    {
      id: "cold_outreach",
      label: "Target Companies",
      beneficiaries: ["consultant"],
      find_label: "From Cold Outreach",
      source_label: "Manage Outreach Criteria",
      pipeline_states: ["Drafted", "Approved", "Sent", "Replied", "Meeting Booked", "Converted", "Rejected", "Abandoned"],
    },
    {
      id: "team_cold_outreach",
      label: "Team Cold Outreach",
      beneficiaries: ["team"],
      find_label: "From Team Outreach",
      source_label: "Manage Team Outreach Criteria",
      pipeline_states: ["Drafted", "Sent", "Replied", "Proposal Requested", "Won", "Lost"],
    },
  ],
  stages: [
    {
      id: "understand",
      label: "Understand Us",
      description: "Define who we are and what we offer",
      sub_tabs: [
        {
          beneficiary_id: "consultant",
          beneficiary_label: "Consultant",
          panels: [
            { id: "baseline", label: "Establish Baseline", type: "asset" },
            { id: "offerings", label: "Offerings", type: "asset" },
            { id: "instructions", label: "Customisation Instructions", type: "asset" },
          ],
        },
        {
          beneficiary_id: "team",
          beneficiary_label: "Team",
          panels: [
            { id: "baseline", label: "Establish Baseline", type: "asset" },
            { id: "offerings", label: "Offerings", type: "asset" },
          ],
        },
      ],
    },
    {
      id: "configure",
      label: "Define Where to Look",
      description: "Configure opportunity sources per type",
      sub_tabs: [
        {
          beneficiary_id: "consultant",
          beneficiary_label: "Consultant",
          panels: [
            { id: "job_sites", label: "Manage Job Sites", type: "config" },
            { id: "company_search", label: "Manage Company Search Criteria", type: "config" },
            { id: "outreach_criteria", label: "Manage Outreach Criteria", type: "config" },
          ],
        },
        {
          beneficiary_id: "team",
          beneficiary_label: "Team",
          panels: [
            { id: "project_marketplaces", label: "Manage Project Marketplaces", type: "config" },
            { id: "team_outreach_criteria", label: "Manage Team Outreach Criteria", type: "config" },
          ],
        },
      ],
    },
    {
      id: "find",
      label: "Find Prospects",
      description: "Discover opportunities from configured sources",
      sub_tabs: [
        {
          beneficiary_id: "consultant",
          beneficiary_label: "Consultant",
          panels: [
            { id: "from_job_sites", label: "From Job Sites", type: "discovery" },
            { id: "from_companies", label: "From Companies", type: "discovery" },
            { id: "from_cold_outreach", label: "From Cold Outreach", type: "discovery" },
          ],
        },
        {
          beneficiary_id: "team",
          beneficiary_label: "Team",
          panels: [
            { id: "from_marketplaces", label: "From Marketplaces", type: "discovery" },
            { id: "from_team_outreach", label: "From Team Outreach", type: "discovery" },
          ],
        },
      ],
    },
  ],
};

// ============================================================================
// API Client
// ============================================================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class APIClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  /**
   * Fetch schema-derived navigation from the backend.
   * Falls back to hardcoded navigation if backend is unavailable.
   */
  async fetchNavigation(): Promise<SchemaNavigation> {
    try {
      const response = await fetch(`${this.baseUrl}/api/navigation`, {
        method: "GET",
        headers: { "Content-Type": "application/json" },
        // Short timeout — fall back to local if backend is down
        signal: AbortSignal.timeout(3000),
      });

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      return await response.json();
    } catch {
      // Fallback to hardcoded schema-derived navigation
      return SCHEMA_NAVIGATION;
    }
  }

  /**
   * Get navigation synchronously from the hardcoded schema.
   * Used for initial render before async fetch completes.
   */
  getNavigationSync(): SchemaNavigation {
    return SCHEMA_NAVIGATION;
  }

  /**
   * Get beneficiaries from the schema navigation.
   */
  getBeneficiaries(): Beneficiary[] {
    return SCHEMA_NAVIGATION.beneficiaries;
  }

  /**
   * Get opportunity types for a specific beneficiary.
   */
  getOpportunityTypesForBeneficiary(beneficiaryId: string): OpportunityType[] {
    return SCHEMA_NAVIGATION.opportunity_types.filter(
      (ot) => ot.beneficiaries.includes(beneficiaryId)
    );
  }

  /**
   * Get the navigation stage by ID.
   */
  getStage(stageId: string): NavigationStage | undefined {
    return SCHEMA_NAVIGATION.stages.find((s) => s.id === stageId);
  }

  /**
   * Get sub-tabs for a specific stage.
   */
  getSubTabsForStage(stageId: string): BeneficiarySubTab[] {
    const stage = this.getStage(stageId);
    return stage?.sub_tabs ?? [];
  }

  /**
   * Get pipeline states for a specific opportunity type.
   */
  getPipelineStates(opportunityTypeId: string): string[] {
    const ot = SCHEMA_NAVIGATION.opportunity_types.find(
      (o) => o.id === opportunityTypeId
    );
    return ot?.pipeline_states ?? [];
  }
}

// Singleton API client instance
export const apiClient = new APIClient();

// Export types and navigation data for direct access
export { SCHEMA_NAVIGATION };
