import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { CompatReport, PlanResult, RpcEvent, RunDetail, RunMode, RunRecord, RunStarted, RunSummary, ScanResult, Settings } from "./types";

export async function rpc<T>(method: string, params: unknown = {}): Promise<T> {
  return invoke<T>("rpc_call", { method, params });
}

export async function rpcSubscribe(): Promise<boolean> {
  return invoke<boolean>("rpc_subscribe");
}

export const api = {
  app: {
    version: () => rpc<{ version: string; app: string; python: string; capabilities: string[] }>("app.version"),
  },
  scan: (params: { roots: string[]; ext?: string[] }) => rpc<ScanResult>("scan", params),
  plan: (params: { roots: string[]; ext?: string[]; source_priority?: string[] }) =>
    rpc<PlanResult>("plan", params),
  compat: {
    check: (params: { book_id: string; plan_id?: string }) => rpc<CompatReport[]>("compat.check", params),
  },
  history: {
    list: (params?: { limit?: number; offset?: number }) => rpc<RunRecord[]>("history.list", params ?? {}),
    get: (params: { run_id: string }) => rpc<RunDetail>("history.get", params),
  },
  settings: {
    get: () => rpc<Settings>("settings.get"),
    set: (patch: Partial<Settings>) => rpc<Settings>("settings.set", patch),
  },
  run: (params: {
    plan_id: string;
    mode: RunMode;
    books?: string[];
    settings?: {
      backup_before_write?: boolean;
      backup_extension?: string;
      overwrite_sidecars?: boolean;
      pdf_password?: string;
      pdf_user_password?: string;
      pdf_owner_password?: string;
      pdf_reencrypt?: boolean;
      pdf_encrypt_algorithm?: string;
    };
  }) => rpc<RunStarted>("run", params),
  rollback: (params: { run_id: string }) => rpc<RunSummary>("rollback", params),
};

export function subscribeRpc(handler: (event: RpcEvent) => void): Promise<() => void> {
  return listen<RpcEvent>("rpc_evt", (event) => handler(event.payload));
}
