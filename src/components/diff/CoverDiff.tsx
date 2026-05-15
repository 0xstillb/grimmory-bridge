import { useState } from "react";
import type { CoverDiff as CoverDiffData } from "../../lib/types";

type CoverInfo = NonNullable<CoverDiffData["current"]>;

type CoverDiffProps = {
  cover: CoverDiffData;
};

function formatSize(bytes?: number): string {
  if (!bytes || bytes <= 0) {
    return "0 KB";
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function freshnessLabel(value?: string): string {
  if (value === "fresh") {
    return "fresh";
  }
  if (value === "stale") {
    return "stale";
  }
  return "unknown";
}

function CoverTile({ label, info, onHover }: { label: string; info: CoverInfo | null; onHover: (uri: string | null) => void }) {
  const hasImage = Boolean(info?.data_uri);
  return (
    <div className="coverTile">
      <div className="coverTileLabel">{label}</div>
      <div
        className={`coverThumb ${hasImage ? "has" : "none"}`}
        onMouseEnter={() => onHover(hasImage ? info!.data_uri! : null)}
        onMouseLeave={() => onHover(null)}
      >
        {hasImage ? <img src={info!.data_uri} alt={`${label} cover`} /> : <div className="coverHatch" />}
      </div>
      <div className="coverMeta mono">
        {(info?.w ?? 0)}×{(info?.h ?? 0)} · {formatSize(info?.bytes)} · {freshnessLabel(info?.freshness)}
      </div>
    </div>
  );
}

export function CoverDiff({ cover }: CoverDiffProps) {
  const [hoverUri, setHoverUri] = useState<string | null>(null);

  return (
    <div className="coverDiffBlock">
      <div className="coverDiffHeader">
        <div className="diff-key">cover</div>
        <span className={`pill ${cover.status === "warn" ? "warn" : cover.status === "changed" ? "accent" : "muted"}`}>
          {cover.status}
        </span>
      </div>
      <div className="coverGrid">
        <CoverTile label="Current" info={cover.current} onHover={setHoverUri} />
        <CoverTile label="Target" info={cover.target} onHover={setHoverUri} />
      </div>
      {hoverUri ? (
        <div className="coverPopover">
          <img src={hoverUri} alt="Cover preview" />
        </div>
      ) : null}
    </div>
  );
}

