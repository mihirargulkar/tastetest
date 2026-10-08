import ProgressLog from "./ProgressLog";

function fmt(fit) {
  return `${fit > 0 ? "+" : ""}${fit.toFixed(1)}`;
}

export default function RankCard({ result, busy, onSelect, runTrace, storeCount, animate }) {
  if (!result) {
    if (busy) {
      return (
        <section className="card rank-card" aria-label="Scoring stores">
          <ProgressLog kind="score" trace={runTrace} storeCount={storeCount} />
          <div className="label">Test here</div>
          {[88, 70, 80, 62, 75].map((w, i) => <div key={i} className="sk" style={{ width: `${w}%` }} />)}
          <div className="label">Skip</div>
          {[66, 78, 58].map((w, i) => <div key={i} className="sk" style={{ width: `${w}%` }} />)}
        </section>
      );
    }
    return (
      <section className="card rank-card">
        <p className="muted">Read the taste, then score stores to see where to test.</p>
      </section>
    );
  }
  const byId = Object.fromEntries(result.stores.map((s) => [s.id, s]));
  const renderRow = (id, idx) => {
    const s = byId[id];
    return (
      <li key={id} className={animate ? "row-in" : undefined} style={animate ? { "--i": idx } : undefined}>
        <button className="row" onClick={() => onSelect(id)}>
          <span className="row-main"><span>{s.name}</span><span className={s.fit >= 0 ? "up" : "dn"}>{fmt(s.fit)}</span></span>
          {result.reasons?.[id] && <span className="why">{result.reasons[id]}</span>}
          {s.confidence === "low" && <span className="why">Thin data here. Treat with caution.</span>}
        </button>
      </li>
    );
  };
  return (
    <section className="card rank-card" aria-label="Store ranking">
      <div className="label" style={{ marginTop: 0 }}>Test here</div>
      <ul>{result.top.map(renderRow)}</ul>
      {result.bottom.length > 0 && (
        <>
          <div className="label">Skip</div>
          <ul>{result.bottom.map(renderRow)}</ul>
        </>
      )}
    </section>
  );
}
