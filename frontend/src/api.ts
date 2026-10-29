export const API_URL =
  import.meta.env.VITE_API_BASE_URL ??
  "https://customer-feedback-intelligence-platform.onrender.com";

export type Filters = {
  start_date?: string;
  end_date?: string;
  category?: string;
  sentiment?: string;
  severity?: string;
  product?: string;
  search?: string;
};

export type FeedbackItem = {
  id: number;
  text: string;
  received_at: string | null;
  rating: number | null;
  product: string | null;
  sentiment: string;
  category: string;
  severity: string;
  summary: string;
  predicted_sentiment: string;
  predicted_category: string;
  predicted_severity: string;
  corrected_at: string | null;
}

export type Issue = {
  id: number;
  title: string;
  category: string;
  count: number;
  priority_score: number;
  priority_level: string;
  components: Record<string, number>;
  contributions: Record<string, number>;
  weights: Record<string, number>;
  reasons: string[];
  recommendation: {
    problem: string;
    why_it_matters: string;
    suggested_action: string;
    expected_outcome: string;
    evaluation_method: string;
  } | null;
};

export type IssueDetail = Issue & {
  feedback: FeedbackItem[];
  feedback_over_time: { date: string; count: number }[];
  rating_trends: { date: string; average_rating: number }[];
};

export type Recommendation = {
  id: number;
  issue_id: number;
  issue_title: string;
  category: string;
  problem: string;
  why_it_matters: string;
  suggested_action: string;
  expected_outcome: string;
  evaluation_method: string;
  feedback_ids: number[];
};

export type Dashboard = {
  total_feedback: number;
  issue_group_count: number;
  recommendation_count: number;
  sentiment_counts: Record<string, number>;
  category_counts: Record<string, number>;
  feedback_over_time: { date: string; count: number }[];
  rating_trends: { date: string; average_rating: number }[];
  priority_issues: Issue[];
};

export type ImportBatch = {
  id: number;
  filename: string;
  status: string;
  total_rows: number;
  imported_rows: number;
  rejected_rows: number;
  duplicate_rows: number;
  created_at: string;
};

export function queryString(filters: Filters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  return params.toString();
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}/api/v1${path}`, init);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // The response body may not be JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
