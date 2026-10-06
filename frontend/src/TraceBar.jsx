import { useState } from "react";
import { CHAIN } from "./config";

export default function TraceBar({ trace, stability, metros, metro, onMetro }) {
  const [open, setOpen] = useState(false);
  return (
    <footer className="card trace-bar">
      <div className="trace-row">
        <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "▾" : "▸"} Agent trace · {trace.length} calls
        </button>
        {stability && (
          <span title="Leave-one-out Spearman correlation between the full ranking and the ranking with one concept removed">
            {stability.rho >= 0.7 ? "✓" : "⚠"} Ranking holds when any single concept is dropped: ρ ≥ {stability.rho.toFixed(2)} · most sensitive to "{stability.weakest}"
          </span>
        )}
        <span className="metros">
          {[null, ...metros].map((m) => (
            <button key={m ?? "all"} className={`pill ${m === metro ? "on" : ""}`} onClick={() => onMetro(m)}>{m ?? "All"}</button>
          ))}
        </span>
      </div>
      {open && (
        <ol className="trace">
          {trace.map((t, i) => <li key={i}><code>{t.tool}</code> {JSON.stringify(t.args)} → {t.summary}</li>)}
        </ol>
      )}
      <p className="fine">Fit is relative to each region. Prioritizes which stores to test in. Not a sales forecast. Not affiliated with {CHAIN}.</p>
    </footer>
  );
}
