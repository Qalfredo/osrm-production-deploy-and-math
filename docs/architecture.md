# Architecture and Design Decisions

## Data pipeline

```
Geofabrik (geofabrik.de)
         │
         │  venezuela-latest.osm.pbf (~200 MB)
         │  Updated daily by Geofabrik
         ▼
  ┌─────────────┐
  │ osrm-extract│  Parses OSM → builds edge-based road graph
  │  (car.lua)  │  Applies car profile: speed limits, turn penalties,
  └──────┬──────┘  one-way restrictions, access rules
         │
         │  venezuela-latest.osrm + companion files (~500 MB)
         ▼
  ┌──────────────┐
  │ osrm-contract│  Contraction Hierarchies preprocessing
  │  (CH pipeline│  Assigns node importance ranks
  └──────┬───────┘  Adds shortcut edges (~20–60 min, runs offline)
         │
         │  venezuela-latest.osrm.hsgr (~1.5 GB in RAM)
         ▼
  ┌─────────────┐
  │ osrm-routed │  HTTP API server on :5000
  │ --algorithm │  Serves: /table, /route, /nearest, /match
  │     ch      │  Answers queries in <1 ms using CH bidirectional Dijkstra
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │ Python client│  OSRMClient.distance_matrix(), .route(), .nearest()
  │ client/     │  Handles lat/lon ↔ lon/lat conversion
  │ osrm_client │  Returns np.ndarray (metres, seconds)
  └─────────────┘
```

## Algorithm choice: CH vs MLD

OSRM ships two preprocessing pipelines. This repo uses **Contraction Hierarchies (CH)**.

| | CH (`osrm-contract`) | MLD (`osrm-partition` + `osrm-customize`) |
|---|---|---|
| Query speed | Faster | Slightly slower |
| Distance matrix | Optimal | Good |
| Live traffic updates | Not supported | Supported |
| Preprocessing time | Longer (20–60 min) | Shorter |
| OSRM recommendation | Distance matrices | Default / general |

The primary use case here is distance matrix computation (`/table`), not live traffic navigation. The [OSRM documentation](https://github.com/Project-OSRM/osrm-backend#quick-start) explicitly recommends CH for this use case.

## Memory requirements

| Asset | Disk | RAM at runtime |
|---|---|---|
| Venezuela `.osm.pbf` | ~200 MB | — |
| Extracted graph (`.osrm.*`) | ~500 MB | — |
| CH graph in memory | — | ~2.5–3 GB |
| Minimum instance | — | 4 GB (t3.medium) |

Rule of thumb: the extracted + contracted graph requires roughly 10–15× the raw `.osm.pbf` size in RAM.

## Coordinate conventions

OSRM's HTTP API uses `longitude,latitude` order (GeoJSON convention). The Python client (`OSRMClient`) accepts `(latitude, longitude)` tuples and handles the flip internally — all public methods follow the common `(lat, lon)` convention.

## OSM data update strategy

Geofabrik updates regional extracts daily. The OSRM preprocessing pipeline is offline and can be re-run without affecting the running server. Recommended update frequency: monthly for Venezuela (road network changes slowly).

Update procedure:
1. Download fresh `.osm.pbf` on a separate machine or at a low-traffic time
2. Run `osrm-extract` and `osrm-contract` (offline, takes ~1 hour)
3. Swap the data files and restart `osrm-routed`

## Attribution

All routing engine code belongs to the [Project-OSRM contributors](https://github.com/Project-OSRM/osrm-backend/graphs/contributors) (BSD-2-Clause license).
OSM data belongs to [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL license).
This repo contains only deployment configuration, integration code, and benchmarks.
