import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SourceConfiguration, type PublicSource } from "../SourceConfiguration";

// ============================================================================
// Helpers
// ============================================================================

function mockSource(overrides: Partial<PublicSource> = {}): PublicSource {
  return {
    id: "src-1",
    source_type: "github",
    url: "https://github.com/testuser",
    label: "My GitHub",
    last_scanned_at: "2024-01-15T10:00:00Z",
    consecutive_failures: 0,
    created_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

// ============================================================================
// Tests — Requirements: 1.1, 1.4
// ============================================================================

describe("SourceConfiguration", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders list of sources with labels and URLs", async () => {
    const sources = [
      mockSource({ id: "src-1", label: "My GitHub", url: "https://github.com/testuser" }),
      mockSource({ id: "src-2", label: "My Portfolio", url: "https://mysite.com", source_type: "portfolio" }),
    ];

    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sources,
    })) as unknown as typeof fetch;

    render(<SourceConfiguration />);

    await waitFor(() => {
      expect(screen.getByText("My GitHub")).toBeInTheDocument();
    });

    expect(screen.getByText("My Portfolio")).toBeInTheDocument();
    expect(screen.getByText("https://github.com/testuser")).toBeInTheDocument();
    expect(screen.getByText("https://mysite.com")).toBeInTheDocument();
  });

  it("shows 'Add Source' button when under the 10-source limit", async () => {
    const sources = [mockSource()];

    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sources,
    })) as unknown as typeof fetch;

    render(<SourceConfiguration />);

    await waitFor(() => {
      expect(screen.getByText("Add Source")).toBeInTheDocument();
    });
  });

  it("hides 'Add Source' button when at 10 sources", async () => {
    const sources = Array.from({ length: 10 }, (_, i) =>
      mockSource({ id: `src-${i}`, label: `Source ${i}`, url: `https://example.com/${i}` })
    );

    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sources,
    })) as unknown as typeof fetch;

    render(<SourceConfiguration />);

    await waitFor(() => {
      expect(screen.getByText("Source 0")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /add source/i })).not.toBeInTheDocument();
  });

  it("add source form submits correctly", async () => {
    const user = userEvent.setup();
    const sources = [mockSource()];
    let postCalled = false;

    global.fetch = vi.fn(async (url: string | URL | Request, options?: RequestInit) => {
      const urlStr = typeof url === "string" ? url : url.toString();
      const method = options?.method || "GET";

      if (method === "POST" && urlStr.includes("/sources")) {
        postCalled = true;
        return { ok: true, status: 201, json: async () => ({}) };
      }

      return { ok: true, status: 200, json: async () => sources };
    }) as unknown as typeof fetch;

    render(<SourceConfiguration />);

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText("My GitHub")).toBeInTheDocument();
    });

    // Click the Add Source toggle button
    await user.click(screen.getByRole("button", { name: /add source/i }));

    // Fill in the form
    const urlInput = screen.getByLabelText("URL");
    const labelInput = screen.getByLabelText("Label");

    await user.type(urlInput, "https://newsite.com");
    await user.type(labelInput, "New Site");

    // Submit the form — use the submit button in the form (not the toggle button)
    const form = screen.getByRole("form", { name: /add new source/i });
    const submitButton = form.querySelector('button[type="submit"]')!;
    await user.click(submitButton);

    await waitFor(() => {
      expect(postCalled).toBe(true);
    });
  });

  it("delete source shows confirmation dialog", async () => {
    const user = userEvent.setup();
    const sources = [mockSource({ id: "src-1", label: "My GitHub" })];

    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sources,
    })) as unknown as typeof fetch;

    render(<SourceConfiguration />);

    await waitFor(() => {
      expect(screen.getByText("My GitHub")).toBeInTheDocument();
    });

    // Click the Delete button
    const deleteBtn = screen.getByRole("button", { name: /delete my github/i });
    await user.click(deleteBtn);

    // Confirm and cancel buttons should appear
    expect(screen.getByRole("button", { name: /confirm delete/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel delete/i })).toBeInTheDocument();
  });

  it("confirms delete calls the delete API", async () => {
    const user = userEvent.setup();
    const sources = [mockSource({ id: "src-1", label: "My GitHub" })];
    let deleteCalled = false;

    global.fetch = vi.fn(async (url: string | URL | Request, options?: RequestInit) => {
      const method = options?.method || "GET";

      if (method === "DELETE") {
        deleteCalled = true;
        return { ok: true, status: 200, json: async () => ({}) };
      }

      return { ok: true, status: 200, json: async () => sources };
    }) as unknown as typeof fetch;

    render(<SourceConfiguration />);

    await waitFor(() => {
      expect(screen.getByText("My GitHub")).toBeInTheDocument();
    });

    // Click Delete, then Confirm
    await user.click(screen.getByRole("button", { name: /delete my github/i }));
    await user.click(screen.getByRole("button", { name: /confirm delete/i }));

    await waitFor(() => {
      expect(deleteCalled).toBe(true);
    });
  });

  it("displays failure warning for sources with 3+ consecutive failures", async () => {
    const sources = [
      mockSource({
        id: "src-fail",
        label: "Broken Source",
        consecutive_failures: 4,
      }),
    ];

    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sources,
    })) as unknown as typeof fetch;

    render(<SourceConfiguration />);

    await waitFor(() => {
      expect(screen.getByText("Broken Source")).toBeInTheDocument();
    });

    // Should show the failure notice alert
    expect(
      screen.getByText(/this source has failed for 4 consecutive/i)
    ).toBeInTheDocument();
  });

  it("does not show failure warning for sources with fewer than 3 failures", async () => {
    const sources = [
      mockSource({
        id: "src-ok",
        label: "OK Source",
        consecutive_failures: 2,
      }),
    ];

    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sources,
    })) as unknown as typeof fetch;

    render(<SourceConfiguration />);

    await waitFor(() => {
      expect(screen.getByText("OK Source")).toBeInTheDocument();
    });

    // Should show the failure count badge but NOT the warning alert
    expect(screen.getByText("2 failures")).toBeInTheDocument();
    expect(
      screen.queryByText(/this source has failed for/i)
    ).not.toBeInTheDocument();
  });
});
