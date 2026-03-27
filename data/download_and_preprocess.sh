#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Download Venezuela OSM data from Geofabrik and preprocess with OSRM.
# Uses the Contraction Hierarchies (CH) pipeline — recommended for distance
# matrix use cases per the official OSRM documentation.
#
# Prerequisites: Docker must be running.
# Expected runtime: 20–60 minutes (mostly the osrm-contract step).
# Expected disk usage: ~2 GB for the extracted + contracted graph.
# ------------------------------------------------------------------------------

set -euo pipefail

DATA_DIR="$(cd "$(dirname "$0")" && pwd)"
OSRM_IMAGE="ghcr.io/project-osrm/osrm-backend:latest"
PBF_FILE="venezuela-latest.osm.pbf"
GEOFABRIK_URL="https://download.geofabrik.de/south-america/venezuela-latest.osm.pbf"

echo "==> OSRM data pipeline — Venezuela (CH)"
echo "    Data directory : $DATA_DIR"
echo "    OSRM image     : $OSRM_IMAGE"
echo ""

# --- Step 1: Download ---
if [ -f "$DATA_DIR/$PBF_FILE" ]; then
  echo "[1/3] $PBF_FILE already exists — skipping download."
  echo "      Delete the file and re-run to force a fresh download."
else
  echo "[1/3] Downloading Venezuela OSM extract from Geofabrik..."
  curl -L --progress-bar -o "$DATA_DIR/$PBF_FILE" "$GEOFABRIK_URL"
  echo "      Download complete: $(du -sh "$DATA_DIR/$PBF_FILE" | cut -f1)"
fi

# --- Step 2: Extract ---
if [ -f "$DATA_DIR/venezuela-latest.osrm" ]; then
  echo "[2/3] Extracted graph already exists — skipping osrm-extract."
else
  echo "[2/3] Running osrm-extract (car profile)..."
  echo "      This builds the road graph from the .pbf file."
  docker run --rm \
    -v "$DATA_DIR:/data" \
    "$OSRM_IMAGE" \
    osrm-extract -p /opt/car.lua /data/$PBF_FILE
  echo "      osrm-extract complete."
fi

# --- Step 3: Contract ---
if [ -f "$DATA_DIR/venezuela-latest.osrm.hsgr" ]; then
  echo "[3/3] Contracted graph already exists — skipping osrm-contract."
else
  echo "[3/3] Running osrm-contract (Contraction Hierarchies)..."
  echo "      This is the slow step — expect 20–60 minutes for Venezuela."
  echo "      The resulting .hsgr file encodes the node hierarchy."
  START_TIME=$(date +%s)
  docker run --rm \
    -v "$DATA_DIR:/data" \
    "$OSRM_IMAGE" \
    osrm-contract /data/venezuela-latest.osrm
  END_TIME=$(date +%s)
  ELAPSED=$(( END_TIME - START_TIME ))
  echo "      osrm-contract complete in ${ELAPSED}s (~$(( ELAPSED / 60 )) min)."
fi

echo ""
echo "==> Preprocessing complete."
echo "    Start OSRM with:"
echo "    docker-compose -f docker/docker-compose.yml up -d"
echo ""
echo "    Test with:"
echo "    curl 'http://localhost:5001/nearest/v1/driving/-66.9036,10.4806'"
