"use client";

import { useCallback, useRef } from "react";
import { useWebSocketMessage } from "@/components/providers/WebSocketProvider";
import type { WebSocketMessage } from "@/lib/websocket";

// ============================================================================
// useProposalNotifications — WebSocket hook for profile enrichment events
// Requirements: 1.4, 3.1
//
// Subscribes to:
// - "notification" messages with category "new_proposals" → triggers refresh
// - "notification" messages with category "source_failure_notice" → callback
// ============================================================================

export interface NewProposalsEvent {
  consultant_id: string;
  count: number;
  title: string;
  message: string;
}

export interface SourceFailureEvent {
  consultant_id: string;
  source_id: string;
  source_url: string;
  source_label: string;
  consecutive_failures: number;
  title: string;
  message: string;
}

interface UseProposalNotificationsOptions {
  /** Called when new proposals arrive — use to refresh the proposal list */
  onNewProposals?: (event: NewProposalsEvent) => void;
  /** Called when a source failure notice is received */
  onSourceFailure?: (event: SourceFailureEvent) => void;
}

/**
 * Hook that listens for profile enrichment WebSocket notifications.
 *
 * Subscribes to the existing "notification" message type and filters
 * for `new_proposals` and `source_failure_notice` categories emitted
 * by the Profile Enrichment Worker.
 */
export function useProposalNotifications({
  onNewProposals,
  onSourceFailure,
}: UseProposalNotificationsOptions): void {
  const onNewProposalsRef = useRef(onNewProposals);
  onNewProposalsRef.current = onNewProposals;

  const onSourceFailureRef = useRef(onSourceFailure);
  onSourceFailureRef.current = onSourceFailure;

  const handleMessage = useCallback((msg: WebSocketMessage) => {
    const category = msg.category as string | undefined;

    if (category === "new_proposals" && onNewProposalsRef.current) {
      onNewProposalsRef.current({
        consultant_id: msg.consultant_id as string,
        count: msg.count as number,
        title: msg.title as string,
        message: msg.message as string,
      });
    }

    if (category === "source_failure_notice" && onSourceFailureRef.current) {
      onSourceFailureRef.current({
        consultant_id: msg.consultant_id as string,
        source_id: msg.source_id as string,
        source_url: msg.source_url as string,
        source_label: msg.source_label as string,
        consecutive_failures: msg.consecutive_failures as number,
        title: msg.title as string,
        message: msg.message as string,
      });
    }
  }, []);

  useWebSocketMessage("notification", handleMessage);
}
