"use client";

import { useWebSocket } from "@/components/providers/WebSocketProvider";
import type { ConnectionStatus as Status } from "@/lib/websocket";

// ============================================================================
// Connection Status Indicator — visible badge showing WebSocket state
// Requirements: 16.6
// ============================================================================

const STATUS_CONFIG: Record<Status, { label: string; dot: string; text: string }> = {
  connected: {
    label: "Connected",
    dot: "bg-green-500",
    text: "text-green-700 dark:text-green-400",
  },
  disconnected: {
    label: "Disconnected",
    dot: "bg-red-500",
    text: "text-red-700 dark:text-red-400",
  },
  reconnecting: {
    label: "Reconnecting…",
    dot: "bg-yellow-500 animate-pulse",
    text: "text-yellow-700 dark:text-yellow-400",
  },
};

export function ConnectionStatus() {
  const { status, reconnect } = useWebSocket();
  const config = STATUS_CONFIG[status];

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-[rgb(var(--border))] bg-[rgb(var(--card))] px-3 py-1.5 text-xs"
      role="status"
      aria-live="polite"
      aria-label={`WebSocket connection: ${config.label}`}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${config.dot}`} />
      <span className={config.text}>{config.label}</span>
      {status === "disconnected" && (
        <button
          onClick={reconnect}
          className="ml-1 text-[rgb(var(--primary))] underline hover:no-underline focus:outline-none focus:ring-2 focus:ring-[rgb(var(--primary))] focus:ring-offset-1 rounded"
          aria-label="Reconnect to server"
        >
          Retry
        </button>
      )}
    </div>
  );
}
