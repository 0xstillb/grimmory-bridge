import { useMemo, useState } from "react";
import type { PlannedOutput } from "../../lib/types";

type SidecarPreviewProps = {
  output: PlannedOutput | null;
  className?: string;
};

function buildPlannedDiff(preview: string): string {
  const normalized = preview.replace(/\r\n/g, "\n");
  const lines = normalized.endsWith("\n") ? normalized.slice(0, -1).split("\n") : normalized.split("\n");
  const header = [
    "--- current",
    "+++ planned",
    "@@ sidecar-json @@",
    "# Current sidecar diff is unavailable in v1. Showing planned content lines.",
  ];
  return `${[...header, ...lines.map((line) => `+ ${line}`)].join("\n")}\n`;
}

export function SidecarPreview({ output, className }: SidecarPreviewProps) {
  const [copied, setCopied] = useState(false);
  const [showDiff, setShowDiff] = useState(false);

  const preview = typeof output?.preview === "string" ? output.preview : "";
  const display = useMemo(() => {
    if (!preview) {
      return "";
    }
    return showDiff ? buildPlannedDiff(preview) : preview;
  }, [preview, showDiff]);

  const onCopy = async () => {
    if (!display) {
      return;
    }
    try {
      await navigator.clipboard.writeText(display);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  const classes = className ? `sidecarBlock ${className}` : "sidecarBlock";

  return (
    <div className={classes}>
      <div className="sidecarHeader">
        <div className="diff-key">sidecar_json</div>
        <div className="sidecarActions">
          <button className="btn ghost sm" type="button" onClick={() => setShowDiff((value) => !value)} disabled={!preview}>
            {showDiff ? "Raw" : "Diff vs current"}
          </button>
          <button className="btn ghost sm" type="button" onClick={() => void onCopy()} disabled={!preview}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      {preview ? (
        <pre className="sidecarPre">{display}</pre>
      ) : (
        <div className="muted mono">No sidecar preview for this book.</div>
      )}
    </div>
  );
}
