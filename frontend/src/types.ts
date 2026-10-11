export interface Book {
  id: string;
  title: string;
  author: string;
  isbn?: string | null;
  year?: number | null;
  pages?: number | null;
  subjects: string[];
  summary: string;
  cover_url?: string | null;
  source: string;
}

export interface Readiness {
  level: number;
  hours: number;
  assumed_concepts: string[];
  style_tags: string[];
  one_line: string;
}

export interface Availability {
  branch: string;
  branch_code: string;
  call_number: string;
  available: number;
  total: number;
  demo: boolean;
}

export interface Demand {
  hot_branches: string[];
  hidden_gem: boolean;
  reservations?: number;
  demo: boolean;
}

export interface Stop {
  role: "before" | "target" | "after";
  order: number;
  book: Book;
  readiness: Readiness;
  why: string;
  confidence: number;
  availability: Availability[];
  demand: Demand;
}

export interface Route {
  target_id: string;
  stops: Stop[];
  generated_at: string;
  engine: string;
  notes: string[];
}

export interface ResolveHit {
  id: string;
  title: string;
  author: string;
  cached: boolean;
}

export interface AskResponse {
  answer: string;
  adjusted_stop_ids: string[];
  engine: string;
}

export interface Branch {
  code: string;
  name: string;
}

export interface Need {
  summary: string;
  topics: string[];
  level?: number | null;
  max_hours?: number | null;
  age_group?: "child" | "teen" | "adult" | null;
  language?: string | null;
  mood?: string | null;
  format?: "book" | "ebook" | "audio" | null;
}

export interface FilterChip {
  id: string;
  label: string;
  kind: "level" | "hours" | "branch" | "category" | "language" | "age";
  value: string;
  on: boolean;
}

export interface Recommendation {
  id: string;
  line_id: string;
  is_target: boolean;
  title: string;
  author: string;
  category: string;
  level: number;
  hours: number;
  why: string;
  fit: number;
  status: string;
  available_at: string[];
  hot_at: string[];
  before_count: number;
}

export interface DiscoverResponse {
  need: Need;
  chips: FilterChip[];
  results: Recommendation[];
  engine: string;
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}
