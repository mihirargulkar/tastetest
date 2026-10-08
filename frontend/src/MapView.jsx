import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

maplibregl.setWorkerUrl(workerUrl);

const STYLE = "https://tiles.openfreemap.org/styles/positron"; // free, no API key

const RADIUS = ["case", ["get", "selected"], 11, 7];
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const greyed = (stores) => stores.map((s) => ({ ...s, fit: null }));

function toGeoJSON(stores, selected) {
  return {
    type: "FeatureCollection",
    features: stores.map((s) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      properties: { id: s.id, fit: s.fit ?? null, confidence: s.confidence ?? "none", selected: s.id === selected },
    })),
  };
}

export default function MapView({ stores, selected, metro, onSelect, scanning }) {
  const container = useRef(null);
  const map = useRef(null);
  const onSelectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const m = new maplibregl.Map({ container: container.current, style: STYLE, center: [-98, 39], zoom: 3.5,
      attributionControl: { compact: true } });
    map.current = m;
    m.on("load", () => {
      m.addSource("stores", { type: "geojson", data: toGeoJSON([], null) });
      m.addLayer({
        id: "stores", type: "circle", source: "stores",
        paint: {
          "circle-radius": RADIUS,
          "circle-color": ["case", ["==", ["get", "fit"], null], "#9b958a",
            ["interpolate", ["linear"], ["get", "fit"], -2, "#b4432f", 0, "#d9c9a0", 2, "#2f7d3a"]],
          "circle-opacity": ["match", ["get", "confidence"], "low", 0.4, 1],
          "circle-stroke-width": ["case", ["get", "selected"], 2.5, 1],
          "circle-stroke-color": "#1d1d1f",
        },
      });
      m.on("click", "stores", (e) => onSelectRef.current(e.features[0].properties.id));
      m.on("mouseenter", "stores", () => { m.getCanvas().style.cursor = "pointer"; });
      m.on("mouseleave", "stores", () => { m.getCanvas().style.cursor = ""; });
      setReady(true);
    });
    return () => m.remove();
  }, []);

  const wasScanning = useRef(false);
  useEffect(() => {
    if (!ready) return;
    const src = map.current.getSource("stores");
    const reveal = wasScanning.current && !scanning && stores.some((s) => s.fit != null) && !reduceMotion();
    wasScanning.current = scanning;
    if (!reveal) {
      // While scanning, hide fits so a result that lands a render before busy clears doesn't flash in early.
      src.setData(toGeoJSON(scanning ? greyed(stores) : stores, selected));
      return;
    }
    const order = [...stores].sort((a, b) => (b.fit ?? -99) - (a.fit ?? -99)).map((s) => s.id);
    const batch = Math.ceil(order.length / 16); // about 1 s at 60 ms per batch
    const timers = [];
    let k = 0;
    const step = () => {
      k = Math.min(order.length, k + batch);
      const shown = new Set(order.slice(0, k));
      src.setData(toGeoJSON(stores.map((s) => (shown.has(s.id) ? s : { ...s, fit: null })), selected));
      if (k < order.length) timers.push(setTimeout(step, 60));
    };
    step();
    return () => timers.forEach(clearTimeout);
  }, [ready, stores, selected, scanning]);

  useEffect(() => {
    if (!ready || !scanning || reduceMotion()) return;
    const m = map.current;
    const t0 = performance.now();
    let raf;
    const tick = (now) => {
      m.setPaintProperty("stores", "circle-radius", 8 + Math.sin((now - t0) / 350)); // 7..9 px, no React state
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); m.setPaintProperty("stores", "circle-radius", RADIUS); };
  }, [ready, scanning]);

  useEffect(() => {
    const inView = stores.filter((s) => !metro || s.metro === metro);
    if (!ready || inView.length === 0) return;
    const bounds = new maplibregl.LngLatBounds();
    inView.forEach((s) => bounds.extend([s.lon, s.lat]));
    const w = container.current.clientWidth;
    let padding = 40;
    if (w >= 1100) padding = { top: 120, bottom: 140, left: 380, right: 420 };
    else if (w > 900) { const k = Math.min(1, (0.6 * w) / 800); padding = { top: 120, bottom: 140, left: 380 * k, right: 420 * k }; }
    map.current.fitBounds(bounds, { padding, maxZoom: 13, duration: 800 });
  }, [ready, metro, stores.length]);

  return (
    <div ref={container} className="map" role="region" aria-label="Map of stores colored by fit">
      {scanning && !reduceMotion() && <div className="map-scan" aria-hidden="true" />}
    </div>
  );
}
