# wialon_geocercas.py
# Backend FastAPI para Wialon
# - Unidades
# - Recursos
# - Geocercas (forma nativa de Wialon)
# - Cruce local unidad ↔ geocerca
# - /wialon/snapshot para traer todo de un jalón
#
# "Truquitos" para agilizar:
#  - caché en memoria (unidades, recursos, geocercas)
#  - snapshot que reduce las peticiones desde el frontend
#  - posibilidad de pedir solo un recurso en el snapshot

import os
import time
import json
from typing import Optional, Dict, Any, List

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from math import radians, sin, cos, sqrt, atan2

# -------------------------------------------------------------
# Configuración y app
# -------------------------------------------------------------
load_dotenv()
WIALON_BASE = os.getenv("WIALON_BASE", "https://hst-api.wialon.com/wialon/ajax.html")
WIALON_TOKEN = os.getenv("WIALON_TOKEN", "")

app = FastAPI(title="Wialon API — Unidades, Recursos y Geocercas", version="1.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------
# Cachés simples en memoria
# -------------------------------------------------------------
SESSION_SID: Optional[str] = None
SESSION_TS: float = 0

CACHE_UNITS: Dict[str, Any] = {"ts": 0, "data": None}
CACHE_RESOURCES: Dict[str, Any] = {"ts": 0, "data": None}
CACHE_GEOFENCES: Dict[int, Dict[str, Any]] = {}  # por resource_id

# segundos de vida
TTL_UNITS = 15       # posiciones se mueven rápido
TTL_RESOURCES = 120  # casi no cambia
TTL_GEO = 300        # geocercas casi no cambian


# -------------------------------------------------------------
# Cliente Wialon
# -------------------------------------------------------------
class Wialon:
    @staticmethod
    def _get_sid() -> str:
        """Obtiene y cachea el SID usando el token."""
        global SESSION_SID, SESSION_TS
        if SESSION_SID and time.time() - SESSION_TS < 240:
            return SESSION_SID

        if not WIALON_TOKEN:
            raise HTTPException(500, "Falta WIALON_TOKEN en entorno (.env)")

        r = requests.get(
            WIALON_BASE,
            params={"svc": "token/login", "params": json.dumps({"token": WIALON_TOKEN})},
            timeout=15,
        )
        data = r.json()
        if "eid" not in data:
            # a veces alguien pone directamente el SID en lugar del token
            # intentamos usarlo así
            if "error" in data:
                raise HTTPException(502, f"token/login falló: {data}")
        SESSION_SID = data.get("eid") or data.get("sid") or WIALON_TOKEN
        SESSION_TS = time.time()
        return SESSION_SID

    @staticmethod
    def call(svc: str, params: dict) -> dict:
        """Llama Wialon con reintento básico."""
        sid = Wialon._get_sid()
        r = requests.get(
            WIALON_BASE,
            params={"svc": svc, "params": json.dumps(params), "sid": sid},
            timeout=30,
        )
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            # si fue error de credencial, reintentar 1 vez
            if data["error"] in (1, 2, 3, 4, 5, 8):
                SESSION_SID = None
                sid = Wialon._get_sid()
                r = requests.get(
                    WIALON_BASE,
                    params={"svc": svc, "params": json.dumps(params), "sid": sid},
                    timeout=30,
                )
                data = r.json()
                if isinstance(data, dict) and data.get("error"):
                    raise HTTPException(502, f"Error {data['error']} en {svc}")
            else:
                raise HTTPException(502, f"Error {data['error']} en {svc}")
        return data


# -------------------------------------------------------------
# Helpers de geometría
# -------------------------------------------------------------
def point_in_polygon(lat: float, lon: float, ring: list[dict]) -> bool:
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        j = (i - 1) % n
        xi, yi = ring[i]["lon"], ring[i]["lat"]
        xj, yj = ring[j]["lon"], ring[j]["lat"]
        intersect = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersect:
            inside = not inside
    return inside


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# -------------------------------------------------------------
# Endpoints de info general / debug
# -------------------------------------------------------------
@app.get("/")
def root():
    return {
        "ok": True,
        "endpoints": [
            "/wialon/units",
            "/wialon/resources",
            "/wialon/resources/{resource_id}/geofences",
            "/wialon/units/in-geofences/local",
            "/wialon/snapshot",
            "/debug/routes",
            "/debug/env",
        ],
    }


@app.get("/debug/routes")
def debug_routes():
    return {"routes": [getattr(r, "path", None) or getattr(r, "path_format", "") for r in app.routes]}


@app.get("/debug/env")
def debug_env():
    return {
        "WIALON_BASE": WIALON_BASE,
        "WIALON_TOKEN_len": len(WIALON_TOKEN),
        "sid_cached": SESSION_SID is not None,
        "sid_source": "token/login or manual",
    }


# -------------------------------------------------------------
# Unidades (con caché)
# -------------------------------------------------------------
def get_units_cached() -> list[dict]:
    now = time.time()
    if CACHE_UNITS["data"] and now - CACHE_UNITS["ts"] < TTL_UNITS:
        return CACHE_UNITS["data"]

    data = Wialon.call(
        "core/search_items",
        {
            "spec": {
                "itemsType": "avl_unit",
                "propName": "sys_name",
                "propValueMask": "*",
                "sortType": "sys_name",
            },
            "force": 1,
            "flags": 1025,
            "from": 0,
            "to": 0,
        },
    )
    items = data.get("items", [])
    out = []
    for u in items:
        pos = u.get("pos") or {}
        out.append(
            {
                "id": u.get("id"),
                "name": u.get("nm"),
                "lat": pos.get("y"),
                "lon": pos.get("x"),
                "t": pos.get("t"),
                "speed": pos.get("s"),
            }
        )
    CACHE_UNITS["ts"] = now
    CACHE_UNITS["data"] = out
    return out


@app.get("/wialon/units")
def list_units():
    return {"count": len(get_units_cached()), "units": get_units_cached()}


# -------------------------------------------------------------
# Recursos (con caché)
# -------------------------------------------------------------
def get_resources_cached() -> list[dict]:
    now = time.time()
    if CACHE_RESOURCES["data"] and now - CACHE_RESOURCES["ts"] < TTL_RESOURCES:
        return CACHE_RESOURCES["data"]

    data = Wialon.call(
        "core/search_items",
        {
            "spec": {
                "itemsType": "avl_resource",
                "propName": "sys_name",
                "propValueMask": "*",
                "sortType": "sys_name",
            },
            "force": 1,
            "flags": 1,
            "from": 0,
            "to": 0,
        },
    )
    items = data.get("items", [])
    out = [{"id": r.get("id"), "name": r.get("nm")} for r in items]
    CACHE_RESOURCES["ts"] = now
    CACHE_RESOURCES["data"] = out
    return out


@app.get("/wialon/resources")
def list_resources():
    res = get_resources_cached()
    return {"count": len(res), "resources": res}


# -------------------------------------------------------------
# Geocercas de un recurso (con caché)
# -------------------------------------------------------------
def get_geofences_of_resource_cached(resource_id: int) -> list[dict]:
    now = time.time()
    if resource_id in CACHE_GEOFENCES:
        if now - CACHE_GEOFENCES[resource_id]["ts"] < TTL_GEO:
            return CACHE_GEOFENCES[resource_id]["data"]

    # forma nativa de Wialon
    raw = Wialon.call("resource/get_zone_data", {"itemId": resource_id, "flags": 0x1F}) or {}
    iterable = (raw.values() if isinstance(raw, dict) else raw) or []

    zones: list[dict] = []
    for z in iterable:
        name = z.get("n") or z.get("name") or ""
        jp = z.get("jp") or {}
        item = {
            "id": z.get("id") or z.get("i"),
            "name": name,
            "type": z.get("t"),
            "color_argb": z.get("c") or jp.get("color_argb"),
            "points": None,
            "center": None,
            "radius": None,
        }

        # polígono
        if jp.get("points"):
            item["points"] = [{"lat": p["lat"], "lon": p["lon"]} for p in jp["points"]]
        elif z.get("p"):
            norm = []
            for p in z["p"]:
                # wialon suele mandar x=lon, y=lat
                lon = p.get("x") if isinstance(p, dict) else p[0]
                lat = p.get("y") if isinstance(p, dict) else p[1]
                norm.append({"lat": float(lat), "lon": float(lon)})
            item["points"] = norm

        # círculo
        if jp.get("center") and jp.get("radius"):
            item["center"] = jp["center"]
            item["radius"] = jp["radius"]
        elif z.get("ct") and z.get("r"):
            item["center"] = {"lat": z["ct"]["y"], "lon": z["ct"]["x"]}
            item["radius"] = z["r"]

        zones.append(item)

    CACHE_GEOFENCES[resource_id] = {"ts": now, "data": zones}
    return zones


@app.get("/wialon/resources/{resource_id}/geofences")
def geofences_of_resource(resource_id: int):
    zones = get_geofences_of_resource_cached(resource_id)
    return {"resource_id": resource_id, "count": len(zones), "geofences": zones}


# -------------------------------------------------------------
# Cruce local unidad ↔ geocerca
# -------------------------------------------------------------
@app.get("/wialon/units/in-geofences/local", summary="Cruce local (geométrico)")
def all_units_in_geofences_local():
    units = [u for u in get_units_cached() if u.get("lat") and u.get("lon")]
    resources = get_resources_cached()

    result: dict[str, dict[str, list[int]]] = {}

    for r in resources:
        rid = r["id"]
        zones = get_geofences_of_resource_cached(rid)
        polys: list[tuple[int, list[dict]]] = []
        circs: list[tuple[int, float, float, float]] = []

        for z in zones:
            if z.get("points"):
                polys.append((int(z["id"]), z["points"]))
            elif z.get("center") and z.get("radius"):
                c = z["center"]
                circs.append((int(z["id"]), c["lat"], c["lon"], float(z["radius"])))

        by_unit: dict[str, list[int]] = {}
        for u in units:
            lat, lon = float(u["lat"]), float(u["lon"])
            inside: list[int] = []

            for zid, ring in polys:
                if point_in_polygon(lat, lon, ring):
                    inside.append(zid)

            for zid, clat, clon, rad in circs:
                if haversine_m(lat, lon, clat, clon) <= rad:
                    inside.append(zid)

            if inside:
                by_unit[str(u["id"])] = inside

        result[str(rid)] = by_unit

    return {"ok": True, "result": result}


# -------------------------------------------------------------
# Snapshot: TODO de un jalón (rápido para frontend)
# -------------------------------------------------------------
@app.get("/wialon/snapshot", summary="Unidades + recursos + geocercas (opcionalmente de 1 recurso)")
def wialon_snapshot(resource_id: Optional[int] = Query(None, description="Si lo mandas, solo ese recurso")):
    # 1. unidades (del caché)
    units = get_units_cached()

    # 2. recursos (del caché)
    resources = get_resources_cached()

    # 3. geocercas por recurso (del caché)
    geofences_by_resource: dict[str, list[dict]] = {}
    if resource_id is not None:
        geofences_by_resource[str(resource_id)] = get_geofences_of_resource_cached(resource_id)
    else:
        for r in resources:
            rid = r["id"]
            geofences_by_resource[str(rid)] = get_geofences_of_resource_cached(rid)

    return {
        "units": units,
        "resources": resources,
        "geofences_by_resource": geofences_by_resource,
    }
