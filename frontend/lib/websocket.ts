"use client";

// ============================================================================
// WebSocket Client with exponential backoff reconnection
// Requirements: 16.2, 16.6
// ============================================================================

export type ConnectionStatus = "connected" | "disconnected" | "reconnecting";

export interface WebSocketMessage {
  type: string;
  [key: string]: unknown;
}

export interface PipelineUpdate {
  type: "pipeline_update";
  record_id: string;
  status: string;
  beneficiary_id?: string;
  opportunity_type_id?: string;
}

export interface NotificationMessage {
  type: "notification";
  category: "action_required" | "alert" | "info";
  title: string;
  message: string;
  timestamp: string;
}

export interface StateSync {
  type: "state_sync";
  pipeline_counts: Record<string, number>;
  requires_action_count: number;
  hot_prospects_count: number;
}

export type WebSocketEventType =
  | "pipeline_update"
  | "notification"
  | "state_sync"
  | "connection_status";

type MessageHandler = (message: WebSocketMessage) => void;
type StatusHandler = (status: ConnectionStatus) => void;

export interface WebSocketClientOptions {
  url: string;
  initialBackoff?: number; // Starting backoff in ms (default: 1000)
  maxBackoff?: number; // Maximum backoff in ms (default: 30000)
  onStatusChange?: StatusHandler;
}

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private initialBackoff: number;
  private maxBackoff: number;
  private currentAttempt: number = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private status: ConnectionStatus = "disconnected";
  private messageHandlers: Map<string, Set<MessageHandler>> = new Map();
  private statusHandlers: Set<StatusHandler> = new Set();
  private intentionalClose: boolean = false;

  constructor(options: WebSocketClientOptions) {
    this.url = options.url;
    this.initialBackoff = options.initialBackoff ?? 1000;
    this.maxBackoff = options.maxBackoff ?? 30000;
    if (options.onStatusChange) {
      this.statusHandlers.add(options.onStatusChange);
    }
  }

  /**
   * Connect to the WebSocket server.
   */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.intentionalClose = false;
    this.createConnection();
  }

  /**
   * Disconnect from the WebSocket server intentionally.
   */
  disconnect(): void {
    this.intentionalClose = true;
    this.clearReconnectTimer();
    if (this.ws) {
      this.ws.close(1000, "Client disconnect");
      this.ws = null;
    }
    this.setStatus("disconnected");
  }

  /**
   * Subscribe to a specific message type.
   */
  on(type: string, handler: MessageHandler): () => void {
    if (!this.messageHandlers.has(type)) {
      this.messageHandlers.set(type, new Set());
    }
    this.messageHandlers.get(type)!.add(handler);

    // Return unsubscribe function
    return () => {
      this.messageHandlers.get(type)?.delete(handler);
    };
  }

  /**
   * Subscribe to connection status changes.
   */
  onStatusChange(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    // Immediately notify current status
    handler(this.status);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  /**
   * Get the current connection status.
   */
  getStatus(): ConnectionStatus {
    return this.status;
  }

  /**
   * Compute reconnection delay using exponential backoff.
   * Formula: min(2^(attempt-1) * initialBackoff, maxBackoff)
   * Starts at 1s, caps at 30s.
   */
  getReconnectDelay(): number {
    const delay = Math.min(
      Math.pow(2, this.currentAttempt) * this.initialBackoff,
      this.maxBackoff
    );
    return delay;
  }

  // --------------------------------------------------------------------------
  // Private methods
  // --------------------------------------------------------------------------

  private createConnection(): void {
    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.currentAttempt = 0;
        this.setStatus("connected");
        this.requestStateSync();
      };

      this.ws.onmessage = (event: MessageEvent) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          this.handleMessage(message);
        } catch {
          console.warn("[WebSocket] Failed to parse message:", event.data);
        }
      };

      this.ws.onclose = (event: CloseEvent) => {
        if (!this.intentionalClose) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = () => {
        // Error will be followed by onclose, so reconnection is handled there
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private handleMessage(message: WebSocketMessage): void {
    const handlers = this.messageHandlers.get(message.type);
    if (handlers) {
      handlers.forEach((handler) => handler(message));
    }

    // Also notify wildcard handlers
    const wildcardHandlers = this.messageHandlers.get("*");
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => handler(message));
    }
  }

  private scheduleReconnect(): void {
    this.setStatus("reconnecting");
    this.clearReconnectTimer();

    const delay = this.getReconnectDelay();
    this.currentAttempt++;

    this.reconnectTimer = setTimeout(() => {
      this.createConnection();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  /**
   * Request a full state resynchronization on reconnect.
   */
  private requestStateSync(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "request_sync" }));
    }
  }

  private setStatus(newStatus: ConnectionStatus): void {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.statusHandlers.forEach((handler) => handler(newStatus));
    }
  }
}

// Singleton instance for the application
let clientInstance: WebSocketClient | null = null;

export function getWebSocketClient(): WebSocketClient {
  if (!clientInstance) {
    const wsUrl =
      typeof window !== "undefined"
        ? process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/api/ws"
        : "ws://localhost:8000/api/ws";

    clientInstance = new WebSocketClient({ url: wsUrl });
  }
  return clientInstance;
}
