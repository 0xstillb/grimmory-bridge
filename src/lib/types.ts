export type BookId = string;
export type FileKind = "epub" | "pdf" | "cbz" | "azw3" | "mobi" | "other";
export type RunMode = "dry" | "write";

export interface Book {
  id: BookId;
  path: string;
  rel: string;
  kind: FileKind;
  size: number;
  mtime: string;
  title: string | null;
  authors: string[];
  series: { name: string; index: number | null } | null;
  isbn: string | null;
  has_opf: boolean;
  has_sidecar: boolean;
  has_cover_sidecar: boolean;
  has_embedded_cover: boolean;
}

export interface ScanResult {
  scan_id: string;
  scanned_at: string;
  roots: { path: string; book_count: number }[];
  books: Book[];
}

export interface PlannedOutput {
  op: "write" | "create" | "update" | "delete" | "backup";
  path: string;
  kind: "epub" | "pdf" | "sidecar_json" | "sidecar_cover" | "backup";
  bytes: number;
  preview?: string | null;
}

export interface FieldDiff {
  key: string;
  status: "same" | "changed" | "added" | "removed" | "warn";
  current: unknown;
  target: unknown;
  note?: string;
}

export interface CoverDiff {
  status: "same" | "changed" | "added" | "removed" | "warn";
  current:
    | { src: string; w?: number; h?: number; sha?: string; bytes?: number; freshness?: string; data_uri?: string }
    | null;
  target:
    | { src: string; w?: number; h?: number; sha?: string; bytes?: number; freshness?: string; data_uri?: string }
    | null;
}

export interface CompatReport {
  target: "grimmory" | "koreader" | "calibre";
  status: "ok" | "partial" | "source" | "unsupported" | "missing";
  notes: string[];
}

export interface BookPlan {
  book_id: BookId;
  fields: FieldDiff[];
  cover: CoverDiff;
  outputs: PlannedOutput[];
  compat: CompatReport[];
  warnings: string[];
  errors: string[];
}

export interface PlanResult {
  plan_id: string;
  scan_id: string;
  built_at: string;
  roots?: string[];
  source_priority: Array<"grimmory" | "koreader" | "calibre">;
  summary: {
    total: number;
    changes: number;
    warn: number;
    same: number;
    errored: number;
  };
  books: BookPlan[];
}

export interface RunStarted {
  run_id: string;
  total: number;
}

export interface RunSummary {
  run_id: string;
  started_at: string;
  ended_at: string;
  mode: RunMode;
  total: number;
  written: number;
  skipped: number;
  failed: number;
  changed_files: string[];
  rollback_available: boolean;
}

export interface PlanProgressEvent {
  scan_id: string;
  current: number;
  total: number;
}

export interface RunProgressEvent {
  run_id: string;
  current: number;
  total: number;
  phase: "scanning" | "writing" | "verifying";
}

export interface LogEvent {
  run_id?: string;
  level: "info" | "warn" | "error";
  message: string;
  ts: string;
  book_id?: string;
}

export interface BookDoneEvent {
  run_id: string;
  book_id: string;
  status: "written" | "skipped" | "failed";
  outputs: PlannedOutput[];
  error?: { code: number; message: string; data?: unknown };
}

export interface RunDoneEvent {
  run_id: string;
  summary: RunSummary;
}

export interface RunHaltedEvent {
  run_id: string;
  at_book_id: string | null;
  error: { code: number; message: string; data?: unknown };
  summary: RunSummary;
}

export interface RunRecord {
  run_id: string;
  started_at: string;
  ended_at: string;
  mode: RunMode;
  roots: string[];
  summary: RunSummary;
  rollback_available: boolean;
}

export interface RunDetail extends RunRecord {
  plan: PlanResult;
  manifest_path: string;
}

export interface Settings {
  always_dry_run_first: boolean;
  confirm_before_write: boolean;
  auto_refresh_grimmory: boolean;
  source_priority: Array<"calibre" | "grimmory" | "koreader">;
  enabled_kinds: string[];
  backup_before_write: boolean;
  backup_extension: string;
  sidecar_metadata_name: string;
  sidecar_cover_name: string;
  overwrite_sidecars: boolean;
  prefer_embedded_over_sidecar: boolean;
  pdf_password: string;
  pdf_user_password: string;
  pdf_owner_password: string;
  pdf_reencrypt: boolean;
  pdf_encrypt_algorithm: string;
  theme: "light" | "dark";
  density: "compact" | "regular" | "comfy";
  accent: "indigo" | "violet" | "teal" | "amber" | "ink";
}

export type RpcEvent =
  | { method: "plan_progress"; params: PlanProgressEvent }
  | { method: "progress"; params: RunProgressEvent }
  | { method: "log"; params: LogEvent }
  | { method: "book_done"; params: BookDoneEvent }
  | { method: "run_done"; params: RunDoneEvent }
  | { method: "run_halted"; params: RunHaltedEvent };
