"use client";

import { useState, useEffect } from "react";

// Pipeline status types matching the design schema
type PipelineStatus =
  | "Drafted"
  | "Sent"
  | "Replied"
  | "Meeting Booked"
  | "Proposal Requested"
  | "Converted"
  | "Won"
  | "Lost"
  | "Abandoned";

type Beneficiary = "consultant" | "team";
type ScoreTier = "A" | "B" | "C" | "D";

interface PipelineRecord {
  id: string;
  companyName: string;
  contactName: string;
  status: PipelineStatus;
  beneficiary: Beneficiary;
  opportunityType: string;
  scoreTier: ScoreTier;
  score: number;
  isPartialScore: boolean;
  lastActivity: string;
  touchpointCount: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Placeholder data — shown when backend has no real records
const PLACEHOLDER_RECORDS: PipelineRecord[] = [
  {
    id: "1",
    companyName: "Acme Corp",
    contactName: "Jane Smith",
    status: "Drafted",
    beneficiary: "consultant",
    opportunityType: "cold_outreach",
    scoreTier: "A",
    score: 87,
    isPartialScore: false,
    lastActivity: "2024-01-15",
    touchpointCount: 0,
  },
  {
    id: "2",
    companyName: "TechStart Ltd",
    contactName: "John Doe",
    status: "Sent",
    beneficiary: "consultant",
    opportunityType: "cold_outreach",
    scoreTier: "B",
    score: 62,
    isPartialScore: true,
    lastActivity: "2024-01-14",
    touchpointCount: 1,
  },
  {
    id: "3",
    companyName: "Global Services Inc",
    contactName: "Alice Johnson",
    status: "Replied",
    beneficiary: "team",
    opportunityType: "contract",
    scoreTier: "A",
    score: 78,
    isPartialScore: false,
    lastActivity: "2024-01-13",
    touchpointCount: 3,
  },
  {
    id: "4",
    companyName: "DataFlow Systems",
    contactName: "Bob Wilson",
    status: "Meeting Booked",
    beneficiary: "consultant",
    opportunityType: "cold_outreach",
    scoreTier: "B",
    score: 55,
    isPartialScore: false,
    lastActivity: "2024-01-12",
    touchpointCount: 4,
  },
  {
    id: "5",
    companyName: "CloudNine Solutions",
    contactName: "Carol Davis",
    status: "Sent",
    beneficiary: "team",
    opportunityType: "contract",
    scoreTier: "C",
    score: 42,
    isPartialScore: true,
    lastActivity: "2024-01-11",
    touchpointCount: 2,
  },
  {
    id: "6",
    companyName: "InnovateTech",
    contactName: "David Lee",
    status: "Proposal Requested",
    beneficiary: "team",
    opportunityType: "contract",
    scoreTier: "A",
    score: 91,
    isPartialScore: false,
    lastActivity: "2024-01-10",
    touchpointCount: 5,
  },
  {
    id: "7",
    companyName: "NextWave Digital",
    contactName: "Eva Martinez",
    status: "Drafted",
    beneficiary: "consultant",
    opportunityType: "job_listing",
    scoreTier: "D",
    score: 18,
    isPartialScore: true,
    lastActivity: "2024-01-09",
    touchpointCount: 0,
  },
  {
    id: "8",
    companyName: "PrimeStack",
    contactName: "Frank Chen",
    status: "Converted",
    beneficiary: "consultant",
    opportunityType: "cold_outreach",
    scoreTier: "A",
    score: 95,
    isPartialScore: false,
    lastActivity: "2024-01-08",
    touchpointCount: 6,
  },
];

const PIPELINE_STATUSES: PipelineStatus[] = [
  "Drafted",
  "Sent",
  "Replied",
  "Meeting Booked",
  "Proposal Requested",
  "Converted",
  "Won",
  "Lost",
  "Abandoned",
];

const OPPORTUNITY_TYPES = [
  { id: "all", label: "All Types" },
  { id: "job_site", label: "Job Sites" },
  { id: "company", label: "Companies" },
  { id: "cold_outreach_consultant", label: "Cold Outreach (Consultant)" },
  { id: "cold_outreach_team", label: "Cold Outreach (Team)" },
  { id: "project_marketplace", label: "Project Marketplaces" },
];

function TierBadge({ tier, score, isPartial }: { tier: ScoreTier; score: number; isPartial: boolean }) {
  const colors: Record<ScoreTier, string> = {
    A: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
    B: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
    C: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
    D: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
  };

  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${colors[tier]}`}>
      {tier}-{score}
      {isPartial && (
        <span title="Partial score - some factors missing" className="opacity-60">⚠</span>
      )}
    </span>
  );
}

function StatusBadge({ status }: { status: PipelineStatus }) {
  const colors: Record<PipelineStatus, string> = {
    Drafted: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
    Sent: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    Replied: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
    "Meeting Booked": "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400",
    "Proposal Requested": "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
    Converted: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    Won: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    Lost: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    Abandoned: "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500",
  };

  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colors[status]}`}>
      {status}
    </span>
  );
}

function ConnectionIndicator({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-1.5 text-xs" title={connected ? "Real-time updates active" : "Disconnected"}>
      <span className={`h-2 w-2 rounded-full ${connected ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
      <span className="text-[rgb(var(--muted-foreground))]">
        {connected ? "Live" : "Offline"}
      </span>
    </div>
  );
}

export default function PipelinePage() {
  const [beneficiary, setBeneficiary] = useState<Beneficiary | "all">("all");
  const [statusFilter, setStatusFilter] = useState<PipelineStatus | "all">("all");
  const [opportunityType, setOpportunityType] = useState("all");
  const [viewMode, setViewMode] = useState<"board" | "list">("board");
  const [wsConnected, setWsConnected] = useState(true);
  const [selectedRecord, setSelectedRecord] = useState<PipelineRecord | null>(null);
  const [records, setRecords] = useState<PipelineRecord[]>(PLACEHOLDER_RECORDS);
  const [sortField, setSortField] = useState<"status" | "score" | "lastActivity" | null>(null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  // Fetch real data from backend
  useEffect(() => {
    async function fetchPipeline() {
      try {
        const params = new URLSearchParams({ page: "1", page_size: "100" });
        if (beneficiary !== "all") params.set("beneficiary_id", beneficiary);
        if (statusFilter !== "all") params.set("status", statusFilter);
        if (opportunityType !== "all") params.set("opportunity_type", opportunityType);

        const response = await fetch(`${API_BASE}/api/pipeline?${params}`, {
          signal: AbortSignal.timeout(3000),
        });

        if (response.ok) {
          const data = await response.json();
          if (data.items && data.items.length > 0) {
            // Map backend response to frontend format
            const mapped: PipelineRecord[] = data.items.map((item: any) => ({
              id: item.id,
              companyName: item.company_name || "Unknown Company",
              contactName: "",
              status: item.current_status as PipelineStatus,
              beneficiary: item.beneficiary_id as Beneficiary,
              opportunityType: item.opportunity_type_id,
              scoreTier: "C" as ScoreTier,
              score: 0,
              isPartialScore: true,
              lastActivity: item.updated_at?.split("T")[0] || "",
              touchpointCount: 0,
            }));
            setRecords(mapped);
            return;
          }
        }
        // Fall back to placeholder
        setRecords(PLACEHOLDER_RECORDS);
      } catch {
        setRecords(PLACEHOLDER_RECORDS);
      }
    }
    fetchPipeline();
  }, [beneficiary, statusFilter, opportunityType]);

  // Simulate WebSocket connection status
  useEffect(() => {
    const interval = setInterval(() => {
      setWsConnected(true); // Placeholder - always connected
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  // Sort logic
  const handleSort = (field: "status" | "score" | "lastActivity") => {
    if (sortField === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  };

  const filteredRecords = records.filter((record) => {
    if (beneficiary !== "all" && record.beneficiary !== beneficiary) return false;
    if (statusFilter !== "all" && record.status !== statusFilter) return false;
    if (opportunityType !== "all" && record.opportunityType !== opportunityType) return false;
    return true;
  });

  // Apply sorting
  const sortedRecords = [...filteredRecords].sort((a, b) => {
    if (!sortField) return 0;
    const dir = sortDirection === "asc" ? 1 : -1;
    if (sortField === "score") return (a.score - b.score) * dir;
    if (sortField === "status") {
      const statusOrder = PIPELINE_STATUSES.indexOf(a.status) - PIPELINE_STATUSES.indexOf(b.status);
      return statusOrder * dir;
    }
    if (sortField === "lastActivity") return a.lastActivity.localeCompare(b.lastActivity) * dir;
    return 0;
  });

  const groupedByStatus = PIPELINE_STATUSES.reduce(
    (acc, status) => {
      acc[status] = filteredRecords.filter((r) => r.status === status);
      return acc;
    },
    {} as Record<PipelineStatus, PipelineRecord[]>
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 tablet:flex-row tablet:items-center tablet:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[rgb(var(--foreground))]">Pipeline</h1>
          <p className="text-sm text-[rgb(var(--muted-foreground))]">
            Track prospects through your outreach pipeline
          </p>
        </div>
        <ConnectionIndicator connected={wsConnected} />
      </div>

      {/* Live region for real-time pipeline updates */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        Pipeline view showing {filteredRecords.length} records
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap items-center gap-3">
          {/* Beneficiary Toggle */}
          <fieldset>
            <legend className="sr-only">Filter by beneficiary</legend>
            <div className="flex rounded-lg border border-[rgb(var(--border))] overflow-hidden" role="radiogroup" aria-label="Beneficiary filter">
              {(["all", "consultant", "team"] as const).map((b) => (
                <button
                  key={b}
                  role="radio"
                  aria-checked={beneficiary === b}
                  onClick={() => setBeneficiary(b)}
                  className={`min-h-[44px] px-3 py-1.5 text-sm font-medium transition-colors
                    focus-visible:outline-2 focus-visible:outline-offset-2
                    focus-visible:outline-[rgb(var(--focus-ring))]
                    ${
                      beneficiary === b
                        ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                        : "text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))]"
                    }`}
                >
                  {b === "all" ? "All" : b === "consultant" ? "Consultant" : "Team"}
                </button>
              ))}
            </div>
          </fieldset>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as PipelineStatus | "all")}
            className="min-h-[44px] rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--card))] px-3 py-1.5 text-sm text-[rgb(var(--foreground))]
                       focus-visible:outline-2 focus-visible:outline-offset-2
                       focus-visible:outline-[rgb(var(--focus-ring))]"
            aria-label="Filter by status"
          >
            <option value="all">All Statuses</option>
            {PIPELINE_STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>

          {/* Opportunity Type Filter */}
          <select
            value={opportunityType}
            onChange={(e) => setOpportunityType(e.target.value)}
            className="min-h-[44px] rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--card))] px-3 py-1.5 text-sm text-[rgb(var(--foreground))]
                       focus-visible:outline-2 focus-visible:outline-offset-2
                       focus-visible:outline-[rgb(var(--focus-ring))]"
            aria-label="Filter by opportunity type"
          >
            {OPPORTUNITY_TYPES.map((ot) => (
              <option key={ot.id} value={ot.id}>{ot.label}</option>
            ))}
          </select>

          {/* View Toggle */}
          <div className="ml-auto flex rounded-lg border border-[rgb(var(--border))] overflow-hidden" role="radiogroup" aria-label="View mode">
            <button
              onClick={() => setViewMode("board")}
              role="radio"
              aria-checked={viewMode === "board"}
              className={`min-h-[44px] px-3 py-1.5 text-sm
                focus-visible:outline-2 focus-visible:outline-offset-2
                focus-visible:outline-[rgb(var(--focus-ring))]
                ${
                  viewMode === "board"
                    ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                    : "text-[rgb(var(--muted-foreground))]"
                }`}
              aria-label="Board view"
            >
              Board
            </button>
            <button
              onClick={() => setViewMode("list")}
              role="radio"
              aria-checked={viewMode === "list"}
              className={`min-h-[44px] px-3 py-1.5 text-sm
                focus-visible:outline-2 focus-visible:outline-offset-2
                focus-visible:outline-[rgb(var(--focus-ring))]
                ${
                  viewMode === "list"
                    ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                    : "text-[rgb(var(--muted-foreground))]"
                }`}
              aria-label="List view"
            >
              List
            </button>
          </div>
        </div>
      </div>

      {/* Board View */}
      {viewMode === "board" && (
        <div className="overflow-x-auto pb-4">
          <div className="flex gap-4 min-w-max">
            {PIPELINE_STATUSES.filter(
              (s) => statusFilter === "all" || s === statusFilter
            ).map((status) => (
              <div key={status} className="w-72 flex-shrink-0">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-[rgb(var(--foreground))]">{status}</h3>
                  <span className="rounded-full bg-[rgb(var(--muted))] px-2 py-0.5 text-xs text-[rgb(var(--muted-foreground))]">
                    {groupedByStatus[status]?.length || 0}
                  </span>
                </div>
                <div className="space-y-2">
                  {(groupedByStatus[status] || []).map((record) => (
                    <button
                      key={record.id}
                      onClick={() => setSelectedRecord(record)}
                      className="card w-full text-left hover:ring-2 hover:ring-[rgb(var(--accent))] transition-all cursor-pointer"
                    >
                      <div className="flex items-start justify-between">
                        <p className="text-sm font-medium text-[rgb(var(--foreground))]">
                          {record.companyName}
                        </p>
                        <TierBadge tier={record.scoreTier} score={record.score} isPartial={record.isPartialScore} />
                      </div>
                      <p className="mt-1 text-xs text-[rgb(var(--muted-foreground))]">
                        {record.contactName}
                      </p>
                      <div className="mt-2 flex items-center justify-between text-xs text-[rgb(var(--muted-foreground))]">
                        <span>{record.touchpointCount} touchpoints</span>
                        <span>{record.lastActivity}</span>
                      </div>
                    </button>
                  ))}
                  {(groupedByStatus[status] || []).length === 0 && (
                    <div className="rounded-lg border-2 border-dashed border-[rgb(var(--border))] p-4 text-center">
                      <p className="text-xs text-[rgb(var(--muted-foreground))]">No records</p>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* List View */}
      {viewMode === "list" && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[rgb(var(--border))]">
                <th className="px-4 py-3 text-left font-medium text-[rgb(var(--muted-foreground))]">Company</th>
                <th className="px-4 py-3 text-left font-medium text-[rgb(var(--muted-foreground))]">Contact</th>
                <th
                  className="px-4 py-3 text-left font-medium text-[rgb(var(--muted-foreground))] cursor-pointer hover:text-[rgb(var(--foreground))]"
                  onClick={() => handleSort("status")}
                >
                  Status {sortField === "status" ? (sortDirection === "asc" ? "↑" : "↓") : ""}
                </th>
                <th
                  className="px-4 py-3 text-left font-medium text-[rgb(var(--muted-foreground))] cursor-pointer hover:text-[rgb(var(--foreground))]"
                  onClick={() => handleSort("score")}
                >
                  Score {sortField === "score" ? (sortDirection === "asc" ? "↑" : "↓") : ""}
                </th>
                <th className="px-4 py-3 text-left font-medium text-[rgb(var(--muted-foreground))]">Type</th>
                <th
                  className="px-4 py-3 text-left font-medium text-[rgb(var(--muted-foreground))] cursor-pointer hover:text-[rgb(var(--foreground))]"
                  onClick={() => handleSort("lastActivity")}
                >
                  Last Activity {sortField === "lastActivity" ? (sortDirection === "asc" ? "↑" : "↓") : ""}
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedRecords.map((record) => (
                <tr
                  key={record.id}
                  onClick={() => setSelectedRecord(record)}
                  className="border-b border-[rgb(var(--border))] hover:bg-[rgb(var(--muted))] cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-[rgb(var(--foreground))]">{record.companyName}</td>
                  <td className="px-4 py-3 text-[rgb(var(--muted-foreground))]">{record.contactName}</td>
                  <td className="px-4 py-3"><StatusBadge status={record.status} /></td>
                  <td className="px-4 py-3"><TierBadge tier={record.scoreTier} score={record.score} isPartial={record.isPartialScore} /></td>
                  <td className="px-4 py-3 text-[rgb(var(--muted-foreground))] capitalize">{record.opportunityType.replace("_", " ")}</td>
                  <td className="px-4 py-3 text-[rgb(var(--muted-foreground))]">{record.lastActivity}</td>
                </tr>
              ))}
              {sortedRecords.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-[rgb(var(--muted-foreground))]">
                    No records match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail Panel (slide-over) */}
      {selectedRecord && (
        <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Prospect detail">
          <div className="absolute inset-0 bg-black/50" onClick={() => setSelectedRecord(null)} />
          <div className="relative w-full max-w-md bg-[rgb(var(--card))] shadow-xl overflow-y-auto">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[rgb(var(--border))] bg-[rgb(var(--card))] px-6 py-4">
              <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">Prospect Detail</h2>
              <button
                onClick={() => setSelectedRecord(null)}
                className="rounded-lg p-1 hover:bg-[rgb(var(--muted))] text-[rgb(var(--muted-foreground))]"
                aria-label="Close detail panel"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <h3 className="text-xl font-bold text-[rgb(var(--foreground))]">{selectedRecord.companyName}</h3>
                <p className="text-sm text-[rgb(var(--muted-foreground))]">{selectedRecord.contactName}</p>
              </div>
              <div className="flex gap-2">
                <StatusBadge status={selectedRecord.status} />
                <TierBadge tier={selectedRecord.scoreTier} score={selectedRecord.score} isPartial={selectedRecord.isPartialScore} />
              </div>
              <div className="space-y-3 pt-4 border-t border-[rgb(var(--border))]">
                <div className="flex justify-between">
                  <span className="text-sm text-[rgb(var(--muted-foreground))]">Beneficiary</span>
                  <span className="text-sm font-medium text-[rgb(var(--foreground))] capitalize">{selectedRecord.beneficiary}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-[rgb(var(--muted-foreground))]">Opportunity Type</span>
                  <span className="text-sm font-medium text-[rgb(var(--foreground))] capitalize">{selectedRecord.opportunityType.replace("_", " ")}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-[rgb(var(--muted-foreground))]">Touchpoints</span>
                  <span className="text-sm font-medium text-[rgb(var(--foreground))]">{selectedRecord.touchpointCount}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-[rgb(var(--muted-foreground))]">Last Activity</span>
                  <span className="text-sm font-medium text-[rgb(var(--foreground))]">{selectedRecord.lastActivity}</span>
                </div>
              </div>
              <div className="pt-4 border-t border-[rgb(var(--border))]">
                <h4 className="text-sm font-semibold text-[rgb(var(--foreground))] mb-2">Touchpoint History</h4>
                <p className="text-xs text-[rgb(var(--muted-foreground))]">
                  Touchpoint history will be displayed here when connected to the backend.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
