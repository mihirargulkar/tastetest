import { useEffect, useMemo, useState } from "react";
import { getJSON, postJSON, streamPost } from "./api";
import MapView from "./MapView";
import InputCard from "./InputCard";
import RankCard from "./RankCard";
import TraceBar from "./TraceBar";
import StoreDrawer from "./StoreDrawer";

export default function App() {
  const [stores, setStores] = useState([]);
  const [demos, setDemos] = useState([]);
  const [lto, setLto] = useState("");
  const [signature, setSignature] = useState([]);
  const [result, setResult] = useState(null);
  const [briefs, setBriefs] = useState({});
  const [trace, setTrace] = useState([]);
  const [selected, setSelected] = useState(null);
  const [metro, setMetro] = useState(null);
  const [busy, setBusy] = useState(null); // "signature" | "score" | null
  const [error, setError] = useState(null);
  const [runFrom, setRunFrom] = useState(0);

  useEffect(() => {
    Promise.all([getJSON("/api/stores"), getJSON("/api/demos")])
      .then(([s, d]) => { setStores(s); setDemos(d); const want = new URLSearchParams(location.search).get("demo"); if (d.length) loadDemo(d.some((x) => x.slug === want) ? want : d[0].slug); })
      .catch((e) => setError(e.message));
  }, []);

  async function loadDemo(slug) {
    try {
      const d = await getJSON(`/api/demos/${slug}`);
      setLto(d.lto); setSignature(d.signature); setResult(d.result);
      setBriefs(d.briefs || {}); setTrace(d.trace || []); setSelected(null); setError(null);
    } catch (e) { setError(e.message); }
  }

  function onEvent(ev) {
    if (ev.type === "trace") setTrace((t) => [...t, ev]);
    else if (ev.type === "signature") setSignature(ev.items);
    else if (ev.type === "result") setResult(ev);
    else if (ev.type === "error") setError(ev.message);
  }

  async function run(kind, url, body) {
    setBusy(kind); setError(null);
    setRunFrom(kind === "signature" ? 0 : trace.length);
    if (kind === "signature") setTrace([]);
    if (kind === "score") { setResult(null); setBriefs({}); setSelected(null); }
    let terminal = false;
    const want = kind === "signature" ? "signature" : "result";
    try {
      await streamPost(url, body, (ev) => { if (ev.type === want || ev.type === "error") terminal = true; onEvent(ev); });
      if (!terminal) setError("The run ended before finishing. Try again, or use a preloaded example.");
    } catch (e) { setError(e.message); } finally { setBusy(null); }
  }

  const readTaste = (instruction) =>
    run("signature", "/api/signature", instruction ? { lto, current: signature, instruction } : { lto });
  const scoreStores = () => run("score", "/api/score", { signature });

  const shown = result ? result.stores : stores;
  const selectedStore = shown.find((s) => s.id === selected);
  const metros = useMemo(() => [...new Set(stores.map((s) => s.metro))].sort(), [stores]);

  async function openStore(id) {
    setSelected(id);
    if (briefs[id] || signature.length === 0) return;
    const fit = result?.stores.find((s) => s.id === id)?.fit ?? null;
    try {
      const b = await postJSON("/api/brief", { store_id: id, signature, fit });
      setBriefs((m) => ({ ...m, [id]: b }));
    } catch (e) { setError(e.message); }
  }

  const runTrace = trace.slice(runFrom);

  return (
    <div className="app">
      <MapView stores={shown} selected={selected} metro={metro} onSelect={openStore} scanning={busy === "score"} />
      <InputCard demos={demos} lto={lto} setLto={setLto} signature={signature} setSignature={setSignature}
        busy={busy} onDemo={loadDemo} onReadTaste={readTaste} onScore={scoreStores} storeCount={stores.length} runTrace={runTrace} />
      {selectedStore
        ? <StoreDrawer store={selectedStore} signature={signature} allStores={result?.stores || []} brief={briefs[selected]} onClose={() => setSelected(null)} />
        : <RankCard result={result} busy={busy === "score"} onSelect={openStore} runTrace={runTrace} storeCount={stores.length} />}
      <TraceBar trace={trace} stability={result?.stability} metros={metros} metro={metro} onMetro={setMetro} />
      {error && <div className="toast" role="alert">{error} <button onClick={() => setError(null)} aria-label="Dismiss">×</button></div>}
    </div>
  );
}
