"use client";

import { useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  FunnelChart,
  Funnel,
  LabelList,
  Cell,
} from "recharts";

type PeriodDays = 7 | 30 | 90;
type Beneficiary = "all" | "consultant" | "team";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// All opportunity types from the schema
const OPPORTUNITY_TYPES = [
  { id: "all", label: "All Types" },
  { id: "job_site", label: "Job Sites" },
  { id: "company", label: "Companies" },
  { id: "cold_outreach_consultant", label: "Cold Outreach (Consultant)" },
  { id: "cold_outreach_team", label: "Cold Outreach (Team)" },
  { id: "project_marketplace", label: "Project Marketplaces" },
];

// Placeholder funnel data
const FUNNEL_DATA = [
  { name: "Discovered", value: 245, fill: "#6366f1" },
  { name: "Drafted", value: 180, fill: "#8b5cf6" },
  { name: "Sent", value: 142, fill: "#a855f7" },
  { name: "Replied", value: 48, fill: "#d946ef" },
  { name: "Meeting Booked", value: 22, fill: "#ec4899" },
  { name: "Converted/Won", value: 12, fill: "#10b981" },
];

// A/B test results placeholder
const AB_TEST_RESULTS = [
  {
    sequenceName: "Tech Outreach v2",
    step: 1,
    variants: [
      { id: "A", sends: 125, openRate: 42.3, clickRate: 8.1, replyRate: 5.6, isWinner: true, isInconclusive: false },
      { id: "B", sends: 118, openRate: 38.9, clickRate: 6.2, replyRate: 3.4, isWinner: false, isInconclusive: false },
    ],
  },
  {
    sequenceName: "Enterprise Cold",
    step: 1,
    variants: [
      { id: "A", sends: 45, openRate: 35.0, clickRate: 5.0, replyRate: 4.0, isWinner: false, isInconclusive: true },
      { id: "B", sends: 42, openRate: 36.2, clickRate: 5.5, replyRate: 4.5, isWinner: false, isInconclusive: true },
      { id: "C", sends: 40, openRate: 33.1, clickRate: 4.8, replyRate: 3.8, isWinner: false, isInconclusive: true },
    ],
  },
];

// Channel effectiveness placeholder
const CHANNEL_DATA = [
  { source: "Apollo", sequence: "Tech Outreach v2", beneficiary: "Consultant", responseRate: 5.6, meetingRate: 2.1, conversionRate: 1.2, isLowConfidence: false },
  { source: "Adzuna", sequence: "Job Apply", beneficiary: "Consultant", responseRate: 12.3, meetingRate: 4.5, conversionRate: 2.8, isLowConfidence: false },
  { source: "Apollo", sequence: "Enterprise Cold", beneficiary: "Team", responseRate: 4.2, meetingRate: 1.8, conversionRate: 0.9, isLowConfidence: false },
  { source: "Internet Search", sequence: "Targeted Outreach", beneficiary: "Team", responseRate: 3.1, meetingRate: 0.0, conversionRate: 0.0, isLowConfidence: true },
];

// Monthly trend data (12 months)
const MONTHLY_TREND = [
  { month: "Feb 23", discovered: 12, sent: 8, responses: 2, outcomes: 0 },
  { month: "Mar 23", discovered: 25, sent: 18, responses: 5, outcomes: 1 },
  { month: "Apr 23", discovered: 34, sent: 28, responses: 8, outcomes: 2 },
  { month: "May 23", discovered: 45, sent: 35, responses: 10, outcomes: 3 },
  { month: "Jun 23", discovered: 38, sent: 30, responses: 9, outcomes: 2 },
  { month: "Jul 23", discovered: 52, sent: 42, responses: 14, outcomes: 4 },
  { month: "Aug 23", discovered: 48, sent: 38, responses: 11, outcomes: 3 },
  { month: "Sep 23", discovered: 60, sent: 50, responses: 16, outcomes: 5 },
  { month: "Oct 23", discovered: 55, sent: 45, responses: 13, outcomes: 4 },
  { month: "Nov 23", discovered: 70, sent: 58, responses: 18, outcomes: 6 },
  { month: "Dec 23", discovered: 42, sent: 30, responses: 8, outcomes: 2 },
  { month: "Jan 24", discovered: 65, sent: 52, responses: 15, outcomes: 5 },
];

// Effort metrics
const EFFORT_METRICS = {
  discovered: 245,
  sent: 180,
  responses: 48,
  outcomes: 12,
};

export default function AnalyticsPage() {
  const [period, setPeriod] = useState<PeriodDays>(30);
  const [beneficiary, setBeneficiary] = useState<Beneficiary>("all");
  const [opportunityType, setOpportunityType] = useState("all");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 tablet:flex-row tablet:items-center tablet:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[rgb(var(--foreground))]">Analytics</h1>
          <p className="text-sm text-[rgb(var(--muted-foreground))]">
            Conversion funnel, A/B results, and performance metrics
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap items-center gap-3">
          {/* Period Selector */}
          <div className="flex rounded-lg border border-[rgb(var(--border))] overflow-hidden" role="radiogroup" aria-label="Time period">
            {([7, 30, 90] as PeriodDays[]).map((p) => (
              <button
                key={p}
                role="radio"
                aria-checked={period === p}
                onClick={() => setPeriod(p)}
                className={`min-h-[44px] px-3 py-1.5 text-sm font-medium transition-colors
                  focus-visible:outline-2 focus-visible:outline-offset-2
                  focus-visible:outline-[rgb(var(--focus-ring))]
                  ${
                    period === p
                      ? "bg-[rgb(var(--accent))] text-[rgb(var(--accent-foreground))]"
                      : "text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))]"
                  }`}
              >
                {p}d
              </button>
            ))}
          </div>

          {/* Beneficiary Filter */}
          <select
            value={beneficiary}
            onChange={(e) => setBeneficiary(e.target.value as Beneficiary)}
            className="min-h-[44px] rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--card))] px-3 py-1.5 text-sm text-[rgb(var(--foreground))]
                       focus-visible:outline-2 focus-visible:outline-offset-2
                       focus-visible:outline-[rgb(var(--focus-ring))]"
            aria-label="Filter by beneficiary"
          >
            <option value="all">All Beneficiaries</option>
            <option value="consultant">Consultant</option>
            <option value="team">Team</option>
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
        </div>
      </div>

      {/* Effort Metrics Summary */}
      <div className="grid gap-4 tablet:grid-cols-2 desktop:grid-cols-4">
        {[
          { label: "Discovered", value: EFFORT_METRICS.discovered, color: "text-blue-600 dark:text-blue-400" },
          { label: "Sent", value: EFFORT_METRICS.sent, color: "text-purple-600 dark:text-purple-400" },
          { label: "Responses", value: EFFORT_METRICS.responses, color: "text-pink-600 dark:text-pink-400" },
          { label: "Outcomes", value: EFFORT_METRICS.outcomes, color: "text-green-600 dark:text-green-400" },
        ].map((metric) => (
          <div key={metric.label} className="card">
            <p className="text-sm text-[rgb(var(--muted-foreground))]">{metric.label}</p>
            <p className={`mt-1 text-2xl font-bold ${metric.color}`}>{metric.value}</p>
            <p className="mt-1 text-xs text-[rgb(var(--muted-foreground))]">Last {period} days</p>
          </div>
        ))}
      </div>

      {/* Funnel Chart */}
      <div className="card">
        <h2 className="text-lg font-semibold text-[rgb(var(--foreground))] mb-4">Conversion Funnel</h2>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={FUNNEL_DATA} layout="vertical" margin={{ top: 5, right: 30, left: 80, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis type="number" />
              <YAxis type="category" dataKey="name" width={100} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "rgb(var(--card))",
                  border: "1px solid rgb(var(--border))",
                  borderRadius: "0.5rem",
                  color: "rgb(var(--foreground))",
                }}
              />
              <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                {FUNNEL_DATA.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 tablet:grid-cols-3 desktop:grid-cols-6">
          {FUNNEL_DATA.map((stage, i) => {
            const dropOff = i > 0 ? ((1 - stage.value / FUNNEL_DATA[i - 1].value) * 100).toFixed(1) : null;
            return (
              <div key={stage.name} className="text-center">
                <p className="text-xs text-[rgb(var(--muted-foreground))]">{stage.name}</p>
                <p className="text-sm font-semibold text-[rgb(var(--foreground))]">{stage.value}</p>
                {dropOff && (
                  <p className="text-xs text-red-500">-{dropOff}%</p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* A/B Test Results */}
      <div className="card">
        <h2 className="text-lg font-semibold text-[rgb(var(--foreground))] mb-4">A/B Test Results</h2>
        <div className="space-y-6">
          {AB_TEST_RESULTS.map((test) => (
            <div key={`${test.sequenceName}-${test.step}`} className="border-b border-[rgb(var(--border))] pb-4 last:border-0 last:pb-0">
              <div className="flex items-center gap-2 mb-3">
                <h3 className="text-sm font-medium text-[rgb(var(--foreground))]">{test.sequenceName}</h3>
                <span className="text-xs text-[rgb(var(--muted-foreground))]">Step {test.step}</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-[rgb(var(--muted-foreground))]">
                      <th className="pb-2 pr-4">Variant</th>
                      <th className="pb-2 pr-4">Sends</th>
                      <th className="pb-2 pr-4">Open Rate</th>
                      <th className="pb-2 pr-4">Click Rate</th>
                      <th className="pb-2 pr-4">Reply Rate</th>
                      <th className="pb-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {test.variants.map((variant) => (
                      <tr key={variant.id} className="border-t border-[rgb(var(--border))]">
                        <td className="py-2 pr-4 font-medium text-[rgb(var(--foreground))]">
                          Variant {variant.id}
                        </td>
                        <td className="py-2 pr-4 text-[rgb(var(--muted-foreground))]">{variant.sends}</td>
                        <td className="py-2 pr-4 text-[rgb(var(--muted-foreground))]">{variant.openRate}%</td>
                        <td className="py-2 pr-4 text-[rgb(var(--muted-foreground))]">{variant.clickRate}%</td>
                        <td className="py-2 pr-4 font-medium text-[rgb(var(--foreground))]">{variant.replyRate}%</td>
                        <td className="py-2">
                          {variant.isWinner && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
                              🏆 Winner
                            </span>
                          )}
                          {variant.isInconclusive && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
                              ⏳ Inconclusive
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Channel Effectiveness */}
      <div className="card">
        <h2 className="text-lg font-semibold text-[rgb(var(--foreground))] mb-4">Channel Effectiveness</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[rgb(var(--border))] text-left text-xs text-[rgb(var(--muted-foreground))]">
                <th className="pb-3 pr-4">Source</th>
                <th className="pb-3 pr-4">Sequence</th>
                <th className="pb-3 pr-4">Beneficiary</th>
                <th className="pb-3 pr-4">Response Rate</th>
                <th className="pb-3 pr-4">Meeting Rate</th>
                <th className="pb-3">Conversion Rate</th>
              </tr>
            </thead>
            <tbody>
              {CHANNEL_DATA.map((row, i) => (
                <tr key={i} className="border-b border-[rgb(var(--border))]">
                  <td className="py-3 pr-4 font-medium text-[rgb(var(--foreground))]">{row.source}</td>
                  <td className="py-3 pr-4 text-[rgb(var(--muted-foreground))]">{row.sequence}</td>
                  <td className="py-3 pr-4 text-[rgb(var(--muted-foreground))]">{row.beneficiary}</td>
                  <td className="py-3 pr-4 text-[rgb(var(--foreground))]">
                    {row.isLowConfidence ? <span className="opacity-50">{row.responseRate}%*</span> : `${row.responseRate}%`}
                  </td>
                  <td className="py-3 pr-4 text-[rgb(var(--foreground))]">
                    {row.isLowConfidence ? <span className="opacity-50">{row.meetingRate}%*</span> : `${row.meetingRate}%`}
                  </td>
                  <td className="py-3 text-[rgb(var(--foreground))]">
                    {row.isLowConfidence ? <span className="opacity-50">{row.conversionRate}%*</span> : `${row.conversionRate}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-[rgb(var(--muted-foreground))]">
            * Low confidence — fewer than 10 prospects in channel
          </p>
        </div>
      </div>

      {/* 12-Month Trend */}
      <div className="card">
        <h2 className="text-lg font-semibold text-[rgb(var(--foreground))] mb-4">12-Month Trend</h2>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={MONTHLY_TREND} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="month" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "rgb(var(--card))",
                  border: "1px solid rgb(var(--border))",
                  borderRadius: "0.5rem",
                  color: "rgb(var(--foreground))",
                }}
              />
              <Legend />
              <Line type="monotone" dataKey="discovered" stroke="#6366f1" strokeWidth={2} dot={{ r: 3 }} name="Discovered" />
              <Line type="monotone" dataKey="sent" stroke="#a855f7" strokeWidth={2} dot={{ r: 3 }} name="Sent" />
              <Line type="monotone" dataKey="responses" stroke="#ec4899" strokeWidth={2} dot={{ r: 3 }} name="Responses" />
              <Line type="monotone" dataKey="outcomes" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} name="Outcomes" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
