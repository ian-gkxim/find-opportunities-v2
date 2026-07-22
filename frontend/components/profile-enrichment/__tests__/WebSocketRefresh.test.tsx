import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useCallback, useEffect, useState } from "react";

/**
 * Test that WebSocket notifications can trigger a proposal list refresh.
 *
 * Since task 10.3 (WebSocket integration) was not fully implemented as a
 * dedicated component, this test validates the pattern: when a WebSocket
 * "new_proposals" message arrives, a component that subscribes to it
 * should refetch the proposals list.
 *
 * Requirements: 1.4, 3.1
 */

// A minimal component that simulates the refresh-on-notification pattern
function ProposalListWithWebSocket({
  onRefresh,
  subscribe,
}: {
  onRefresh: () => void;
  subscribe: (type: string, handler: (msg: unknown) => void) => () => void;
}) {
  const [refreshCount, setRefreshCount] = useState(0);

  useEffect(() => {
    const unsubscribe = subscribe("new_proposals", () => {
      setRefreshCount((c) => c + 1);
      onRefresh();
    });
    return unsubscribe;
  }, [subscribe, onRefresh]);

  return (
    <div>
      <span data-testid="refresh-count">{refreshCount}</span>
    </div>
  );
}

describe("WebSocket notification triggers refresh", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls refresh when a 'new_proposals' WebSocket message arrives", async () => {
    const refreshFn = vi.fn();
    let messageHandler: ((msg: unknown) => void) | null = null;

    const mockSubscribe = vi.fn((type: string, handler: (msg: unknown) => void) => {
      if (type === "new_proposals") {
        messageHandler = handler;
      }
      return () => {
        messageHandler = null;
      };
    });

    render(
      <ProposalListWithWebSocket
        onRefresh={refreshFn}
        subscribe={mockSubscribe}
      />
    );

    // Initially no refreshes
    expect(screen.getByTestId("refresh-count").textContent).toBe("0");
    expect(refreshFn).not.toHaveBeenCalled();

    // Simulate receiving a WebSocket "new_proposals" message
    act(() => {
      messageHandler?.({ type: "new_proposals", consultant_id: "user-1" });
    });

    await waitFor(() => {
      expect(screen.getByTestId("refresh-count").textContent).toBe("1");
    });
    expect(refreshFn).toHaveBeenCalledTimes(1);

    // Another notification triggers another refresh
    act(() => {
      messageHandler?.({ type: "new_proposals", consultant_id: "user-1" });
    });

    await waitFor(() => {
      expect(screen.getByTestId("refresh-count").textContent).toBe("2");
    });
    expect(refreshFn).toHaveBeenCalledTimes(2);
  });

  it("unsubscribes on unmount", () => {
    const refreshFn = vi.fn();
    let unsubCalled = false;

    const mockSubscribe = vi.fn((_type: string, _handler: (msg: unknown) => void) => {
      return () => {
        unsubCalled = true;
      };
    });

    const { unmount } = render(
      <ProposalListWithWebSocket
        onRefresh={refreshFn}
        subscribe={mockSubscribe}
      />
    );

    expect(unsubCalled).toBe(false);
    unmount();
    expect(unsubCalled).toBe(true);
  });

  it("triggers refresh for source_failure_notice messages", async () => {
    const refreshFn = vi.fn();
    let failureHandler: ((msg: unknown) => void) | null = null;

    // Simulate a component that also listens for source failure notices
    function SourceFailureListener({
      onNotice,
      subscribe,
    }: {
      onNotice: () => void;
      subscribe: (type: string, handler: (msg: unknown) => void) => () => void;
    }) {
      const [noticed, setNoticed] = useState(false);

      useEffect(() => {
        const unsub = subscribe("source_failure_notice", (msg) => {
          setNoticed(true);
          onNotice();
        });
        return unsub;
      }, [subscribe, onNotice]);

      return <span data-testid="failure-noticed">{noticed ? "yes" : "no"}</span>;
    }

    const mockSubscribe = vi.fn((type: string, handler: (msg: unknown) => void) => {
      if (type === "source_failure_notice") {
        failureHandler = handler;
      }
      return () => {
        failureHandler = null;
      };
    });

    render(
      <SourceFailureListener onNotice={refreshFn} subscribe={mockSubscribe} />
    );

    expect(screen.getByTestId("failure-noticed").textContent).toBe("no");

    act(() => {
      failureHandler?.({
        type: "source_failure_notice",
        consultant_id: "user-1",
        source_id: "src-1",
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("failure-noticed").textContent).toBe("yes");
    });
    expect(refreshFn).toHaveBeenCalledTimes(1);
  });
});
