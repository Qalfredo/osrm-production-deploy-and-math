# OSRM Local Deployment Walkthrough

This guide walks through deploying [OSRM (Project-OSRM/osrm-backend)](https://github.com/Project-OSRM/osrm-backend) locally using Docker and OpenStreetMap data for Venezuela. The **Contraction Hierarchies (CH)** pipeline is used throughout — the OSRM team recommends it for distance matrix workloads.

> **Attribution**: OSRM is an open-source routing engine built in C++ by 180+ contributors. This guide documents how to deploy it, not how it was built.

---

## Prerequisites

| Requirement | Minimum version | Notes |
|---|---|---|
| Docker | 20.10+ | Must be running |
| Docker Compose | v2.x | Bundled with Docker Desktop |
| Disk space | 4 GB free | For .pbf + extracted graph |
| RAM | 4 GB free | For osrm-routed at runtime |

Verify Docker is running:

```bash
docker info
```

---

## Step 1 — Download Venezuela OSM data

OpenStreetMap extracts are distributed free of charge by [Geofabrik](https://download.geofabrik.de/). The Venezuela extract is ~200 MB.

```bash
mkdir -p data
curl -L -o data/venezuela-latest.osm.pbf \
  https://download.geofabrik.de/south-america/venezuela-latest.osm.pbf
```

Check the file arrived:

```bash
ls -lh data/venezuela-latest.osm.pbf
# → something like: -rw-r--r-- 1 user staff 198M ...
```

---

## Step 2 — Extract the road graph (`osrm-extract`)

`osrm-extract` parses the `.pbf` file and builds OSRM's internal graph representation. The `car.lua` profile defines road speeds, turn penalties, and access rules for motor vehicles — it ships inside the Docker image.

```bash
docker run --rm \
  -v "$(pwd)/data:/data" \
  ghcr.io/project-osrm/osrm-backend:latest \
  osrm-extract -p /opt/car.lua /data/venezuela-latest.osm.pbf
```

**What this produces** (inside `data/`):

| File | Contents |
|---|---|
| `venezuela-latest.osrm` | Main graph file |
| `venezuela-latest.osrm.ebg` | Edge-based graph |
| `venezuela-latest.osrm.enw` | Edge node weights |
| `venezuela-latest.osrm.geometry` | Compressed geometry |
| `venezuela-latest.osrm.names` | Road names |
| `venezuela-latest.osrm.properties` | Routing properties |
| `venezuela-latest.osrm.restrictions` | Turn restrictions |

Expected runtime: **2–5 minutes** for Venezuela.

---

## Step 3 — Build the Contraction Hierarchy (`osrm-contract`)

This is the most important preprocessing step. `osrm-contract` assigns an importance rank to every node in the road graph, then contracts lower-ranked nodes — removing them and replacing their connections with shortcut edges that preserve all shortest paths.

The result is a hierarchical graph that enables bidirectional Dijkstra queries touching only ~hundreds of nodes instead of millions. See `02_osrm_math_graphs.ipynb` for a detailed walkthrough of the algorithm.

```bash
docker run --rm \
  -v "$(pwd)/data:/data" \
  ghcr.io/project-osrm/osrm-backend:latest \
  osrm-contract /data/venezuela-latest.osrm
```

**What this produces**:

| File | Contents |
|---|---|
| `venezuela-latest.osrm.hsgr` | Contracted graph (the hierarchy) |
| `venezuela-latest.osrm.core` | Core nodes (top of hierarchy) |

Expected runtime: **20–60 minutes** for Venezuela. This runs offline — it never affects query latency.

> **Why CH and not MLD?** OSRM offers two pipelines. CH (`osrm-contract`) produces faster queries for distance matrices. MLD (`osrm-partition` + `osrm-customize`) is more flexible and supports live traffic updates but is slower per query. For a distance matrix workload, CH is the right choice.

---

## Step 4 — Start the routing server (`osrm-routed`)

```bash
docker run --rm -d \
  --name osrm \
  -p 5000:5000 \
  -v "$(pwd)/data:/data" \
  ghcr.io/project-osrm/osrm-backend:latest \
  osrm-routed --algorithm ch /data/venezuela-latest.osrm
```

Or using Docker Compose (recommended — handles restarts):

```bash
docker-compose -f docker/docker-compose.yml up -d
```

Check it started:

```bash
docker logs osrm
# → [info] starting up engines, checksum: ...
# → [info] running and waiting for requests
```

---

## Step 5 — Test the API

OSRM exposes a REST API on port 5000. Test all three endpoints used by the Python client.

### Nearest (coordinate snapping)

```bash
# Snap Caracas Plaza Bolivar to the nearest road
curl "http://localhost:5000/nearest/v1/driving/-66.9036,10.4806"
```

Expected response:
```json
{
  "code": "Ok",
  "waypoints": [{
    "name": "Av. Urdaneta",
    "location": [-66.9035, 10.4807],
    "distance": 12.4
  }]
}
```

### Route (turn-by-turn)

```bash
# Caracas → Valencia
curl "http://localhost:5000/route/v1/driving/-66.9036,10.4806;-67.9936,10.1620?overview=simplified"
```

Expected response includes `distance` (metres) and `duration` (seconds).

### Distance matrix (`/table`)

```bash
# 3×3 matrix: Caracas, Valencia, Maracay
curl "http://localhost:5000/table/v1/driving/-66.9036,10.4806;-67.9936,10.1620;-67.5958,10.2469?annotations=duration,distance"
```

Expected response includes `durations` (seconds) and `distances` (metres) as nested arrays.

---

## Step 6 — Test with Python

```python
from client import OSRMClient

client = OSRMClient("http://localhost:5000")

locations = [
    (10.4806, -66.9036),  # Caracas
    (10.1620, -67.9936),  # Valencia
    (10.2469, -67.5958),  # Maracay
]

distances, durations = client.distance_matrix(locations)

print("Distances (km):")
print((distances / 1000).round(1))

print("\nDurations (min):")
print((durations / 60).round(1))
```

---

## Automated pipeline

The `data/download_and_preprocess.sh` script runs all three steps (download, extract, contract) in sequence with idempotency checks — it skips steps whose output already exists.

```bash
chmod +x data/download_and_preprocess.sh
./data/download_and_preprocess.sh
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker not running | `open /Applications/Docker.app` (macOS) or `sudo systemctl start docker` |
| Container exits immediately | Not enough RAM | Ensure ≥4 GB free; check `docker stats` |
| `osrm-routed` says `checksum mismatch` | Data files from different OSRM versions | Delete all `data/venezuela-latest.osrm*` and re-run from Step 2 |
| `/table` returns `null` distances | No route between points | Check OSM data covers the region; rare in cities, more common in rural areas |
| `curl: (7) Failed to connect` | Container not yet up | Wait 10 seconds after `docker-compose up` and retry |

---

## Updating OSM data

Geofabrik updates regional extracts daily. To refresh:

```bash
# Remove old data files
rm data/venezuela-latest.osm.pbf data/venezuela-latest.osrm*

# Re-run the full pipeline
./data/download_and_preprocess.sh

# Restart the server
docker-compose -f docker/docker-compose.yml restart
```

Schedule this monthly to keep road data reasonably current.
