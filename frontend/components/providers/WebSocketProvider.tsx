"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  type ConnectionStatus,
  type WebSocketClient,
  type WebSocketMessage,
  type PipelineUpdate,
  type NotificationMessage,
  type StateSync,
  getWebSocketClient,
} from "@/lib/websocket";

// ============================================================================
// WebSocket Context — provides real-time updates across components
// Requirements: 16.2, 16.6
// ============================================================================

interface WebSocketContextValue {
  /** Current connection status */
  status: ConnectionStatus;
  /** Subscribe to a specific message type. Returns unsubscribe function. */
  subscribe: (type: string, handler: (msg: WebSocketMessage) => void) => () => void;
  /** Latest pipeline update received */
  lastPipelineUpdate: PipelineUpdate | null;
  /** Latest notification received */
  lastNotification: NotificationMessage | null;
  /** Latest state sync data */
  stateSync: StateSync | null;
  /** Manually trigger a reconnect */
  reconnect: () => void;
}

const WebSocketContext = createContext<WebSocketContextValue | undefined>(
  undefined
);

interface WebSocketProviderProps {
  children: React.ReactNode;
}

export function WebSocketProvider({ children }: WebSocketProviderProps) {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [lastPipelineUpdate, setLastPipelineUpdate] =
    useState<PipelineUpdate | null>(null);
  const [lastNotification, setLastNotification] =
    useState<NotificationMessage | null>(null);
  const [stateSync, setStateSync] = useState<StateSync | null>(null);
  const clientRef = useRef<WebSocketClient | null>(null);

  // Initialize WebSocket client
  useEffect(() => {
    const client = getWebSocketClient();
    clientRef.current = client;

    // Subscribe to status changes
    const unsubStatus = client.onStatusChange(setStatus);

    // Subscribe to pipeline updates
    const unsubPipeline = client.on("pipeline_update", (msg) => {
      setLastPipelineUpdate(msg as unknown as PipelineUpdate);
    });

    // Subscribe to notifications
    const unsubNotification = client.on("notification", (msg) => {
      setLastNotification(msg as unknown as NotificationMessage);
    });

    // Subscribe to state sync
    const unsubSync = client.on("state_sync", (msg) => {
      setStateSync(msg as unknown as StateSync);
    });

    // Connect
    client.connect();

    return () => {
      unsubStatus();
      unsubPipeline();
      unsubNotification();
      unsubSync();
      client.disconnect();
    };
  }, []);

  const subscribe = useCallback(
    (type: string, handler: (msg: WebSocketMessage) => void) => {
      if (!clientRef.current) return () => {};
      return clientRef.current.on(type, handler);
    },
    []
  );

  const reconnect = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.disconnect();
      clientRef.current.connect();
    }
  }, []);

  return (
    <WebSocketContext.Provider
      value={{
        status,
        subscribe,
        lastPipelineUpdate,
        lastNotification,
        stateSync,
        reconnect,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
}

/**
 * Hook for accessing the WebSocket context.
 * Must be used within a WebSocketProvider.
 */
export function useWebSocket(): WebSocketContextValue {
  const context = useContext(WebSocketContext);
  if (context === undefined) {
    throw new Error("useWebSocket must be used within a WebSocketProvider");
  }
  return context;
}

/**
 * Hook for subscribing to specific WebSocket message types.
 * Automatically cleans up on unmount.
 */
export function useWebSocketMessage(
  type: string,
  handler: (msg: WebSocketMessage) => void
): void {
  const { subscribe } = useWebSocket();
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    return subscribe(type, (msg) => handlerRef.current(msg));
  }, [type, subscribe]);
}
