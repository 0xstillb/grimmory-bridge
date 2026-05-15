import { invoke } from "@tauri-apps/api/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent } from "react";
import { CompatBadges } from "./components/compat/CompatBadges";
import { CoverDiff } from "./components/diff/CoverDiff";
import { FieldDiff } from "./components/diff/FieldDiff";
import { SidecarPreview } from "./components/diff/SidecarPreview";
import { mapRunError } from "./lib/errors";
import { api, rpcSubscribe, subscribeRpc } from "./lib/rpc";
import { logActions, useLogStore } from "./lib/store";
import type { BookPlan, PlanResult, RpcEvent, RunDetail, RunHaltedEvent, RunMode, RunRecord, Settings } from "./lib/types";

type Route = "library" | "embed" | "log" | "history" | "settings" | "empty";
type PaletteCommand = { id: string; label: string; run: () => void };
type CompletedBookState = "written" | "skipped";

function pickBookTitle(book: BookPlan): string {
  const row = book.fields.find((field) => field.key === "title");
  if (typeof row?.target === "string" && row.target.trim().length > 0) {
    return row.target;
  }
  if (typeof row?.current === "string" && row.current.trim().length > 0) {
    return row.current;
  }
  return `Book ${book.book_id.slice(0, 8)}`;
}

function pickAuthors(book: BookPlan): string {
  const row = book.fields.find((field) => field.key === "authors");
  const values = Array.isArray(row?.target) ? row.target : Array.isArray(row?.current) ? row.current : [];
  return values.length > 0 ? values.join(", ") : "Unknown author";
}

function pickIsbn(book: BookPlan): string {
  const row = book.fields.find((field) => field.key === "identifiers.isbn13");
  if (typeof row?.target === "string" && row.target.trim().length > 0) {
    return row.target;
  }
  if (typeof row?.current === "string" && row.current.trim().length > 0) {
    return row.current;
  }
  return "";
}

function pickCoverUri(book: BookPlan): string | null {
  if (typeof book.cover?.target?.data_uri === "string" && book.cover.target.data_uri.length > 0) {
    return book.cover.target.data_uri;
  }
  if (typeof book.cover?.current?.data_uri === "string" && book.cover.current.data_uri.length > 0) {
    return book.cover.current.data_uri;
  }
  return null;
}

function statusForBook(book: BookPlan): { cls: "success" | "warn" | "danger" | "muted"; label: string } {
  if (book.errors.length > 0) {
    return { cls: "danger", label: "Errored" };
  }
  if (book.warnings.length > 0) {
    return { cls: "warn", label: "Warn" };
  }
  if (book.outputs.length > 0) {
    return { cls: "success", label: "Changes" };
  }
  return { cls: "muted", label: "Same" };
}

function primaryOutputForBook(book: BookPlan): { kind: string; path: string } | null {
  const match = book.outputs.find((output) => output.kind === "epub" || output.kind === "pdf");
  if (!match) {
    return null;
  }
  return { kind: match.kind, path: match.path };
}

const LOG_ROW_HEIGHT = 26;
const LOG_OVERSCAN = 12;

function App() {
  const [route, setRoute] = useState<Route>("empty");
  const [version, setVersion] = useState("loading...");
  const [roots, setRoots] = useState<string[]>([]);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [isPlanning, setIsPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [selectedBookId, setSelectedBookId] = useState<string | null>(null);
  const [runMode, setRunMode] = useState<RunMode>("dry");
  const [isRunning, setIsRunning] = useState(false);
  const [runProgress, setRunProgress] = useState({ current: 0, total: 0, phase: "verifying" });
  const [completedBooks, setCompletedBooks] = useState<Record<string, CompletedBookState>>({});
  const [toast, setToast] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const [showUnchanged, setShowUnchanged] = useState(false);
  const [skippedBookIds, setSkippedBookIds] = useState<Set<string>>(new Set());
  const [readOnlyPlan, setReadOnlyPlan] = useState(false);
  const [historyRows, setHistoryRows] = useState<RunRecord[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyDetail, setHistoryDetail] = useState<RunDetail | null>(null);
  const [historyDetailLoading, setHistoryDetailLoading] = useState(false);
  const [settingsDraft, setSettingsDraft] = useState<Settings | null>(null);
  const [theme, setTheme] = useState<Settings["theme"]>("dark");
  const [density, setDensity] = useState<Settings["density"]>("comfy");
  const [accent, setAccent] = useState<Settings["accent"]>("indigo");
  const [dragSourceIndex, setDragSourceIndex] = useState<number | null>(null);
  const [bookFilter, setBookFilter] = useState<"all" | "changes" | "warn" | "same">("all");
  const [bookSearch, setBookSearch] = useState("");
  const [bookView, setBookView] = useState<"cards" | "list">("cards");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const paletteInputRef = useRef<HTMLInputElement | null>(null);
  const [haltEvent, setHaltEvent] = useState<RunHaltedEvent | null>(null);
  const [isBooting, setIsBooting] = useState(true);
  const [bootProgress, setBootProgress] = useState(6);
  const [bootLabel, setBootLabel] = useState("Starting app...");
  const logEntries = useLogStore((value) => value.entries);
  const logLevel = useLogStore((value) => value.level);
  const logSearch = useLogStore((value) => value.search);
  const logFollowTail = useLogStore((value) => value.followTail);
  const logViewportRef = useRef<HTMLDivElement | null>(null);
  const [logScrollTop, setLogScrollTop] = useState(0);
  const [logViewportHeight, setLogViewportHeight] = useState(320);
  const [logAtBottom, setLogAtBottom] = useState(true);

  const loadPlan = useCallback(async (nextRoots: string[]) => {
    setPlanError(null);
    if (nextRoots.length === 0) {
      setPlan(null);
      setSelectedBookId(null);
      setCompletedBooks({});
      return;
    }

    setIsPlanning(true);
    try {
      const out = await api.plan({ roots: nextRoots, ext: ["epub", "pdf"] });
      setPlan(out);
      setReadOnlyPlan(false);
      setSelectedBookId(out.books[0]?.book_id ?? null);
      setCompletedBooks({});
    } catch (error) {
      setPlan(null);
      setReadOnlyPlan(false);
      setSelectedBookId(null);
      setCompletedBooks({});
      setPlanError(String(error));
    } finally {
      setIsPlanning(false);
    }
  }, []);

  const applyRoots = useCallback(
    async (nextRoots: string[]) => {
      setRoots(nextRoots);
      await loadPlan(nextRoots);
    },
    [loadPlan],
  );

  useEffect(() => {
    let active = true;
    const bump = (progress: number, label: string) => {
      if (!active) {
        return;
      }
      setBootProgress((prev) => (progress > prev ? progress : prev));
      setBootLabel(label);
    };

    const pulseTimer = window.setInterval(() => {
      if (!active) {
        return;
      }
      setBootProgress((prev) => (prev < 92 ? prev + 1 : prev));
    }, 220);

    const init = async () => {
      bump(12, "Connecting runtime...");
      try {
        await rpcSubscribe();
      } catch {
        // Keep boot going; app can still recover on next RPC.
      }

      bump(34, "Loading engine version...");
      try {
        const info = await api.app.version();
        if (active) {
          setVersion(info.version);
        }
      } catch (err) {
        if (active) {
          setVersion(`error: ${String(err)}`);
        }
      }

      bump(68, "Loading settings...");
      try {
        const value = await api.settings.get();
        if (active) {
          setSettingsDraft(value);
          setTheme(value.theme);
          setDensity(value.density);
          setAccent(value.accent);
        }
      } catch {
        if (active) {
          setSettingsDraft(null);
        }
      }

      bump(100, "Ready");
      window.clearInterval(pulseTimer);
      window.setTimeout(() => {
        if (active) {
          setIsBooting(false);
        }
      }, 160);
    };

    void init();
    return () => {
      active = false;
      window.clearInterval(pulseTimer);
    };
  }, []);

  useEffect(() => {
    if (roots.length === 0) {
      setRoute("empty");
      return;
    }
    if (route === "empty") {
      setRoute("library");
    }
  }, [roots.length, route]);

  useEffect(() => {
    let unlisten: (() => void) | null = null;
    void subscribeRpc((event: RpcEvent) => {
      if (event.method === "progress") {
        setRunProgress({
          current: event.params.current,
          total: event.params.total,
          phase: event.params.phase,
        });
      }

      if (event.method === "book_done") {
        setCompletedBooks((prev) => {
          if (event.params.status === "failed") {
            const next = { ...prev };
            delete next[event.params.book_id];
            return next;
          }
          return { ...prev, [event.params.book_id]: event.params.status };
        });
      }

      if (event.method === "run_done") {
        setIsRunning(false);
        setHaltEvent(null);
        setRunProgress({
          current: event.params.summary.total,
          total: event.params.summary.total,
          phase: "verifying",
        });
        setToast({
          tone: "ok",
          text: `Run done: written ${event.params.summary.written}, skipped ${event.params.summary.skipped}, failed ${event.params.summary.failed}`,
        });
      }

      if (event.method === "run_halted") {
        setIsRunning(false);
        setHaltEvent(event.params);
        setToast({
          tone: "error",
          text: `Run halted at ${event.params.at_book_id ?? "unknown"}: ${event.params.error.message}`,
        });
      }

      if (event.method === "log") {
        logActions.push(event.params);
      }
    }).then((dispose) => {
      unlisten = dispose;
    });

    return () => {
      if (unlisten) {
        unlisten();
      }
    };
  }, []);

  const onPickFolder = useCallback(async () => {
    const selected = await invoke<string | null>("pick_folder");
    if (!selected) {
      return;
    }
    await applyRoots([selected]);
  }, [applyRoots]);

  const onDropRoots = useCallback(
    async (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      setDropActive(false);

      const files = Array.from(event.dataTransfer.files);
      const candidatePaths = files
        .map((file) => (file as File & { path?: string }).path)
        .filter((value): value is string => typeof value === "string" && value.length > 0);

      if (candidatePaths.length === 0) {
        return;
      }

      const firstPath = candidatePaths[0];
      const nextRoot = /\.[^\\/]+$/.test(firstPath) ? firstPath.replace(/[\\/][^\\/]+$/, "") : firstPath;
      if (!nextRoot) {
        return;
      }
      await applyRoots([nextRoot]);
    },
    [applyRoots],
  );

  const runWithMode = useCallback(async (mode: RunMode, books?: string[]) => {
    if (!plan || isRunning || readOnlyPlan) {
      return;
    }

    setHaltEvent(null);
    setIsRunning(true);
    setToast(null);
    setCompletedBooks({});
    setRunProgress({ current: 0, total: plan.summary.total, phase: "verifying" });

    try {
      const activeSettings = settingsDraft;
      const started = await api.run({
        plan_id: plan.plan_id,
        mode,
        books,
        settings: {
          backup_before_write: activeSettings?.backup_before_write ?? true,
          backup_extension: activeSettings?.backup_extension ?? ".bak",
          overwrite_sidecars: activeSettings?.overwrite_sidecars ?? true,
          // Keep empty string when user intentionally uses empty PDF password.
          pdf_password: activeSettings?.pdf_password ?? "",
          pdf_user_password: activeSettings?.pdf_user_password ?? "",
          pdf_owner_password: activeSettings?.pdf_owner_password ?? "",
          pdf_reencrypt: activeSettings?.pdf_reencrypt ?? true,
          pdf_encrypt_algorithm: activeSettings?.pdf_encrypt_algorithm ?? "",
        },
      });
      setRunProgress((prev) => ({ ...prev, total: started.total }));
    } catch (error) {
      setIsRunning(false);
      setToast({ tone: "error", text: `Run start failed: ${String(error)}` });
    }
  }, [isRunning, plan, readOnlyPlan, settingsDraft]);

  const onRun = useCallback(async () => {
    await runWithMode(runMode);
  }, [runMode, runWithMode]);

  const loadHistory = useCallback(async () => {
    setIsHistoryLoading(true);
    setHistoryError(null);
    try {
      const rows = await api.history.list({ limit: 100, offset: 0 });
      setHistoryRows(rows);
    } catch (error) {
      setHistoryError(String(error));
    } finally {
      setIsHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (route === "history") {
      void loadHistory();
    }
  }, [route, loadHistory]);

  const onOpenHistoryDetail = useCallback(async (runId: string) => {
    setHistoryDetailLoading(true);
    try {
      const detail = await api.history.get({ run_id: runId });
      setHistoryDetail(detail);
    } catch (error) {
      setToast({ tone: "error", text: `Load history detail failed: ${String(error)}` });
    } finally {
      setHistoryDetailLoading(false);
    }
  }, []);

  const onReopenPlan = useCallback(() => {
    if (!historyDetail) {
      return;
    }
    setPlan(historyDetail.plan);
    setReadOnlyPlan(true);
    setSelectedBookId(historyDetail.plan.books[0]?.book_id ?? null);
    setCompletedBooks({});
    setRoute("library");
    setToast({ tone: "ok", text: `Loaded ${historyDetail.run_id} as read-only plan snapshot` });
  }, [historyDetail]);

  const setDraftField = useCallback(<K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettingsDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
  }, []);

  const toggleDraftKind = useCallback((kind: string) => {
    setSettingsDraft((prev) => {
      if (!prev) {
        return prev;
      }
      const has = prev.enabled_kinds.includes(kind);
      const nextKinds = has ? prev.enabled_kinds.filter((item) => item !== kind) : [...prev.enabled_kinds, kind];
      return { ...prev, enabled_kinds: nextKinds };
    });
  }, []);

  const onSourceDropAt = useCallback((targetIndex: number) => {
    setSettingsDraft((prev) => {
      if (!prev || dragSourceIndex == null || dragSourceIndex === targetIndex) {
        return prev;
      }
      const next = [...prev.source_priority];
      const [moved] = next.splice(dragSourceIndex, 1);
      next.splice(targetIndex, 0, moved);
      return { ...prev, source_priority: next };
    });
    setDragSourceIndex(null);
  }, [dragSourceIndex]);

  const onSaveSettings = useCallback(async () => {
    if (!settingsDraft) {
      return;
    }
    try {
      const saved = await api.settings.set(settingsDraft);
      setSettingsDraft(saved);
      setTheme(saved.theme);
      setDensity(saved.density);
      setAccent(saved.accent);
      setToast({ tone: "ok", text: "Settings saved" });
    } catch (error) {
      setToast({ tone: "error", text: `Save settings failed: ${String(error)}` });
    }
  }, [settingsDraft]);

  const onToggleTheme = useCallback(async () => {
    const current = settingsDraft?.theme ?? theme;
    const next: Settings["theme"] = current === "dark" ? "light" : "dark";
    setTheme(next);
    setSettingsDraft((prev) => (prev ? { ...prev, theme: next } : prev));
    try {
      const saved = await api.settings.set({ theme: next });
      setSettingsDraft((prev) => (prev ? { ...prev, ...saved } : saved));
      setDensity(saved.density);
      setAccent(saved.accent);
    } catch {
      setToast({ tone: "error", text: "Toggle theme failed" });
    }
  }, [settingsDraft, theme]);

  const paletteCommands = useMemo<PaletteCommand[]>(
    () => [
      { id: "run-dry", label: "Run dry", run: () => void runWithMode("dry") },
      { id: "run-write", label: "Run write", run: () => void runWithMode("write") },
      { id: "pick-library", label: "Pick library", run: () => void onPickFolder() },
      { id: "open-settings", label: "Open settings", run: () => setRoute("settings") },
      { id: "toggle-theme", label: "Toggle theme", run: () => void onToggleTheme() },
      { id: "route-library", label: "Switch route: Library", run: () => setRoute("library") },
      { id: "route-embed", label: "Switch route: Embed", run: () => setRoute("embed") },
      { id: "route-log", label: "Switch route: Log", run: () => setRoute("log") },
      { id: "route-history", label: "Switch route: History", run: () => setRoute("history") },
      { id: "route-settings", label: "Switch route: Settings", run: () => setRoute("settings") },
    ],
    [onPickFolder, onToggleTheme, runWithMode],
  );

  const visiblePaletteCommands = useMemo(() => {
    const query = paletteQuery.trim().toLowerCase();
    if (!query) {
      return paletteCommands;
    }
    return paletteCommands.filter((command) => command.label.toLowerCase().includes(query));
  }, [paletteCommands, paletteQuery]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && key === "k") {
        event.preventDefault();
        setPaletteQuery("");
        setPaletteOpen(true);
        return;
      }
      if (event.key === "Escape") {
        setPaletteOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!paletteOpen) {
      return;
    }
    const input = paletteInputRef.current;
    if (!input) {
      return;
    }
    input.focus();
    input.select();
  }, [paletteOpen]);

  const onRunPaletteCommand = useCallback((command: PaletteCommand) => {
    setPaletteOpen(false);
    command.run();
  }, []);

  const selectedBook = useMemo(
    () => plan?.books.find((book) => book.book_id === selectedBookId) ?? null,
    [plan, selectedBookId],
  );
  const selectedBookIndex = useMemo(() => {
    if (!plan || !selectedBookId) {
      return -1;
    }
    return plan.books.findIndex((book) => book.book_id === selectedBookId);
  }, [plan, selectedBookId]);
  const visibleBooks = useMemo(() => {
    if (!plan) {
      return [];
    }
    const query = bookSearch.trim().toLowerCase();
    return plan.books.filter((book) => {
      const status = statusForBook(book);
      if (bookFilter === "changes" && status.cls !== "success") {
        return false;
      }
      if (bookFilter === "warn" && status.cls !== "warn" && status.cls !== "danger") {
        return false;
      }
      if (bookFilter === "same" && status.cls !== "muted") {
        return false;
      }
      if (!query) {
        return true;
      }
      const haystack = `${pickBookTitle(book)} ${pickAuthors(book)} ${pickIsbn(book)}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [plan, bookFilter, bookSearch]);
  const visibleFields = useMemo(() => {
    if (!selectedBook) {
      return [];
    }
    return selectedBook.fields.filter((field) => showUnchanged || field.status !== "same");
  }, [selectedBook, showUnchanged]);
  const selectedSidecarOutput = useMemo(
    () => selectedBook?.outputs.find((output) => output.kind === "sidecar_json") ?? null,
    [selectedBook],
  );
  const selectedPrimaryOutput = useMemo(() => (selectedBook ? primaryOutputForBook(selectedBook) : null), [selectedBook]);
  const selectedIsSkipped = useMemo(
    () => (selectedBook ? skippedBookIds.has(selectedBook.book_id) : false),
    [selectedBook, skippedBookIds],
  );
  const runProgressPct = runProgress.total > 0 ? Math.min(100, Math.max(0, (runProgress.current / runProgress.total) * 100)) : 0;
  const runProgressLabel = `${runProgress.phase} ${runProgress.current}/${runProgress.total}`;

  const onToggleSkipSelected = useCallback(() => {
    if (!selectedBook) {
      return;
    }
    setSkippedBookIds((prev) => {
      const next = new Set(prev);
      if (next.has(selectedBook.book_id)) {
        next.delete(selectedBook.book_id);
      } else {
        next.add(selectedBook.book_id);
      }
      return next;
    });
  }, [selectedBook]);

  const onOpenSelected = useCallback(async () => {
    if (!selectedPrimaryOutput) {
      return;
    }
    const rawPath = selectedPrimaryOutput.path;
    const normalized = rawPath.replace(/\\/g, "/");
    const fileUrl = `file:///${normalized}`;

    try {
      window.open(fileUrl, "_blank", "noopener,noreferrer");
      setToast({ tone: "ok", text: `Requested open: ${rawPath}` });
    } catch {
      try {
        await navigator.clipboard.writeText(rawPath);
        setToast({ tone: "ok", text: `Could not open directly. Path copied: ${rawPath}` });
      } catch {
        setToast({ tone: "error", text: `Open failed: ${rawPath}` });
      }
    }
  }, [selectedPrimaryOutput]);

  const onSelectEmbedBook = useCallback(
    (nextBookId: string) => {
      if (!plan) {
        return;
      }
      const found = plan.books.find((book) => book.book_id === nextBookId);
      if (found) {
        setSelectedBookId(found.book_id);
      }
    },
    [plan],
  );

  const onSelectEmbedOffset = useCallback(
    (delta: number) => {
      if (!plan || selectedBookIndex < 0) {
        return;
      }
      const nextIndex = selectedBookIndex + delta;
      if (nextIndex < 0 || nextIndex >= plan.books.length) {
        return;
      }
      setSelectedBookId(plan.books[nextIndex].book_id);
    },
    [plan, selectedBookIndex],
  );

  const filteredLogs = useMemo(() => {
    const query = logSearch.trim().toLowerCase();
    return logEntries.filter((entry) => {
      if (logLevel !== "all" && entry.level !== logLevel) {
        return false;
      }
      if (!query) {
        return true;
      }
      const haystack = `${entry.ts} ${entry.level} ${entry.message} ${entry.run_id ?? ""} ${entry.book_id ?? ""}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [logEntries, logLevel, logSearch]);

  const logTotal = filteredLogs.length;
  const logStart = Math.max(0, Math.floor(logScrollTop / LOG_ROW_HEIGHT) - LOG_OVERSCAN);
  const logVisibleCount = Math.ceil(logViewportHeight / LOG_ROW_HEIGHT) + LOG_OVERSCAN * 2;
  const logEnd = Math.min(logTotal, logStart + logVisibleCount);
  const visibleLogs = filteredLogs.slice(logStart, logEnd);
  const logPadTop = logStart * LOG_ROW_HEIGHT;
  const logPadBottom = Math.max(0, (logTotal - logEnd) * LOG_ROW_HEIGHT);

  useEffect(() => {
    const viewport = logViewportRef.current;
    if (!viewport) {
      return;
    }

    const sync = () => {
      setLogViewportHeight(viewport.clientHeight);
    };
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, [route]);

  useEffect(() => {
    if (!logFollowTail || !logAtBottom) {
      return;
    }
    const viewport = logViewportRef.current;
    if (!viewport) {
      return;
    }
    viewport.scrollTop = viewport.scrollHeight;
  }, [filteredLogs, logFollowTail, logAtBottom]);

  const onLogScroll = useCallback(() => {
    const viewport = logViewportRef.current;
    if (!viewport) {
      return;
    }
    const nextTop = viewport.scrollTop;
    const delta = viewport.scrollHeight - (viewport.scrollTop + viewport.clientHeight);
    setLogScrollTop(nextTop);
    setLogAtBottom(delta <= 8);
  }, []);

  const formatLogLine = useCallback((entry: (typeof filteredLogs)[number]) => {
    const runPart = entry.run_id ? ` run=${entry.run_id}` : "";
    const bookPart = entry.book_id ? ` book=${entry.book_id}` : "";
    return `[${entry.ts}] [${entry.level}]${runPart}${bookPart} ${entry.message}`;
  }, []);

  const onCopyLogLine = useCallback(
    async (entry: (typeof filteredLogs)[number]) => {
      const text = formatLogLine(entry);
      try {
        await navigator.clipboard.writeText(text);
        setToast({ tone: "ok", text: "Copied log line" });
      } catch {
        setToast({ tone: "error", text: "Copy log line failed" });
      }
    },
    [formatLogLine],
  );

  const haltCopy = useMemo(() => {
    if (!haltEvent) {
      return null;
    }
    const mapped = mapRunError({ code: haltEvent.error.code, message: haltEvent.error.message });
    return {
      title: mapped.title,
      suggestion: mapped.suggestion,
    };
  }, [haltEvent]);

  const retryBookIds = useMemo(() => {
    if (!haltEvent || !plan || !haltEvent.at_book_id) {
      return [];
    }
    const index = plan.books.findIndex((book) => book.book_id === haltEvent.at_book_id);
    if (index < 0) {
      return [];
    }
    return plan.books.slice(index).map((book) => book.book_id);
  }, [haltEvent, plan]);

  const onOpenLogFromHalt = useCallback(() => {
    logActions.setLevel("error");
    setRoute("log");
  }, []);

  const onRollbackStub = useCallback(async () => {
    if (!haltEvent) {
      return;
    }
    const ok = window.confirm(`Roll back applied changes for ${haltEvent.run_id}?`);
    if (!ok) {
      return;
    }
    setToast({ tone: "ok", text: "Rollback in progress..." });
    try {
      const summary = await api.rollback({ run_id: haltEvent.run_id });
      setToast({
        tone: "ok",
        text: `Rollback done: restored ${summary.written}, skipped ${summary.skipped}, failed ${summary.failed}`,
      });
      setHaltEvent(null);
    } catch (error) {
      setToast({ tone: "error", text: `Rollback failed: ${String(error)}` });
    }
  }, [haltEvent]);

  const onRetryStub = useCallback(async () => {
    if (!haltEvent) {
      return;
    }
    if (!plan || retryBookIds.length === 0) {
      setToast({ tone: "error", text: "Re-plan first" });
      return;
    }
    try {
      await runWithMode("write", retryBookIds);
      setToast({ tone: "ok", text: `Retry started from ${haltEvent.at_book_id}` });
    } catch (error) {
      const text = String(error);
      if (text.includes("PLAN_STALE")) {
        setToast({ tone: "error", text: "Re-plan first" });
      } else {
        setToast({ tone: "error", text: `Retry failed: ${text}` });
      }
    }
  }, [haltEvent, plan, retryBookIds, runWithMode]);

  return (
    <main
      className="gb-app gb-window"
      data-theme={theme}
      data-density={density}
      data-accent={accent}
      aria-label="Grimmory Bridge"
    >
      <header className="gb-titlebar">
        <div className="lights">
          <span />
          <span />
          <span />
        </div>
        <div className="title">Grimmory Bridge</div>
        <div className="spacer" />
        <div className="crumbs mono">Python {version}</div>
      </header>

      {isBooting ? (
        <div className="bootOverlay" role="status" aria-live="polite">
          <div className="panel bootCard">
            <div className="mono bootPercent">{Math.min(100, Math.max(0, Math.round(bootProgress)))}%</div>
            <div className="bootLabel">{bootLabel}</div>
            <div className="bootTrack">
              <div className="bootFill" style={{ width: `${Math.min(100, Math.max(0, bootProgress))}%` }} />
            </div>
          </div>
        </div>
      ) : null}

      <div className="shell">
        <aside className="sidebar">
          <button
            className={`nav ${route === "library" || route === "empty" ? "active" : ""}`}
            type="button"
            onClick={() => setRoute("library")}
          >
            Library
          </button>
          <button
            className={`nav ${route === "embed" ? "active" : ""}`}
            type="button"
            onClick={() => setRoute("embed")}
            disabled={!selectedBook}
          >
            Embed
          </button>
          <button className={`nav ${route === "log" ? "active" : ""}`} type="button" onClick={() => setRoute("log")}>
            Log
          </button>
          <button className={`nav ${route === "history" ? "active" : ""}`} type="button" onClick={() => setRoute("history")}>
            History
          </button>
          <button
            className={`nav ${route === "settings" ? "active" : ""}`}
            type="button"
            onClick={() => setRoute("settings")}
          >
            Settings
          </button>
          <div className="sidebarFooter">
            <div className="mono">MVP #1.7</div>
          </div>
        </aside>

        {route === "empty" ? (
          <section className="content emptyContent">
            <div className="emptyWrap">
              <div className="emptyIcon mono">GB</div>
              <h1 className="emptyTitle">Your library is empty</h1>
              <p className="emptyText">
                Add a Calibre folder to scan its <span className="mono">metadata.opf</span> files, build a plan, and
                review every change before anything is written.
              </p>

              <div
                className={`dropZone ${dropActive ? "active" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDropActive(true);
                }}
                onDragLeave={() => setDropActive(false)}
                onDrop={(event) => void onDropRoots(event)}
              >
                <div className="dropTitle">Drop folders here</div>
                <div className="dropSub">or use the button below - folders are scanned read-only</div>
                <div className="dropActions">
                  <button className="btn primary" type="button" onClick={() => void onPickFolder()}>
                    Pick Calibre library
                  </button>
                </div>
              </div>

              <div className="featureGrid">
                <div className="featureCard">
                  <div className="featureTitle">Dry Run by default</div>
                  <div className="featureDesc">Nothing is written until you confirm a plan.</div>
                </div>
                <div className="featureCard">
                  <div className="featureTitle">Field-level diff</div>
                  <div className="featureDesc">See current {"->"} target for every metadata field.</div>
                </div>
                <div className="featureCard">
                  <div className="featureTitle">Compat check</div>
                  <div className="featureDesc">KOReader - Grimmory - Calibre status per book.</div>
                </div>
              </div>
            </div>
          </section>
        ) : route === "library" ? (
          <section className="content">
            <div className="toolbar">
              <button className="btn primary" type="button" onClick={() => void onPickFolder()}>
                Pick library
              </button>
              <div className="segmented">
                {(["all", "changes", "warn", "same"] as const).map((filter) => (
                  <button
                    key={filter}
                    className={`seg ${bookFilter === filter ? "active" : ""}`}
                    type="button"
                    onClick={() => setBookFilter(filter)}
                  >
                    {filter}
                  </button>
                ))}
              </div>
              <input
                className="logSearchInput mono"
                type="text"
                value={bookSearch}
                onChange={(event) => setBookSearch(event.target.value)}
                placeholder="Search title/author/isbn"
              />
              <div className="segmented">
                <button className={`seg ${bookView === "cards" ? "active" : ""}`} type="button" onClick={() => setBookView("cards")}>
                  Cards
                </button>
                <button className={`seg ${bookView === "list" ? "active" : ""}`} type="button" onClick={() => setBookView("list")}>
                  List
                </button>
              </div>
              <div className="muted mono">{roots[0] ?? "No library selected"}</div>
            </div>

            {haltEvent && haltCopy ? (
              <div className="haltBanner">
                <div>
                  <div className="haltTitle">{haltCopy.title}</div>
                  <div className="haltSub muted">
                    at {haltEvent.at_book_id ?? "unknown"} - {haltCopy.suggestion}
                  </div>
                </div>
                <div className="haltActions">
                  <button className="btn primary" type="button" onClick={onRollbackStub}>
                    Roll back applied changes
                  </button>
                  <button
                    className="btn ghost"
                    type="button"
                    onClick={onRetryStub}
                    disabled={!plan || retryBookIds.length === 0}
                  >
                    Retry from #N
                  </button>
                  <button className="btn ghost" type="button" onClick={onOpenLogFromHalt}>
                    Open log
                  </button>
                </div>
              </div>
            ) : null}

            {planError ? <div className="errorPanel">{planError}</div> : null}
            {isPlanning ? <div className="panel">Scanning and planning...</div> : null}

            {!isPlanning && !plan && !planError ? (
              <div className="panel">Pick a library folder to start.</div>
            ) : null}

            {plan ? (
              <div className="libraryGrid">
                <div className={`bookList scroll ${bookView === "list" ? "listMode" : ""}`}>
                  {visibleBooks.length === 0 ? <div className="muted mono">No books match current filters.</div> : null}
                  {visibleBooks.map((book) => {
                    const status = statusForBook(book);
                    const coverUri = pickCoverUri(book);
                    const doneState = completedBooks[book.book_id];
                    return (
                      <button
                        key={book.book_id}
                        className={`bookCard ${selectedBookId === book.book_id ? "selected" : ""} ${doneState ? "done" : ""}`}
                        type="button"
                        onClick={() => setSelectedBookId(book.book_id)}
                      >
                        {doneState ? (
                          <span className="bookDoneBadge" title={`Done: ${doneState}`} aria-label={`Done: ${doneState}`}>
                            {"\u2713"}
                          </span>
                        ) : null}
                        <div className={`bookCover ${coverUri ? "has" : "none"}`}>
                          {coverUri ? <img src={coverUri} alt={`${pickBookTitle(book)} cover`} loading="lazy" /> : <span>no cover</span>}
                        </div>
                        <div className="bookTitle">{pickBookTitle(book)}</div>
                        <div className="bookMeta">{pickAuthors(book)}</div>
                        <div className={`pill ${status.cls}`}>
                          <span className="dot" />
                          {status.label}
                        </div>
                      </button>
                    );
                  })}
                </div>

                <div className="bookDetail panel">
                  {selectedBook ? (
                    <>
                      <div className="detailTitle">{pickBookTitle(selectedBook)}</div>
                      <div className="muted">{pickAuthors(selectedBook)}</div>
                      <div className="detailStats">
                        <span className="pill accent">{selectedBook.outputs.length} outputs</span>
                        <span className="pill muted">{selectedBook.warnings.length} warnings</span>
                        <span className="pill muted">{selectedBook.errors.length} errors</span>
                      </div>
                      <div className="diffToolbar">
                        <label className="muted">
                          <input
                            type="checkbox"
                            checked={showUnchanged}
                            onChange={(event) => setShowUnchanged(event.target.checked)}
                          />{" "}
                          Show unchanged
                        </label>
                      </div>
                      <CoverDiff cover={selectedBook.cover} />
                      <CompatBadges compat={selectedBook.compat} />
                      <SidecarPreview output={selectedSidecarOutput} />
                      <div className="diffPanel scroll">
                        {visibleFields.map((row) => (
                          <FieldDiff key={row.key} row={row} />
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="muted">Pick a book from the list.</div>
                  )}
                </div>
              </div>
            ) : null}

            {readOnlyPlan ? <div className="panel muted">Read-only snapshot loaded from History. Build a new plan before running.</div> : null}

            <div className="runBar">
              <div className="segmented">
                <button
                  className={`seg ${runMode === "dry" ? "active" : ""}`}
                  type="button"
                  onClick={() => setRunMode("dry")}
                  disabled={isRunning}
                >
                  Dry Run
                </button>
                <button
                  className={`seg ${runMode === "write" ? "active" : ""}`}
                  type="button"
                  onClick={() => setRunMode("write")}
                  disabled={isRunning}
                >
                  Write
                </button>
              </div>

              <div className="summary mono">
                {plan ? `${plan.summary.changes} changes - ${plan.summary.warn} warnings - ${plan.summary.same} same` : "No plan"}
              </div>

              <div className="kbd">Ctrl+Enter</div>

              <button className="btn primary" type="button" onClick={() => void onRun()} disabled={!plan || isRunning || readOnlyPlan}>
                {runMode === "dry" ? "Run dry run" : "Write changes..."}
              </button>

              <button className="btn ghost" type="button" disabled>
                Cancel
              </button>

              {isRunning ? (
                <div className="progressInline" role="status" aria-live="polite" title={runProgressLabel}>
                  <div className="progressTrack" aria-hidden>
                    <div className="progressFill" style={{ width: `${runProgressPct}%` }} />
                  </div>
                  <div className="progressText mono">{runProgressLabel}</div>
                </div>
              ) : null}
            </div>
          </section>
        ) : route === "embed" ? (
          <section className="content embedContent">
            {!selectedBook ? (
              <div className="panel muted">Pick a book in Library first.</div>
            ) : (
              <>
                <div className="panel embedHeader">
                  <div className="embedHeaderTop">
                    <div>
                      <div className="detailTitle">{pickBookTitle(selectedBook)}</div>
                      <div className="muted">{pickAuthors(selectedBook)}</div>
                    </div>
                    <div className="embedSwitch">
                      <button
                        className="btn ghost sm"
                        type="button"
                        onClick={() => onSelectEmbedOffset(-1)}
                        disabled={!plan || selectedBookIndex <= 0}
                      >
                        Prev
                      </button>
                      <select
                        className="embedSelect mono"
                        value={selectedBook.book_id}
                        onChange={(event) => onSelectEmbedBook(event.target.value)}
                      >
                        {(plan?.books ?? []).map((book, index) => (
                          <option key={book.book_id} value={book.book_id}>
                            {`${index + 1}. ${pickBookTitle(book)}`}
                          </option>
                        ))}
                      </select>
                      <button
                        className="btn ghost sm"
                        type="button"
                        onClick={() => onSelectEmbedOffset(1)}
                        disabled={!plan || selectedBookIndex < 0 || selectedBookIndex >= plan.books.length - 1}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                  <div className="embedMeta">
                    <span className="pill accent">
                      <span className="dot" />
                      {(selectedPrimaryOutput?.kind ?? "other").toUpperCase()}
                    </span>
                    <span className="pill muted mono">
                      {plan ? `${selectedBookIndex + 1}/${plan.books.length}` : "0/0"}
                    </span>
                    <span className="mono muted">{selectedPrimaryOutput?.path ?? selectedBook.book_id}</span>
                  </div>
                </div>

                <div className="embedGrid">
                  <div className="panel embedColumn embedDiffColumn">
                    <div className="diffToolbar">
                      <label className="muted">
                        <input
                          type="checkbox"
                          checked={showUnchanged}
                          onChange={(event) => setShowUnchanged(event.target.checked)}
                        />{" "}
                        Show unchanged
                      </label>
                    </div>
                    <div className="diffPanel embedDiffPanel scroll">
                      {visibleFields.map((row) => (
                        <FieldDiff key={row.key} row={row} />
                      ))}
                    </div>
                  </div>

                  <div className="embedColumn embedRightColumn">
                    <CoverDiff cover={selectedBook.cover} />
                    <CompatBadges compat={selectedBook.compat} />
                    <SidecarPreview output={selectedSidecarOutput} className="embedSidecar" />
                  </div>
                </div>

                <div className="panel embedFooter">
                  <button className={`btn ${selectedIsSkipped ? "danger" : "ghost"}`} type="button" onClick={onToggleSkipSelected}>
                    {selectedIsSkipped ? "Unskip" : "Skip"}
                  </button>
                  <button className="btn ghost" type="button" onClick={() => void onOpenSelected()} disabled={!selectedPrimaryOutput}>
                    Open file in Explorer/Finder
                  </button>
                </div>
              </>
            )}
          </section>
        ) : route === "log" ? (
          <section className="content">
            <div className="panel logToolbar">
              <div className="segmented">
                {(["all", "info", "warn", "error"] as const).map((level) => (
                  <button
                    key={level}
                    className={`seg ${logLevel === level ? "active" : ""}`}
                    type="button"
                    onClick={() => logActions.setLevel(level)}
                  >
                    {level}
                  </button>
                ))}
              </div>

              <input
                className="logSearchInput mono"
                type="text"
                value={logSearch}
                onChange={(event) => logActions.setSearch(event.target.value)}
                placeholder="Search logs"
              />

              <label className="muted">
                <input
                  type="checkbox"
                  checked={logFollowTail}
                  onChange={(event) => logActions.setFollowTail(event.target.checked)}
                />{" "}
                Follow tail
              </label>

              <button className="btn ghost" type="button" onClick={() => logActions.clear()}>
                Clear
              </button>
            </div>

            <div className="panel logPanel">
              <div className="logSummary mono">
                {logTotal} lines {logAtBottom ? "- tail" : "- paused"}
              </div>
              <div className="logViewport scroll" ref={logViewportRef} onScroll={onLogScroll}>
                <div style={{ height: `${logPadTop}px` }} />
                {visibleLogs.map((entry) => (
                  <button
                    key={entry.id}
                    className={`logRow ${entry.level}`}
                    type="button"
                    style={{ height: `${LOG_ROW_HEIGHT}px` }}
                    onClick={() => void onCopyLogLine(entry)}
                    title="Click to copy line"
                  >
                    <span className="mono logTs">{entry.ts}</span>
                    <span className="mono logLevel">{entry.level.toUpperCase()}</span>
                    <span className="logMessage">{entry.message}</span>
                  </button>
                ))}
                <div style={{ height: `${logPadBottom}px` }} />
              </div>
            </div>
          </section>
        ) : route === "history" ? (
          <section className="content">
            <div className="toolbar">
              <button className="btn ghost" type="button" onClick={() => void loadHistory()}>
                Refresh
              </button>
              <div className="muted mono">{historyRows.length} runs</div>
            </div>

            {historyError ? <div className="errorPanel">{historyError}</div> : null}
            {isHistoryLoading ? <div className="panel">Loading history...</div> : null}

            <div className="historyGrid">
              <div className="panel historyTableWrap scroll">
                <div className="historyTableHeader mono">
                  <span>started_at</span>
                  <span>mode</span>
                  <span>roots</span>
                  <span>changes</span>
                  <span>result</span>
                  <span>rollback</span>
                </div>
                {historyRows.map((row) => (
                  <button key={row.run_id} className="historyRow" type="button" onClick={() => void onOpenHistoryDetail(row.run_id)}>
                    <span className="mono">{row.started_at}</span>
                    <span className={`pill ${row.mode === "write" ? "warn" : "muted"}`}>{row.mode}</span>
                    <span className="historyCellEllipsis mono">{row.roots.join(", ") || "-"}</span>
                    <span className="mono">{row.summary.written + row.summary.skipped + row.summary.failed}</span>
                    <span className={`pill ${row.summary.failed > 0 ? "danger" : "success"}`}>
                      {row.summary.failed > 0 ? "halted" : "done"}
                    </span>
                    <span className="mono">{row.rollback_available ? "yes" : "no"}</span>
                  </button>
                ))}
              </div>

              <div className="panel historyDetail">
                {historyDetailLoading ? <div className="muted">Loading detail...</div> : null}
                {!historyDetailLoading && !historyDetail ? <div className="muted">Select a run to inspect details.</div> : null}
                {historyDetail ? (
                  <>
                    <div className="detailTitle">{historyDetail.run_id}</div>
                    <div className="muted mono">{historyDetail.started_at} {"->"} {historyDetail.ended_at}</div>
                    <div className="detailStats">
                      <span className="pill accent">mode {historyDetail.mode}</span>
                      <span className="pill muted">written {historyDetail.summary.written}</span>
                      <span className="pill muted">skipped {historyDetail.summary.skipped}</span>
                      <span className="pill danger">failed {historyDetail.summary.failed}</span>
                    </div>
                    <div className="muted mono">manifest: {historyDetail.manifest_path}</div>
                    <button className="btn primary" type="button" onClick={onReopenPlan}>
                      Re-open plan
                    </button>
                  </>
                ) : null}
              </div>
            </div>
          </section>
        ) : route === "settings" ? (
          <section className="content scroll">
            {!settingsDraft ? (
              <div className="panel muted mono">No settings loaded</div>
            ) : (
              <>
                <div className="panel settingsSection">
                  <div className="detailTitle">Run defaults</div>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={settingsDraft.always_dry_run_first}
                      onChange={(event) => setDraftField("always_dry_run_first", event.target.checked)}
                    />{" "}
                    Always dry run first
                  </label>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={settingsDraft.confirm_before_write}
                      onChange={(event) => setDraftField("confirm_before_write", event.target.checked)}
                    />{" "}
                    Confirm before write
                  </label>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={settingsDraft.auto_refresh_grimmory}
                      onChange={(event) => setDraftField("auto_refresh_grimmory", event.target.checked)}
                    />{" "}
                    Auto refresh Grimmory
                  </label>
                </div>

                <div className="panel settingsSection">
                  <div className="detailTitle">Sources</div>
                  <div className="muted">Drag to reorder source priority</div>
                  <div className="settingsSortable">
                    {settingsDraft.source_priority.map((target, index) => (
                      <div
                        key={target}
                        className="settingsDragItem"
                        draggable
                        onDragStart={() => setDragSourceIndex(index)}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => onSourceDropAt(index)}
                      >
                        <span className="mono">{target}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="panel settingsSection">
                  <div className="detailTitle">File handling</div>
                  <div className="settingsChipRow">
                    {(["epub", "pdf", "cbz", "azw3", "mobi", "other"] as const).map((kind) => (
                      <button
                        key={kind}
                        className={`pill ${settingsDraft.enabled_kinds.includes(kind) ? "accent" : "muted"}`}
                        type="button"
                        onClick={() => toggleDraftKind(kind)}
                      >
                        {kind}
                      </button>
                    ))}
                  </div>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={settingsDraft.backup_before_write}
                      onChange={(event) => setDraftField("backup_before_write", event.target.checked)}
                    />{" "}
                    Backup before write
                  </label>
                  <label className="muted mono">
                    backup_extension
                    <input
                      className="settingsInput mono"
                      value={settingsDraft.backup_extension}
                      onChange={(event) => setDraftField("backup_extension", event.target.value)}
                    />
                  </label>
                </div>

                <div className="panel settingsSection">
                  <div className="detailTitle">Sidecars</div>
                  <label className="muted mono">
                    sidecar_metadata_name
                    <input
                      className="settingsInput mono"
                      value={settingsDraft.sidecar_metadata_name}
                      onChange={(event) => setDraftField("sidecar_metadata_name", event.target.value)}
                    />
                  </label>
                  <label className="muted mono">
                    sidecar_cover_name
                    <input
                      className="settingsInput mono"
                      value={settingsDraft.sidecar_cover_name}
                      onChange={(event) => setDraftField("sidecar_cover_name", event.target.value)}
                    />
                  </label>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={settingsDraft.overwrite_sidecars}
                      onChange={(event) => setDraftField("overwrite_sidecars", event.target.checked)}
                    />{" "}
                    Overwrite sidecars
                  </label>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={settingsDraft.prefer_embedded_over_sidecar}
                      onChange={(event) => setDraftField("prefer_embedded_over_sidecar", event.target.checked)}
                    />{" "}
                    Prefer embedded cover over sidecar cover
                  </label>
                </div>

                <div className="panel settingsSection">
                  <div className="detailTitle">PDF encryption</div>
                  <label className="muted mono">
                    pdf_password
                    <input
                      className="settingsInput mono"
                      type="password"
                      value={settingsDraft.pdf_password}
                      onChange={(event) => setDraftField("pdf_password", event.target.value)}
                    />
                  </label>
                  <label className="muted mono">
                    pdf_owner_password
                    <input
                      className="settingsInput mono"
                      type="password"
                      value={settingsDraft.pdf_owner_password}
                      onChange={(event) => setDraftField("pdf_owner_password", event.target.value)}
                    />
                  </label>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={settingsDraft.pdf_reencrypt}
                      onChange={(event) => setDraftField("pdf_reencrypt", event.target.checked)}
                    />{" "}
                    Re-encrypt PDF after metadata write
                  </label>
                  <label className="muted mono">
                    pdf_encrypt_algorithm
                    <select
                      className="settingsSelect mono"
                      value={settingsDraft.pdf_encrypt_algorithm}
                      onChange={(event) => setDraftField("pdf_encrypt_algorithm", event.target.value)}
                    >
                      <option value="">auto</option>
                      <option value="RC4-40">RC4-40</option>
                      <option value="RC4-128">RC4-128</option>
                      <option value="AES-128">AES-128</option>
                      <option value="AES-256-R5">AES-256-R5</option>
                      <option value="AES-256">AES-256</option>
                    </select>
                  </label>
                </div>

                <div className="panel settingsSection">
                  <div className="detailTitle">Appearance</div>
                  <div className="settingsSelects">
                    <label className="mono muted">
                      theme
                      <select
                        className="settingsSelect mono"
                        value={settingsDraft.theme}
                        onChange={(event) => setDraftField("theme", event.target.value as Settings["theme"])}
                      >
                        <option value="light">light</option>
                        <option value="dark">dark</option>
                      </select>
                    </label>
                    <label className="mono muted">
                      density
                      <select
                        className="settingsSelect mono"
                        value={settingsDraft.density}
                        onChange={(event) => setDraftField("density", event.target.value as Settings["density"])}
                      >
                        <option value="compact">compact</option>
                        <option value="regular">regular</option>
                        <option value="comfy">comfy</option>
                      </select>
                    </label>
                    <label className="mono muted">
                      accent
                      <select
                        className="settingsSelect mono"
                        value={settingsDraft.accent}
                        onChange={(event) => setDraftField("accent", event.target.value as Settings["accent"])}
                      >
                        <option value="indigo">indigo</option>
                        <option value="violet">violet</option>
                        <option value="teal">teal</option>
                        <option value="amber">amber</option>
                        <option value="ink">ink</option>
                      </select>
                    </label>
                  </div>
                </div>

                <div className="runBar">
                  <div className="summary mono">settings.sqlite - schema v1</div>
                  <button className="btn primary" type="button" onClick={() => void onSaveSettings()}>
                    Save settings
                  </button>
                </div>
              </>
            )}
          </section>
        ) : null}
      </div>

      {paletteOpen ? (
        <div className="paletteBackdrop" onClick={() => setPaletteOpen(false)}>
          <div
            className="paletteModal"
            onClick={(event) => event.stopPropagation()}
          >
            <input
              ref={paletteInputRef}
              className="paletteInput mono"
              type="text"
              value={paletteQuery}
              onChange={(event) => setPaletteQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && visiblePaletteCommands[0]) {
                  event.preventDefault();
                  onRunPaletteCommand(visiblePaletteCommands[0]);
                }
              }}
              placeholder="Type a command"
            />
            <div className="paletteList scroll">
              {visiblePaletteCommands.length === 0 ? <div className="paletteEmpty muted">No commands</div> : null}
              {visiblePaletteCommands.map((command) => (
                <button key={command.id} className="paletteItem" type="button" onClick={() => onRunPaletteCommand(command)}>
                  {command.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {toast ? <div className={`toast ${toast.tone === "ok" ? "ok" : "error"}`}>{toast.text}</div> : null}
    </main>
  );
}

export default App;
