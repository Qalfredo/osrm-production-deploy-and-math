# OSRM Production Deployment

> **This repo documents my production deployment of OSRM ([Project-OSRM/osrm-backend](https://github.com/Project-OSRM/osrm-backend)) for a ride-hailing use case. I did not build the routing engine. All credit for OSRM goes to its 180+ contributors, originally from the University of Karlsruhe. This project is licensed under BSD-2-Clause.**

Production deployment of OSRM for ride-hailing at scale — Python client, Docker Compose setup, OSM data pipeline, and benchmark results vs Google Maps Distance Matrix API.

---

## What OSRM's team built vs. what this repo covers

| OSRM (Project-OSRM contributors) | This repo |
|---|---|
| C++ routing engine | Production deployment setup |
| Contraction Hierarchies algorithm | OSM data pipeline for Venezuela |
| MLD preprocessing pipeline | Python client wrapping the OSRM HTTP API |
| HTTP API (`/route`, `/table`, `/nearest`, ...) | Benchmark suite vs Google Maps Distance Matrix |
| Official Docker images (`ghcr.io/project-osrm/osrm-backend`) | Cost analysis and integration guide |

---

## Architecture

```
Geofabrik (.osm.pbf)
        │
        ▼
  osrm-extract          ← builds the road graph
        │
        ▼
  osrm-contract         ← builds Contraction Hierarchy (CH pipeline)
        │
        ▼
  osrm-routed           ← HTTP API on :5000
        │
        ▼
  Python client         ← distance_matrix(), route(), nearest()
        │
        ▼
  Application layer
```

All preprocessing runs via the official `ghcr.io/project-osrm/osrm-backend` Docker image.

---

## Cost comparison

| Metric | Google Maps API | OSRM (self-hosted) |
|---|---|---|
| Cost per 1K elements | $5.00 | ~$0.03 (infra only) |
| Rate limits | Yes | None |
| Data ownership | No | Yes |
| Live traffic | Yes | No (static OSM) |
| Setup complexity | Zero | Medium |

---

## Repository structure

```
.
├── docker/
│   └── docker-compose.yml          # Official OSRM image + volume setup
├── data/
│   └── download_and_preprocess.sh  # OSM download + osrm-extract/contract
├── client/
│   └── osrm_client.py              # Python wrappers: distance_matrix(), route(), nearest()
├── notebooks/
│   ├── 01_local_deploy_walkthrough.md   # Step-by-step local deploy guide
│   ├── 02_osrm_math_graphs.ipynb        # Dijkstra + Contraction Hierarchies walkthrough
│   ├── 03_distance_comparison.ipynb     # OSRM vs Google Maps — cost and accuracy
│   └── 04_aws_deploy_walkthrough.md     # Minimal EC2 deploy via AWS CLI
└── docs/
    └── architecture.md             # Deployment architecture and design decisions
```

---

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/qalfredo/osrm-production-deployment
cd osrm-production-deployment
cp .env.example .env
# Edit .env and add your GOOGLE_MAPS_API_KEY
```

### 2. Download OSM data and preprocess

```bash
chmod +x data/download_and_preprocess.sh
./data/download_and_preprocess.sh
```

This downloads the Venezuela `.osm.pbf` from Geofabrik and runs `osrm-extract` + `osrm-contract`. Expect ~20–60 minutes for the contraction step.

### 3. Start OSRM

```bash
docker-compose -f docker/docker-compose.yml up -d
```

OSRM is now serving on `http://localhost:5001`.

### 4. Test with Python

```python
from client.osrm_client import OSRMClient

client = OSRMClient("http://localhost:5001")

# Distance matrix for 3 Venezuelan cities: Caracas, Valencia, Maracay
locations = [
    (10.4806, -66.9036),  # Caracas
    (10.1620, -67.9936),  # Valencia
    (10.2469, -67.5958),  # Maracay
]

distances, durations = client.distance_matrix(locations)
print(distances)   # meters
print(durations)   # seconds
```

---

## Algorithm choice: CH vs MLD

OSRM ships two preprocessing pipelines:

- **Contraction Hierarchies (CH)** — faster at query time for point-to-point and distance matrix queries. The [official OSRM documentation](https://github.com/Project-OSRM/osrm-backend#quick-start) recommends CH for distance matrix use cases.
- **Multi-Level Dijkstra (MLD)** — more flexible, supports live traffic updates, recommended for routing with turn-by-turn.

This repo uses **CH** (`osrm-contract`) because the primary use case is distance matrix computation at scale.

---

## Limitations

- **OSM data currency**: Venezuela OSM data from Geofabrik is updated regularly but may lag real-world road changes. Schedule periodic re-extraction.
- **No live traffic**: OSRM uses static road speeds from OSM. Travel times are estimates, not real-time.
- **Memory requirements**: The Venezuela `.osm.pbf` is ~200MB but the extracted CH graph requires significantly more RAM. A `t3.medium` (4GB) is the minimum viable instance.
- **OSM quality**: OSM coverage is good in major Venezuelan cities but sparse in rural areas.

---

## Notebooks

| # | File | Description |
|---|---|---|
| 01 | `01_local_deploy_walkthrough.md` | Full local deploy guide: Docker, data pipeline, testing |
| 02 | `02_osrm_math_graphs.ipynb` | Graph theory, Dijkstra, and Contraction Hierarchies visualized with NetworkX |
| 03 | `03_distance_comparison.ipynb` | OSRM vs Google Maps Distance Matrix — accuracy and cost side by side |
| 04 | `04_aws_deploy_walkthrough.md` | Minimal single-instance EC2 deploy using AWS CLI |

---

## Credits

- **[Project-OSRM](https://github.com/Project-OSRM/osrm-backend)** — the routing engine (BSD-2-Clause license)
- **[OpenStreetMap contributors](https://www.openstreetmap.org/copyright)** — the map data (ODbL license)
- **[Geofabrik](https://download.geofabrik.de/)** — OSM regional extracts
- **Geisberger et al. (2008)** — *Contraction Hierarchies: Faster and Simpler Hierarchical Routing in Road Networks* — the algorithm OSRM is built on
