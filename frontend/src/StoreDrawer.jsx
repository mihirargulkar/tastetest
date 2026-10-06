const LABEL = { test: "✅ Test here.", maybe: "➖ Maybe.", skip: "⛔ Skip." };

function Meter({ fit, confidence }) {
  const pct = Math.max(-1, Math.min(1, fit / 2.5)) * 50;
  const bar = pct >= 0 ? { left: "50%", width: `${pct}%` } : { left: `${50 + pct}%`, width: `${-pct}%`, background: "var(--red)" };
  return (
    <div>
      <div className="meter"><i /><b style={bar} /></div>
      <div className="src">fit vs. chain average (relative to each region) · confidence: {confidence}</div>
    </div>
  );
}

function Entity({ e }) {
  return (
    <div className="ent">
      {e.image ? <img src={e.image} alt="" /> : <span className="thumb" />}
      <span>{e.name}</span>
      {e.affinity != null && <span className="src">· affinity {e.affinity.toFixed(2)}</span>}
    </div>
  );
}

function Section({ title, children }) {
  return <div className="sec"><div className="label" style={{ marginTop: 0 }}>{title}</div>{children}</div>;
}

export default function StoreDrawer({ store, brief, onClose }) {
  return (
    <aside className="card drawer" aria-label={`${store.name} brief`}>
      <header className="drawer-head">
        <div><h2>{store.name}</h2><div className="src">{store.address}</div></div>
        {store.fit != null && <span className={`fit ${store.fit >= 0 ? "up" : "dn"}`}>{store.fit > 0 ? "+" : ""}{store.fit.toFixed(1)}</span>}
        <button className="close" aria-label="Close" onClick={onClose}>×</button>
      </header>
      {!brief ? <p className="muted">Building this store's brief…</p> : (
        <>
          <p className="verdict"><b>{LABEL[brief.label]}</b> {brief.verdict}</p>
          {store.fit != null && <Meter fit={store.fit} confidence={store.confidence} />}
          <Section title="Why">
            <div className="chips">{brief.why_tags.map((t) => <span key={t.id} className="chip" style={{ paddingRight: 10 }}>{t.name}</span>)}</div>
            <div className="src">Qloo taste analysis · 1.2 km radius</div>
          </Section>
          {brief.partners.length > 0 && <Section title="Local collab partners">{brief.partners.map((p) => <Entity key={p.id} e={p} />)}</Section>}
          <Section title="Menu cues"><ul>{brief.menu_cues.map((c, i) => <li key={i}>• {c}</li>)}</ul></Section>
        </>
      )}
    </aside>
  );
}
