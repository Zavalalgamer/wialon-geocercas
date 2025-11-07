"use client";

import React, { useEffect } from "react";
import {
  MapContainer,
  TileLayer,
  LayersControl,
  LayerGroup,
  GeoJSON,
  Circle,
  CircleMarker,
  Popup,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";

import type * as L from "leaflet";
import type { Feature, FeatureCollection, Geometry } from "geojson";

type Unit = {
  id: number;
  name: string;
  lat?: number;
  lon?: number;
  t?: number;
  speed?: number;
};

type Bounds = [[number, number], [number, number]] | undefined;

type Props = {
  center: [number, number];
  zoom: number;
  polygonFeatures: any[]; // Feature[]
  circleZones: any[];     // Feature[] con properties.center/radius
  units: Unit[];
  fitBounds?: Bounds;     // ← NUEVO
};

function FitToBounds({ bounds }: { bounds?: Bounds }) {
  const map = useMap();
  useEffect(() => {
    if (!bounds) return;
    try {
      (map as any).fitBounds(bounds as any, {
        padding: [24, 24],
        maxZoom: 12,
      });
    } catch {}
  }, [map, JSON.stringify(bounds)]);
  return null;
}

export default function MapaLeafletClient({
  center,
  zoom,
  polygonFeatures,
  circleZones,
  units,
  fitBounds,
}: Props) {
  return (
    <div
      className="rounded-2xl overflow-hidden border border-gray-200 bg-white shadow-sm"
      style={{ height: 600 }}
    >
      <MapContainer
        center={center}
        zoom={zoom}
        style={{ height: "100%", width: "100%" }}
        scrollWheelZoom
      >
        {/* Auto-zoom */}
        <FitToBounds bounds={fitBounds} />

        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="OpenStreetMap">
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution="&copy; OpenStreetMap"
            />
          </LayersControl.BaseLayer>

          <LayersControl.BaseLayer name="Toner (Carto Light)">
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
              attribution="&copy; OpenStreetMap & Carto"
            />
          </LayersControl.BaseLayer>

          <LayersControl.Overlay checked name="Geocercas">
            <LayerGroup>
              <GeoJSON
                data={
                  {
                    type: "FeatureCollection",
                    features: polygonFeatures as Feature<Geometry, any>[],
                  } as FeatureCollection
                }
                style={(feat: any): L.PathOptions => ({
                  color: feat?.properties?.color || "#475569",
                  weight: 2,
                  fillOpacity: 0.35,
                })}
                onEachFeature={(feature: Feature, layer: L.Layer) => {
                  const p: any = (feature as any).properties || {};
                  layer.bindPopup(
                    `<b>${p.name || ""}</b><br/>Categoría: ${p.categoria || "—"}`
                  );
                }}
              />

              {circleZones.map((f: any, idx: number) =>
                f.properties?.center ? (
                  <Circle
                    key={`cz-${idx}`}
                    center={[f.properties.center.lat, f.properties.center.lon]}
                    radius={f.properties.radius || 200}
                    pathOptions={{
                      color: f.properties.color || "#64748b",
                      fillOpacity: 0.35,
                    }}
                  >
                    <Popup>
                      <div className="text-sm">
                        <div className="font-medium">{f.properties.name}</div>
                        <div>Categoría: {f.properties.categoria || "—"}</div>
                      </div>
                    </Popup>
                  </Circle>
                ) : null
              )}
            </LayerGroup>
          </LayersControl.Overlay>

          <LayersControl.Overlay checked name="Unidades">
            <LayerGroup>
              {units.map((u) =>
                u.lat != null && u.lon != null ? (
                  <CircleMarker
                    key={u.id}
                    center={[u.lat, u.lon]}
                    radius={6}
                    pathOptions={{ color: "#111827", fillOpacity: 0.9 }}
                  >
                    <Popup>
                      <div className="text-sm">
                        <div className="font-medium">{u.name}</div>
                        <div className="text-xs text-gray-500">
                          {u.lat.toFixed(6)}, {u.lon.toFixed(6)}
                        </div>
                        <div className="text-xs">
                          Vel: {u.speed ?? "—"} km/h
                        </div>
                      </div>
                    </Popup>
                  </CircleMarker>
                ) : null
              )}
            </LayerGroup>
          </LayersControl.Overlay>
        </LayersControl>
      </MapContainer>
    </div>
  );
}
