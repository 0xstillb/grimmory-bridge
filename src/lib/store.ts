import { useSyncExternalStore } from "react";
import type { LogEvent } from "./types";

export type LogLevelFilter = "all" | "info" | "warn" | "error";

export interface UiLogEntry {
  id: number;
  run_id?: string;
  level: "info" | "warn" | "error";
  message: string;
  ts: string;
  book_id?: string;
}

export interface LogState {
  entries: UiLogEntry[];
  level: LogLevelFilter;
  search: string;
  followTail: boolean;
}

const LOG_CAP = 5000;

let logSeq = 0;
let state: LogState = {
  entries: [],
  level: "all",
  search: "",
  followTail: true,
};

const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) {
    listener();
  }
}

function setState(next: LogState) {
  state = next;
  emit();
}

export const useLogStore = <T>(selector: (value: LogState) => T): T =>
  useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => selector(state),
    () => selector(state),
  );

export const logActions = {
  push(event: LogEvent) {
    const entry: UiLogEntry = {
      id: ++logSeq,
      run_id: event.run_id,
      level: event.level,
      message: event.message,
      ts: event.ts,
      book_id: event.book_id,
    };
    const next = state.entries.length >= LOG_CAP ? [...state.entries.slice(1), entry] : [...state.entries, entry];
    setState({ ...state, entries: next });
  },
  setLevel(level: LogLevelFilter) {
    setState({ ...state, level });
  },
  setSearch(search: string) {
    setState({ ...state, search });
  },
  setFollowTail(followTail: boolean) {
    setState({ ...state, followTail });
  },
  clear() {
    setState({ ...state, entries: [] });
  },
};
