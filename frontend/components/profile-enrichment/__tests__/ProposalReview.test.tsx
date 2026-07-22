import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ProposalReview, type CompetencyProposal } from "../ProposalReview";

// ============================================================================
// Mock the WebSocket provider module so useProposalNotifications doesn't throw
// ============================================================================

vi.mock("@/components/providers/WebSocketProvider", () => ({
  useWebSocket: () => ({
    status: "connected",
    subscribe: () => () => {},
    lastPipelineUpdate: null,
    lastNotification: null,
    stateSync: null,
    reconnect: () => {},
  }),
  useWebSocketMessage: (_type: string, _handler: unknown) => {},
}));

// ============================================================================
// Helpers
// ============================================================================

function mockProposal(overrides: Partial<CompetencyProposal> = {}): CompetencyProposal {
  return {
    id: "prop-1",
    category: "technology",
    name: "Kubernetes",
    evidence_summary: "Owner of k8s-operator repo (142 stars)",
    confidence: "strong",
    source_url: "https://github.com/testuser/k8s-operator",
    source_label: "My GitHub",
    status: "pending",
    created_at: "2024-01-10T00:00:00Z",
    ...overrides,
  };
}

// ============================================================================
// Tests — Requirements: 3.1
// ============================================================================

describe("ProposalReview", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders proposals with name, category, and confidence badges", async () => {
    const proposals = [
      mockProposal({
        id: "prop-1",
        name: "Kubernetes",
        category: "technology",
        confidence: "strong",
      }),
      mockProposal({
        id: "prop-2",
        name: "RFC 9114 Co-author",
        category: "publication",
        confidence: "inferred",
      }),
    ];

    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => proposals,
    })) as unknown as typeof fetch;

    render(<ProposalReview />);

    await waitFor(() => {
      expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    });

    // Name and category badges
    expect(screen.getByText("RFC 9114 Co-author")).toBeInTheDocument();
    expect(screen.getByText("technology")).toBeInTheDocument();
    expect(screen.getByText("publication")).toBeInTheDocument();

    // Confidence badges
    expect(screen.getByText("strong")).toBeInTheDocument();
    expect(screen.getByText("inferred")).toBeInTheDocument();
  });

  it("accept button triggers accept API call", async () => {
    const user = userEvent.setup();
    const proposals = [mockProposal({ id: "prop-1", name: "Kubernetes" })];
    let acceptCalled = false;

    global.fetch = vi.fn(async (url: string | URL | Request, options?: RequestInit) => {
      const urlStr = typeof url === "string" ? url : url.toString();
      const method = options?.method || "GET";

      if (method === "POST" && urlStr.includes("/proposals/prop-1/accept")) {
        acceptCalled = true;
        return { ok: true, status: 200, json: async () => ({}) };
      }

      return { ok: true, status: 200, json: async () => proposals };
    }) as unknown as typeof fetch;

    render(<ProposalReview />);

    await waitFor(() => {
      expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    });

    // Click Accept (enters edit mode first in the edit-then-accept flow)
    const acceptBtn = screen.getByRole("button", { name: /accept proposal: kubernetes/i });
    await user.click(acceptBtn);

    // Now confirm accept
    const confirmBtn = screen.getByRole("button", { name: /confirm accept/i });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(acceptCalled).toBe(true);
    });
  });

  it("reject button triggers reject API call", async () => {
    const user = userEvent.setup();
    const proposals = [mockProposal({ id: "prop-1", name: "Kubernetes" })];
    let rejectCalled = false;

    global.fetch = vi.fn(async (url: string | URL | Request, options?: RequestInit) => {
      const urlStr = typeof url === "string" ? url : url.toString();
      const method = options?.method || "GET";

      if (method === "POST" && urlStr.includes("/proposals/prop-1/reject")) {
        rejectCalled = true;
        return { ok: true, status: 200, json: async () => ({}) };
      }

      return { ok: true, status: 200, json: async () => proposals };
    }) as unknown as typeof fetch;

    render(<ProposalReview />);

    await waitFor(() => {
      expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    });

    // Click Reject
    const rejectBtn = screen.getByRole("button", { name: /reject proposal: kubernetes/i });
    await user.click(rejectBtn);

    await waitFor(() => {
      expect(rejectCalled).toBe(true);
    });
  });

  it("bulk select/deselect works", async () => {
    const user = userEvent.setup();
    const proposals = [
      mockProposal({ id: "prop-1", name: "Kubernetes" }),
      mockProposal({ id: "prop-2", name: "Docker" }),
      mockProposal({ id: "prop-3", name: "Terraform" }),
    ];

    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => proposals,
    })) as unknown as typeof fetch;

    render(<ProposalReview />);

    await waitFor(() => {
      expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    });

    // Click "Select all" checkbox
    const selectAllCheckbox = screen.getByRole("checkbox", { name: /select all/i });
    await user.click(selectAllCheckbox);

    // Bulk actions bar should appear with count
    await waitFor(() => {
      expect(screen.getByText("3 selected")).toBeInTheDocument();
    });

    // Deselect all
    await user.click(selectAllCheckbox);

    await waitFor(() => {
      expect(screen.queryByText("3 selected")).not.toBeInTheDocument();
    });
  });

  it("bulk accept sends bulk API request", async () => {
    const user = userEvent.setup();
    const proposals = [
      mockProposal({ id: "prop-1", name: "Kubernetes" }),
      mockProposal({ id: "prop-2", name: "Docker" }),
    ];
    let bulkCalled = false;
    let bulkBody: unknown = null;

    global.fetch = vi.fn(async (url: string | URL | Request, options?: RequestInit) => {
      const urlStr = typeof url === "string" ? url : url.toString();
      const method = options?.method || "GET";

      if (method === "POST" && urlStr.includes("/proposals/bulk")) {
        bulkCalled = true;
        bulkBody = JSON.parse(options?.body as string);
        return { ok: true, status: 200, json: async () => ({ processed: 2, failed: 0 }) };
      }

      return { ok: true, status: 200, json: async () => proposals };
    }) as unknown as typeof fetch;

    render(<ProposalReview />);

    await waitFor(() => {
      expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    });

    // Select all
    const selectAllCheckbox = screen.getByRole("checkbox", { name: /select all/i });
    await user.click(selectAllCheckbox);

    await waitFor(() => {
      expect(screen.getByText("2 selected")).toBeInTheDocument();
    });

    // Click bulk accept
    const bulkAcceptBtn = screen.getByRole("button", { name: /bulk accept/i });
    await user.click(bulkAcceptBtn);

    await waitFor(() => {
      expect(bulkCalled).toBe(true);
    });

    expect(bulkBody).toEqual({
      proposal_ids: expect.arrayContaining(["prop-1", "prop-2"]),
      action: "accept",
    });
  });

  it("bulk reject sends bulk API request", async () => {
    const user = userEvent.setup();
    const proposals = [
      mockProposal({ id: "prop-1", name: "Kubernetes" }),
      mockProposal({ id: "prop-2", name: "Docker" }),
    ];
    let bulkBody: unknown = null;

    global.fetch = vi.fn(async (url: string | URL | Request, options?: RequestInit) => {
      const urlStr = typeof url === "string" ? url : url.toString();
      const method = options?.method || "GET";

      if (method === "POST" && urlStr.includes("/proposals/bulk")) {
        bulkBody = JSON.parse(options?.body as string);
        return { ok: true, status: 200, json: async () => ({ processed: 2, failed: 0 }) };
      }

      return { ok: true, status: 200, json: async () => proposals };
    }) as unknown as typeof fetch;

    render(<ProposalReview />);

    await waitFor(() => {
      expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    });

    // Select all
    await user.click(screen.getByRole("checkbox", { name: /select all/i }));

    await waitFor(() => {
      expect(screen.getByText("2 selected")).toBeInTheDocument();
    });

    // Click bulk reject
    const bulkRejectBtn = screen.getByRole("button", { name: /bulk reject/i });
    await user.click(bulkRejectBtn);

    await waitFor(() => {
      expect(bulkBody).toEqual({
        proposal_ids: expect.arrayContaining(["prop-1", "prop-2"]),
        action: "reject",
      });
    });
  });

  it("status filter tabs switch between pending/accepted/rejected", async () => {
    const user = userEvent.setup();
    let lastStatusFilter = "pending";

    global.fetch = vi.fn(async (url: string | URL | Request) => {
      const urlStr = typeof url === "string" ? url : url.toString();

      if (urlStr.includes("status=accepted")) {
        lastStatusFilter = "accepted";
        return {
          ok: true,
          status: 200,
          json: async () => [
            mockProposal({ id: "acc-1", name: "Accepted Skill", status: "accepted" }),
          ],
        };
      }

      if (urlStr.includes("status=rejected")) {
        lastStatusFilter = "rejected";
        return {
          ok: true,
          status: 200,
          json: async () => [
            mockProposal({ id: "rej-1", name: "Rejected Skill", status: "rejected" }),
          ],
        };
      }

      lastStatusFilter = "pending";
      return {
        ok: true,
        status: 200,
        json: async () => [
          mockProposal({ id: "pend-1", name: "Pending Skill", status: "pending" }),
        ],
      };
    }) as unknown as typeof fetch;

    render(<ProposalReview />);

    // Initially pending
    await waitFor(() => {
      expect(screen.getByText("Pending Skill")).toBeInTheDocument();
    });

    // Click "Accepted" tab
    const acceptedTab = screen.getByRole("tab", { name: /accepted/i });
    await user.click(acceptedTab);

    await waitFor(() => {
      expect(screen.getByText("Accepted Skill")).toBeInTheDocument();
    });
    expect(lastStatusFilter).toBe("accepted");

    // Click "Rejected" tab
    const rejectedTab = screen.getByRole("tab", { name: /rejected/i });
    await user.click(rejectedTab);

    await waitFor(() => {
      expect(screen.getByText("Rejected Skill")).toBeInTheDocument();
    });
    expect(lastStatusFilter).toBe("rejected");
  });

  it("shows empty state when no proposals exist", async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => [],
    })) as unknown as typeof fetch;

    render(<ProposalReview />);

    await waitFor(() => {
      expect(screen.getByText(/no pending proposals found/i)).toBeInTheDocument();
    });
  });

  it("shows error state when API fails", async () => {
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 500,
      json: async () => ({}),
    })) as unknown as typeof fetch;

    render(<ProposalReview />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });
});
