import { useMemo, useState } from "react";
import type { FieldDiff as FieldDiffRow } from "../../lib/types";

type FieldDiffProps = {
  row: FieldDiffRow;
};

function toArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry));
  }
  if (value == null) {
    return [];
  }
  return [String(value)];
}

function normalizeText(value: unknown): string {
  if (value == null) {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry)).join(", ");
  }
  return String(value);
}

function trimLong(text: string): { short: string; long: string; longMode: boolean } {
  if (text.length <= 280) {
    return { short: text, long: text, longMode: false };
  }
  return { short: `${text.slice(0, 280)}...`, long: text, longMode: true };
}

export function FieldDiff({ row }: FieldDiffProps) {
  const [expanded, setExpanded] = useState(false);
  const status = row.status;

  const currentItems = toArray(row.current);
  const targetItems = toArray(row.target);

  const currentText = useMemo(() => trimLong(normalizeText(row.current)), [row.current]);
  const targetText = useMemo(() => trimLong(normalizeText(row.target)), [row.target]);

  const showCurrentText = expanded ? currentText.long : currentText.short;
  const showTargetText = expanded ? targetText.long : targetText.short;
  const canExpand = currentText.longMode || targetText.longMode;

  return (
    <div className="diff-row">
      <div className="diff-key">{row.key}</div>
      <div className="diff-val">
        {status === "same" ? (
          <div className="diff-line same">
            <span className="marker">=</span>
            <span className="text">{showTargetText}</span>
          </div>
        ) : null}

        {(status === "changed" || status === "warn" || status === "removed") && currentItems.length > 0
          ? currentItems.map((value, index) => (
              <div key={`minus-${index}-${value}`} className="diff-line minus">
                <span className="marker">-</span>
                <span className="text">{value}</span>
              </div>
            ))
          : null}

        {(status === "changed" || status === "warn" || status === "added") && targetItems.length > 0
          ? targetItems.map((value, index) => (
              <div key={`plus-${index}-${value}`} className="diff-line plus">
                <span className="marker">+</span>
                <span className="text">{value}</span>
              </div>
            ))
          : null}

        {status === "added" && targetItems.length === 0 ? (
          <div className="diff-line plus">
            <span className="marker">+</span>
            <span className="text">{showTargetText}</span>
          </div>
        ) : null}

        {status === "removed" && currentItems.length === 0 ? (
          <div className="diff-line minus">
            <span className="marker">-</span>
            <span className="text">{showCurrentText}</span>
          </div>
        ) : null}

        {canExpand ? (
          <button className="btn ghost sm" type="button" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "show less" : "show full"}
          </button>
        ) : null}

        {row.note ? <div className="diffNote">{row.note}</div> : null}
      </div>
    </div>
  );
}
