import { useMemo, useState } from "react";
import type { CompatReport } from "../../lib/types";

type CompatBadgesProps = {
  compat: CompatReport[];
};

const TARGET_ORDER: Array<CompatReport["target"]> = ["grimmory", "koreader", "calibre"];

function statusClass(status: CompatReport["status"]): string {
  if (status === "ok") {
    return "success";
  }
  if (status === "partial") {
    return "warn";
  }
  if (status === "missing") {
    return "danger";
  }
  return "muted";
}

export function CompatBadges({ compat }: CompatBadgesProps) {
  const [hoverTarget, setHoverTarget] = useState<CompatReport["target"] | null>(null);
  const rows = useMemo<CompatReport[]>(() => {
    const byTarget = new Map<CompatReport["target"], CompatReport>();
    for (const item of compat) {
      byTarget.set(item.target, item);
    }
    return TARGET_ORDER.map(
      (target) =>
        byTarget.get(target) ?? {
          target,
          status: "missing",
          notes: ["No data"],
        },
    );
  }, [compat]);

  return (
    <div className="compatBlock">
      <div className="diff-key">compat</div>
      <div className="compatRow">
        {rows.map((row) => {
          const open = hoverTarget === row.target && row.notes.length > 0;
          return (
            <div
              key={row.target}
              className="compatItem"
              onMouseEnter={() => setHoverTarget(row.target)}
              onMouseLeave={() => setHoverTarget(null)}
            >
              <span className={`pill ${statusClass(row.status)} ${row.status === "unsupported" ? "compatUnsupported" : ""}`}>
                <span className="dot" />
                {row.target}: {row.status}
              </span>
              {open ? (
                <div className="compatPopover">
                  {row.notes.map((note, index) => (
                    <div key={`${row.target}-${index}`}>{note}</div>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
