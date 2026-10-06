import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const STYLE = "https://tiles.openfreemap.org/styles/positron"; // free, no API key

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

export default function MapView({ stores, selected, metro, onSelect }) {
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
          "circle-radius": ["case", ["get", "selected"], 11, 7],
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

  useEffect(() => {
    if (ready) map.current.getSource("stores").setData(toGeoJSON(stores, selected));
  }, [ready, stores, selected]);

  useEffect(() => {
    const inView = stores.filter((s) => !metro || s.metro === metro);
    if (!ready || inView.length === 0) return;
    const bounds = new maplibregl.LngLatBounds();
    inView.forEach((s) => bounds.extend([s.lon, s.lat]));
    const w = container.current.clientWidth;
    let padding = 40;
    if (w >= 1100) padding = { top: 120, bottom: 140, left: 380, right: 420 };
    else if (w > 800) { const k = Math.min(1, (0.6 * w) / 800); padding = { top: 120, bottom: 140, left: 380 * k, right: 420 * k }; }
    map.current.fitBounds(bounds, { padding, maxZoom: 13, duration: 800 });
  }, [ready, metro, stores.length]);

  return <div ref={container} className="map" role="region" aria-label="Map of stores colored by fit" />;
}
