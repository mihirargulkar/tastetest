import { useState } from "react";
import ProgressLog from "./ProgressLog";

export default function InputCard({ demos, lto, setLto, signature, setSignature, busy, onDemo, onReadTaste, onScore, storeCount, runTrace }) {
  const [instruction, setInstruction] = useState("");

  function refine(e) {
    e.preventDefault();
    if (!instruction.trim()) return;
    onReadTaste(instruction.trim());
    setInstruction("");
  }

  return (
    <section className="card input-card" aria-label="New limited-time offer">
      <h1>TasteTest</h1>
      <p className="sub">Where should your next limited-time drink launch first?</p>
      {demos.length > 0 && (
        <div>{demos.map((d) => <button key={d.slug} className="pill" onClick={() => onDemo(d.slug)}>{d.title}</button>)}</div>
      )}
      <label className="label" htmlFor="lto">New LTO</label>
      <textarea id="lto" maxLength={500} value={lto} onChange={(e) => setLto(e.target.value)}
        placeholder="e.g. matcha-yuzu cold brew, bright and citrusy, for a younger crowd" />
      <button className="btn secondary" disabled={!lto.trim() || !!busy} onClick={() => onReadTaste()}>
        {busy === "signature" ? "Reading the taste…" : "Read the taste"}
      </button>
      {busy === "signature" && <ProgressLog kind="signature" trace={runTrace} />}

      {signature.length > 0 && (
        <>
          <div className="label">Taste signature</div>
          <div className="chips">
            {signature.map((i) => (
              <span key={i.id} className="chip" title={`weight ${i.weight}`}>
                {i.substituted_from && <><s>{i.substituted_from}</s>&nbsp;→</>}
                {i.name}
                <button aria-label={`Remove ${i.name}`} disabled={!!busy}
                  onClick={() => setSignature(signature.filter((x) => x.id !== i.id))}>×</button>
              </span>
            ))}
          </div>
          <form onSubmit={refine}>
            <input className="input" aria-label="Adjust the signature" maxLength={300} value={instruction}
              onChange={(e) => setInstruction(e.target.value)} disabled={!!busy}
              placeholder='Adjust: “aim at an older crowd”' />
          </form>
          <button className="btn" disabled={!!busy || signature.length === 0} onClick={onScore}>
            {busy === "score" ? "Scoring…" : `Score ${storeCount} stores`}
          </button>
        </>
      )}
    </section>
  );
}
