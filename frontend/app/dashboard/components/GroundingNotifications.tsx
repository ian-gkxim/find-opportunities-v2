"use client";

import { useCallback, useEffect, useState } from "react";
import { useWebSocketMessage } from "@/components/providers/WebSocketProvider";
import type { WebSocketMessage } from "@/lib/websocket";

// ============================================================================
// Grounding Notifications — real-time WebSocket listener for grounding events
// Requirements: 1.4, 3.1
//
// Listens for grounding_blocked and grounding_unverified notifications pushed
// by the backend GroundingNotificationService and displays them in the
// Dashboard "Requires Action" section.
// ============================================================================

export interface GroundingClaim {
  claim_id: string;
  claim_text: string;
  source_span: string;
  source_span_start?: number;
  source_span_end?: number;
  category?: string;
}

export interface GroundingNotification {
  id: string;
  category: "grounding_blocked" | "grounding_unverified";
  title: string;
  message: string;
  material_id: string;
  pipeline_record_id: string;
  severity: "error" | "info";
  ungrounded_count?: number;
  ungrounded_claims?: GroundingClaim[];
  blocked_states?: string[];
  timestamp: string;
}

interface GroundingNotificationsProps {
  /** Callback when a new grounding notification arrives */
  onNotification?: (notification: GroundingNotification) => void;
  /** Maximum notifications to retain in view */
  maxVisible?: number;
}

/**
 * Listens for grounding-related WebSocket notifications and renders them
 * as action items in the Dashboard.
 *
 * Two types of notifications are handled:
 * - grounding_blocked: Material has ungrounded claims blocking pipeline.
 *   Displayed with error severity and claim details.
 * - grounding_unverified: Material could not be verified (extraction failed).
 *   Displayed with info severity as a non-blocking notice.
 */
export function GroundingNotifications({
  onNotification,
  maxVisible = 10,
}: GroundingNotificationsProps) {
  const [notifications, setNotifications] = useState<GroundingNotification[]>(
    []
  );

  const handleNotification = useCallback(
    (msg: WebSocketMessage) => {
      const category = msg.category as string | undefined;

      // Only handle grounding-related notifications
      if (
        category !== "grounding_blocked" &&
        category !== "grounding_unverified"
      ) {
        return;
      }

      const notification: GroundingNotification = {
        id: `${msg.material_id}-${Date.now()}`,
        category: category as "grounding_blocked" | "grounding_unverified",
        title: msg.title as string,
        message: msg.message as string,
        material_id: msg.material_id as string,
        pipeline_record_id: msg.pipeline_record_id as string,
        severity: msg.severity as "error" | "info",
        ungrounded_count: msg.ungrounded_count as number | undefined,
        ungrounded_claims: msg.ungrounded_claims as
          | GroundingClaim[]
          | undefined,
        blocked_states: msg.blocked_states as string[] | undefined,
        timestamp: new Date().toISOString(),
      };

      setNotifications((prev) => [notification, ...prev].slice(0, maxVisible));

      if (onNotification) {
        onNotification(notification);
      }
    },
    [maxVisible, onNotification]
  );

  // Subscribe to WebSocket "notification" messages for grounding events
  useWebSocketMessage("notification", handleNotification);

  const dismissNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  if (notifications.length === 0) {
    return null;
  }

  return (
    <div
      className="space-y-2"
      role="log"
      aria-label="Grounding verification notifications"
      aria-live="polite"
    >
      {notifications.map((notification) => (
        <GroundingNotificationCard
          key={notification.id}
          notification={notification}
          onDismiss={() => dismissNotification(notification.id)}
        />
      ))}
    </div>
  );
}

// ─── Individual Notification Card ────────────────────────────────────────────

interface GroundingNotificationCardProps {
  notification: GroundingNotification;
  onDismiss: () => void;
}

function GroundingNotificationCard({
  notification,
  onDismiss,
}: GroundingNotificationCardProps) {
  const isBlocked = notification.category === "grounding_blocked";

  return (
    <div
      className={`rounded-lg border border-l-4 p-3 ${
        isBlocked
          ? "border-red-500 border-l-red-500 bg-red-50 dark:bg-red-950/20"
          : "border-yellow-500 border-l-yellow-500 bg-yellow-50 dark:bg-yellow-950/20"
      }`}
      role="alert"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span className="flex-shrink-0 text-sm" aria-hidden="true">
            {isBlocked ? "🚫" : "⚠️"}
          </span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-[rgb(var(--foreground))]">
              {notification.title}
            </p>
            <p className="text-xs text-[rgb(var(--muted-foreground))] mt-0.5">
              {notification.message}
            </p>

            {/* Ungrounded claims detail for blocked materials */}
            {isBlocked &&
              notification.ungrounded_claims &&
              notification.ungrounded_claims.length > 0 && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs font-medium text-red-700 dark:text-red-400">
                    {notification.ungrounded_count} ungrounded claim
                    {notification.ungrounded_count !== 1 ? "s" : ""} — view
                    details
                  </summary>
                  <ul className="mt-1 space-y-1 pl-4">
                    {notification.ungrounded_claims.map((claim) => (
                      <li
                        key={claim.claim_id}
                        className="text-xs text-[rgb(var(--muted-foreground))]"
                      >
                        <span className="font-mono bg-[rgb(var(--muted))] px-1 rounded">
                          {claim.source_span}
                        </span>
                        <span className="ml-1 italic">
                          — &quot;{claim.claim_text}&quot;
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
          </div>
        </div>
        <button
          onClick={onDismiss}
          className="flex-shrink-0 rounded p-1 text-[rgb(var(--muted-foreground))] hover:bg-[rgb(var(--muted))] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--focus-ring))]"
          aria-label={`Dismiss ${notification.title}`}
        >
          <span aria-hidden="true" className="text-xs">
            ✕
          </span>
        </button>
      </div>
    </div>
  );
}
