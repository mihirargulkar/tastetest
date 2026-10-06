function fmt(fit) {
  return `${fit > 0 ? "+" : ""}${fit.toFixed(1)}`;
}

export default function RankCard({ result, busy, onSelect }) {
  if (!result) {
    return (
      <section className="card rank-card">
        <p className="muted">{busy ? "Scoring stores against local taste…" : "Read the taste, then score stores to see where to test."}</p>
      </section>
    );
  }
  const byId = Object.fromEntries(result.stores.map((s) => [s.id, s]));
  const Row = ({ id }) => {
    const s = byId[id];
    return (
      <li>
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
      <ul>{result.top.map((id) => <Row key={id} id={id} />)}</ul>
      {result.bottom.length > 0 && (
        <>
          <div className="label">Skip</div>
          <ul>{result.bottom.map((id) => <Row key={id} id={id} />)}</ul>
        </>
      )}
    </section>
  );
}
