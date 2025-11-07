"use client";

import React, { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";

const MapaLeafletClient = dynamic(() => import("@/components/MapaLeafletClient"), { ssr: false });

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type Unit = { id: number; name: string; lat?: number; lon?: number; t?: number; speed?: number; course?: number };
type Resource = { id: number; name: string };
type Geofence = {
  id: number;
  name: string;
  categoria?: string;
  color_argb?: number;
  type?: number; // 1 polygon, 3 circle (común)
  geojson?: any;
  points?: Array<{ lat: number; lon: number }>;
  center?: { lat: number; lon: number };
  radius?: number;
};

// Utilidades
const argbToRgba = (argb?: number) =>
  argb == null
    ? undefined
    : (() => {
        const a = ((argb >>> 24) & 0xff) / 255;
        const r = (argb >>> 16) & 0xff;
        const g = (argb >>> 8) & 0xff;
        const b = argb & 0xff;
        return `rgba(${r},${g},${b},${a.toFixed(3)})`;
      })();

export default function MapaGeocercasPage() {
  const [units, setUnits] = useState<Unit[]>([]);
  const [resources, setResources] = useState<Resource[]>([]);
  const [zonesByRes, setZonesByRes] = useState<Record<string, Geofence[]>>({});
  const [filter, setFilter] = useState<"all" | "sucursal" | "segura" | "riesgo">("all");
  const [loading, setLoading] = useState(false);

  const [center] = useState<[number, number]>([20.6736, -103.344]); // GDL
  const [zoom] = useState(6);

  async function fetchUnits() {
    const r = await fetch(`${API}/wialon/units`);
    const j = await r.json();
    return j.units as Unit[];
  }
  async function fetchResources() {
    const r = await fetch(`${API}/wialon/resources`);
    const j = await r.json();
    return j.resources as Resource[];
  }
  async function fetchGeofencesOf(resourceId: number) {
    const r = await fetch(`${API}/wialon/resources/${resourceId}/geofences`);
    const j = await r.json();
    return j.geofences as Geofence[];
  }

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [u, res] = await Promise.all([fetchUnits(), fetchResources()]);
        setUnits(u);
        setResources(res);
        const entries = await Promise.all(res.map(async (r) => [String(r.id), await fetchGeofencesOf(r.id)] as const));
        const zbr: Record<string, Geofence[]> = {};
        entries.forEach(([rid, arr]) => (zbr[rid] = arr));
        setZonesByRes(zbr);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Construye features (polígonos / círculos) y aplica color: primero color_argb de Wialon, luego paleta por categoría
  const allFeatures = useMemo(() => {
    const feats: any[] = [];
    Object.values(zonesByRes).forEach((zs) => {
      zs.forEach((z) => {
        const cat = (z.categoria || "").toLowerCase();
        if (filter !== "all" && cat !== filter) return;

        const color =
          argbToRgba(z.color_argb) ||
          (cat === "sucursal"
            ? "rgba(37,99,235,0.55)"
            : cat === "segura"
            ? "rgba(16,185,129,0.55)"
            : cat === "riesgo"
            ? "rgba(239,68,68,0.55)"
            : "rgba(107,114,128,0.35)");

        if (z.geojson) {
          feats.push({
            type: "Feature",
            properties: { name: z.name, categoria: cat, color },
            geometry: z.geojson.type ? z.geojson : { type: "Polygon", coordinates: z.geojson },
          });
          return;
        }

        if (z.points && z.points.length > 2) {
          feats.push({
            type: "Feature",
            properties: { name: z.name, categoria: cat, color },
            geometry: { type: "Polygon", coordinates: [z.points.map((p) => [p.lon, p.lat])] },
          });
          return;
        }

        if (z.center && z.radius) {
          feats.push({
            type: "Feature",
            properties: { name: z.name, categoria: cat, color, _circle: true, center: z.center, radius: z.radius },
          });
        }
      });
    });
    return feats;
  }, [zonesByRes, filter]);

  const circleZones = useMemo(() => allFeatures.filter((f) => f.properties?._circle), [allFeatures]);
  const polygonFeatures = useMemo(() => allFeatures.filter((f) => !f.properties?._circle), [allFeatures]);

  // ---- Nuevo: cálculo de fitBounds (polígonos + círculos + unidades)
  const fitBounds = useMemo(() => {
    let minLat = 90, maxLat = -90, minLon = 180, maxLon = -180;
    let touched = false;

    // Polígonos
    for (const f of polygonFeatures) {
      const g = f.geometry;
      if (!g) continue;
      const type = g.type;
      const coords = g.coordinates;
      const push = (lng: number, lat: number) => {
        if (isFinite(lat) && isFinite(lng)) {
          touched = true;
          if (lat < minLat) minLat = lat;
          if (lat > maxLat) maxLat = lat;
          if (lng < minLon) minLon = lng;
          if (lng > maxLon) maxLon = lng;
        }
      };
      if (type === "Polygon") {
        for (const ring of coords) for (const [lng, lat] of ring) push(lng, lat);
      } else if (type === "MultiPolygon") {
        for (const poly of coords) for (const ring of poly) for (const [lng, lat] of ring) push(lng, lat);
      }
    }

    // Círculos (tomamos el centro)
    for (const f of circleZones) {
      const c = f.properties?.center;
      if (c) {
        touched = true;
        if (c.lat < minLat) minLat = c.lat;
        if (c.lat > maxLat) maxLat = c.lat;
        if (c.lon < minLon) minLon = c.lon;
        if (c.lon > maxLon) maxLon = c.lon;
      }
    }

    // Unidades
    for (const u of units) {
      if (u.lat != null && u.lon != null) {
        touched = true;
        if (u.lat < minLat) minLat = u.lat;
        if (u.lat > maxLat) maxLat = u.lat;
        if (u.lon < minLon) minLon = u.lon;
        if (u.lon > maxLon) maxLon = u.lon;
      }
    }

    if (!touched) return undefined;
    // [SW, NE]
    return [[minLat, minLon], [maxLat, maxLon]] as [[number, number], [number, number]];
  }, [polygonFeatures, circleZones, units]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-6">
        <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Mapa — Unidades & Geocercas</h1>
            <p className="text-sm text-gray-500">Colores priorizan el definido en Wialon; zoom automático al contenido visible.</p>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value as any)}
              className="border rounded-lg px-2 py-2 text-sm bg-white"
            >
              <option value="all">Todas</option>
              <option value="sucursal">Sucursal</option>
              <option value="segura">Segura</option>
              <option value="riesgo">Riesgo</option>
            </select>
            {loading && <span className="text-xs text-gray-500">Cargando…</span>}
          </div>
        </header>

        <MapaLeafletClient
          center={center}
          zoom={zoom}
          polygonFeatures={polygonFeatures}
          circleZones={circleZones}
          units={units}
          fitBounds={fitBounds}  // ← auto-zoom
        />
      </div>
    </div>
  );
}
