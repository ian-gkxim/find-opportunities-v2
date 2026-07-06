"use client";

import { useState } from "react";

// Integration types
type IntegrationStatus = "connected" | "disconnected" | "error";

interface Integration {
  id: string;
  name: string;
  description: string;
  status: IntegrationStatus;
  lastValidated: string | null;
  usage: number | null; // percentage 0-100
  quota: string | null;
  fields: { key: string; label: string; type: "text" | "password"; placeholder: string }[];
}

interface ScoringWeights {
  firmographic: number;
  technographic: number;
  intent: number;
  llm_relevance: number;
  historical: number;
}

// Placeholder integrations
const INITIAL_INTEGRATIONS: Integration[] = [
  {
    id: "apollo",
    name: "Apollo.io",
    description: "B2B enrichment, contact discovery, and intent signals",
    status: "connected",
    lastValidated: "2024-01-15 14:32",
    usage: 45,
    quota: "450 / 1000 credits",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "Enter Apollo.io API key" },
    ],
  },
  {
    id: "lemlist",
    name: "Lemlist",
    description: "Multi-channel outreach sequences and A/B testing",
    status: "connected",
    lastValidated: "2024-01-15 14:30",
    usage: 22,
    quota: "220 / 1000 emails",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "Enter Lemlist API key" },
    ],
  },
  {
    id: "adzuna",
    name: "Adzuna",
    description: "Job listing discovery and opportunity matching",
    status: "disconnected",
    lastValidated: null,
    usage: null,
    quota: null,
    fields: [
      { key: "app_id", label: "App ID", type: "text", placeholder: "Enter Adzuna App ID" },
      { key: "api_key", label: "API Key", type: "password", placeholder: "Enter Adzuna API key" },
    ],
  },
  {
    id: "gmail",
    name: "Gmail",
    description: "Email sending and reply detection",
    status: "error",
    lastValidated: "2024-01-14 09:15",
    usage: 85,
    quota: "425 / 500 daily sends",
    fields: [
      { key: "client_id", label: "Client ID", type: "text", placeholder: "OAuth Client ID" },
      { key: "client_secret", label: "Client Secret", type: "password", placeholder: "OAuth Client Secret" },
    ],
  },
  {
    id: "llm",
    name: "LLM Provider",
    description: "AI-powered relevance scoring and content generation",
    status: "connected",
    lastValidated: "2024-01-15 14:28",
    usage: 60,
    quota: "60,000 / 100,000 tokens",
    fields: [
      { key: "provider", label: "Provider", type: "text", placeholder: "anthropic or openai" },
      { key: "api_key", label: "API Key", type: "password", placeholder: "Enter provider API key" },
      { key: "model", label: "Model", type: "text", placeholder: "e.g. claude-3-sonnet-20240229" },
    ],
  },
];

function StatusIndicator({ status }: { status: IntegrationStatus }) {
  const config: Record<IntegrationStatus, { color: string; label: string }> = {
    connected: { color: "bg-green-500", label: "Connected" },
    disconnected: { color: "bg-gray-400", label: "Disconnected" },
    error: { color: "bg-red-500", label: "Error" },
  };

  return (
    <div className="flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${config[status].color}`} />
      <span className={`text-xs font-medium ${
        status === "connected" ? "text-green-700 dark:text-green-400" :
        status === "error" ? "text-red-700 dark:text-red-400" :
        "text-gray-500 dark:text-gray-400"
      }`}>
        {config[status].label}
      </span>
    </div>
  );
}

function UsageBar({ usage }: { usage: number }) {
  const getColor = (value: number) => {
    if (value >= 100) return "bg-red-500";
    if (value >= 80) return "bg-yellow-500";
    return "bg-green-500";
  };

  const getLabel = (value: number) => {
    if (value >= 100) return "Critical — API calls blocked";
    if (value >= 80) return "Warning — approaching quota limit";
    return "";
  };

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-[rgb(var(--muted-foreground))]">Usage</span>
        <span className={`font-medium ${
          usage >= 100 ? "text-red-600 dark:text-red-400" :
          usage >= 80 ? "text-yellow-600 dark:text-yellow-400" :
          "text-[rgb(var(--foreground))]"
        }`}>
          {usage}%
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-[rgb(var(--muted))]">
        <div
          className={`h-2 rounded-full transition-all ${getColor(usage)}`}
          style={{ width: `${Math.min(usage, 100)}%` }}
        />
      </div>
      {getLabel(usage) && (
        <p className={`text-xs ${usage >= 100 ? "text-red-600 dark:text-red-400" : "text-yellow-600 dark:text-yellow-400"}`}>
          {getLabel(usage)}
        </p>
      )}
    </div>
  );
}

function IntegrationCard({ integration, onValidate }: { integration: Integration; onValidate: (id: string) => void }) {
  const [showCredentials, setShowCredentials] = useState(false);
  const [validating, setValidating] = useState(false);

  const handleValidate = () => {
    setValidating(true);
    // Simulated validation
    setTimeout(() => {
      setValidating(false);
      onValidate(integration.id);
    }, 2000);
  };

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-[rgb(var(--foreground))]">{integration.name}</h3>
            <StatusIndicator status={integration.status} />
          </div>
          <p className="mt-1 text-sm text-[rgb(var(--muted-foreground))]">{integration.description}</p>
        </div>
        <button
          onClick={() => setShowCredentials(!showCredentials)}
          className="rounded-lg px-3 py-1.5 text-xs font-medium border border-[rgb(var(--border))] text-[rgb(var(--foreground))] hover:bg-[rgb(var(--muted))] transition-colors"
        >
          {showCredentials ? "Hide" : "Configure"}
        </button>
      </div>

      {/* Usage / Quota */}
      {integration.usage !== null && (
        <div className="mt-4">
          <UsageBar usage={integration.usage} />
          {integration.quota && (
            <p className="mt-1 text-xs text-[rgb(var(--muted-foreground))]">{integration.quota}</p>
          )}
        </div>
      )}

      {/* Last validated */}
      {integration.lastValidated && (
        <p className="mt-2 text-xs text-[rgb(var(--muted-foreground))]">
          Last validated: {integration.lastValidated}
        </p>
      )}

      {/* Credential form */}
      {showCredentials && (
        <div className="mt-4 space-y-3 border-t border-[rgb(var(--border))] pt-4">
          {integration.fields.map((field) => (
            <div key={field.key}>
              <label
                htmlFor={`${integration.id}-${field.key}`}
                className="block text-xs font-medium text-[rgb(var(--muted-foreground))] mb-1"
              >
                {field.label}
              </label>
              <input
                id={`${integration.id}-${field.key}`}
                type={field.type}
                placeholder={field.placeholder}
                defaultValue={integration.status === "connected" ? "••••••••••••" : ""}
                className="w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background))] px-3 py-2 text-sm text-[rgb(var(--foreground))] placeholder:text-[rgb(var(--muted-foreground))]"
              />
            </div>
          ))}
          <button
            onClick={handleValidate}
            disabled={validating}
            className="rounded-lg bg-[rgb(var(--accent))] px-4 py-2 text-sm font-medium text-[rgb(var(--accent-foreground))] hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {validating ? "Validating..." : "Validate Credentials"}
          </button>
        </div>
      )}
    </div>
  );
}

function ScoringWeightsPanel() {
  const [weights, setWeights] = useState<ScoringWeights>({
    firmographic: 30,
    technographic: 25,
    intent: 20,
    llm_relevance: 15,
    historical: 10,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const total = Object.values(weights).reduce((sum, w) => sum + w, 0);
  const isValid = total === 100 && Object.values(weights).every((w) => w >= 0 && w <= 100);

  const handleChange = (key: keyof ScoringWeights, value: string) => {
    const num = parseInt(value) || 0;
    setWeights((prev) => ({ ...prev, [key]: Math.min(100, Math.max(0, num)) }));
    setSaved(false);
  };

  const handleSave = () => {
    if (!isValid) return;
    setSaving(true);
    setTimeout(() => {
      setSaving(false);
      setSaved(true);
    }, 1000);
  };

  const factors: { key: keyof ScoringWeights; label: string; description: string }[] = [
    { key: "firmographic", label: "Firmographic", description: "Company size, revenue, industry fit" },
    { key: "technographic", label: "Technographic", description: "Technology stack overlap" },
    { key: "intent", label: "Intent Signals", description: "Active buying intent indicators" },
    { key: "llm_relevance", label: "LLM Relevance", description: "AI-assessed profile match" },
    { key: "historical", label: "Historical", description: "Past conversion rate for similar companies" },
  ];

  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-[rgb(var(--foreground))]">Scoring Weights</h2>
      <p className="mt-1 text-sm text-[rgb(var(--muted-foreground))]">
        Configure how much each factor contributes to the account score. Weights must sum to 100.
      </p>

      <div className="mt-4 space-y-4">
        {factors.map((factor) => (
          <div key={factor.key} className="flex items-center gap-4">
            <div className="flex-1">
              <label
                htmlFor={`weight-${factor.key}`}
                className="block text-sm font-medium text-[rgb(var(--foreground))]"
              >
                {factor.label}
              </label>
              <p className="text-xs text-[rgb(var(--muted-foreground))]">{factor.description}</p>
            </div>
            <div className="flex items-center gap-2">
              <input
                id={`weight-${factor.key}`}
                type="number"
                min={0}
                max={100}
                value={weights[factor.key]}
                onChange={(e) => handleChange(factor.key, e.target.value)}
                className="w-16 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background))] px-2 py-1.5 text-sm text-center text-[rgb(var(--foreground))]"
              />
              <span className="text-sm text-[rgb(var(--muted-foreground))]">%</span>
            </div>
          </div>
        ))}
      </div>

      {/* Sum indicator */}
      <div className={`mt-4 flex items-center justify-between rounded-lg px-3 py-2 ${
        isValid
          ? "bg-green-50 dark:bg-green-900/20"
          : "bg-red-50 dark:bg-red-900/20"
      }`}>
        <span className={`text-sm font-medium ${
          isValid ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"
        }`}>
          Total: {total}%
        </span>
        {!isValid && (
          <span className="text-xs text-red-600 dark:text-red-400">
            Must equal 100%
          </span>
        )}
        {isValid && (
          <span className="text-xs text-green-600 dark:text-green-400">✓ Valid</span>
        )}
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={!isValid || saving}
          className="rounded-lg bg-[rgb(var(--accent))] px-4 py-2 text-sm font-medium text-[rgb(var(--accent-foreground))] hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {saving ? "Saving..." : "Save Weights"}
        </button>
        {saved && (
          <span className="text-sm text-green-600 dark:text-green-400">✓ Saved successfully</span>
        )}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [integrations, setIntegrations] = useState(INITIAL_INTEGRATIONS);

  const handleValidate = (id: string) => {
    setIntegrations((prev) =>
      prev.map((i) =>
        i.id === id ? { ...i, status: "connected" as IntegrationStatus, lastValidated: new Date().toLocaleString() } : i
      )
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[rgb(var(--foreground))]">Settings</h1>
        <p className="text-sm text-[rgb(var(--muted-foreground))]">
          Manage integrations, credentials, and scoring configuration
        </p>
      </div>

      {/* Integrations Section */}
      <div>
        <h2 className="text-lg font-semibold text-[rgb(var(--foreground))] mb-3">Integrations</h2>
        <div className="grid gap-4 desktop:grid-cols-2">
          {integrations.map((integration) => (
            <IntegrationCard
              key={integration.id}
              integration={integration}
              onValidate={handleValidate}
            />
          ))}
        </div>
      </div>

      {/* Scoring Weights */}
      <ScoringWeightsPanel />
    </div>
  );
}
