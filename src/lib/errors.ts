export interface HaltErrorPayload {
  code: number;
  message: string;
}

export function mapRunError(error: HaltErrorPayload): { title: string; suggestion: string } {
  if (error.code === 1011 || error.message === "WRITE_HALTED") {
    return {
      title: "Write halted",
      suggestion: "Inspect the failing book in Log, then roll back or retry from that point.",
    };
  }
  if (error.code === 1003 || error.message === "PLAN_STALE") {
    return {
      title: "Plan is stale",
      suggestion: "Build a fresh plan, then retry the run.",
    };
  }
  return {
    title: error.message || "Run halted",
    suggestion: "Open Log to inspect details, then decide rollback or retry.",
  };
}
