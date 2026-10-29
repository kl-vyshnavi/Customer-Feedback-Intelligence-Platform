import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

describe("feedback dashboard", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve({
      ok: true,
      json: async () => String(input).endsWith("/imports") ? [] : ({
        total_feedback: 0,
        issue_group_count: 0,
        recommendation_count: 0,
        sentiment_counts: { positive: 0, neutral: 0, negative: 0 },
        category_counts: {},
        feedback_over_time: [],
        rating_trends: [],
        priority_issues: [],
        items: [],
        pages: 0,
      }),
    })));
  });

  it("shows loading state and then the empty dashboard", async () => {
    render(<App />);
    expect(screen.getByText("Loading insights…")).toBeInTheDocument();
    expect(await screen.findByText("No feedback yet")).toBeInTheDocument();
  });

  it("opens the import workflow from the sidebar", async () => {
    render(<App />);
    await waitFor(() => expect(screen.queryByText("Loading insights…")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Imports" }));
    expect(screen.getByRole("heading", { name: "Import feedback" })).toBeInTheDocument();
    expect(screen.getByText(/CSV files up to 5 MB/)).toBeInTheDocument();
  });
});
