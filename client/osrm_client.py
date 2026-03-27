"""
OSRM HTTP API client.

Wraps the three endpoints used most in ride-hailing:
  - /table  → distance matrix (distances + durations for N×M location pairs)
  - /route  → turn-by-turn route between two points
  - /nearest → snap a coordinate to the nearest road segment

IMPORTANT — coordinate order:
  OSRM's HTTP API expects (longitude, latitude), which is the opposite of
  the common (latitude, longitude) convention. All public methods on this
  client accept (lat, lon) tuples and handle the flip internally.

Usage:
    from client import OSRMClient

    client = OSRMClient("http://localhost:5001")
    distances, durations = client.distance_matrix(
        origins=[(10.4806, -66.9036), (10.1620, -67.9936)],
        destinations=[(10.2469, -67.5958)],
    )
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import requests


class OSRMClient:
    """Thin wrapper around the OSRM v1 HTTP API."""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        """
        Parameters
        ----------
        base_url:
            OSRM server URL, e.g. "http://localhost:5001".
            Falls back to the OSRM_BASE_URL environment variable, then
            "http://localhost:5001".
        timeout:
            Request timeout in seconds.
        """
        self.base_url = (
            base_url
            or os.getenv("OSRM_BASE_URL", "http://localhost:5001")
        ).rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def distance_matrix(
        self,
        origins: list[tuple[float, float]],
        destinations: Optional[list[tuple[float, float]]] = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute an N×M distance and duration matrix via the /table endpoint.

        Parameters
        ----------
        origins:
            List of (lat, lon) tuples.
        destinations:
            List of (lat, lon) tuples. If None, uses origins as destinations
            (square N×N matrix).

        Returns
        -------
        distances : np.ndarray, shape (N, M), float
            Road distances in metres. np.nan where no route was found.
        durations : np.ndarray, shape (N, M), float
            Estimated travel times in seconds. np.nan where no route was found.
        """
        if destinations is None:
            destinations = origins

        all_coords = origins + destinations
        coords_str = self._fmt_coords(all_coords)

        sources = ";".join(str(i) for i in range(len(origins)))
        dests = ";".join(
            str(i) for i in range(len(origins), len(origins) + len(destinations))
        )

        url = f"{self.base_url}/table/v1/driving/{coords_str}"
        params = {
            "sources": sources,
            "destinations": dests,
            "annotations": "duration,distance",
        }

        data = self._get(url, params)

        durations = self._to_array(data.get("durations"))
        distances = self._to_array(data.get("distances"))

        return distances, durations

    def route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        steps: bool = False,
    ) -> dict:
        """
        Get the fastest route between two points.

        Parameters
        ----------
        origin:
            (lat, lon) of the start point.
        destination:
            (lat, lon) of the end point.
        steps:
            If True, include turn-by-turn step details.

        Returns
        -------
        dict with keys:
            distance_m   – road distance in metres
            duration_s   – estimated duration in seconds
            geometry     – encoded polyline (overview geometry)
            steps        – list of maneuver steps (only if steps=True)
        """
        coords_str = self._fmt_coords([origin, destination])
        url = f"{self.base_url}/route/v1/driving/{coords_str}"
        params = {
            "overview": "simplified",
            "steps": "true" if steps else "false",
        }

        data = self._get(url, params)
        route = data["routes"][0]

        result: dict = {
            "distance_m": route["distance"],
            "duration_s": route["duration"],
            "geometry": route.get("geometry"),
        }
        if steps:
            result["steps"] = route["legs"][0].get("steps", [])
        return result

    def nearest(
        self,
        location: tuple[float, float],
        number: int = 1,
    ) -> list[dict]:
        """
        Snap a coordinate to the nearest road segment(s).

        Parameters
        ----------
        location:
            (lat, lon) of the query point.
        number:
            Number of nearest segments to return.

        Returns
        -------
        List of waypoint dicts, each with:
            location  – [lon, lat] of the snapped point
            distance  – straight-line distance to the snapped point (metres)
            name      – road name (may be empty)
        """
        lat, lon = location
        url = f"{self.base_url}/nearest/v1/driving/{lon},{lat}"
        params = {"number": number}
        data = self._get(url, params)
        return data.get("waypoints", [])

    def health_check(self) -> bool:
        """Return True if the OSRM server is reachable."""
        try:
            # Use a known Venezuelan coordinate (Caracas) as a probe.
            self.nearest((10.4806, -66.9036))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_coords(coords: list[tuple[float, float]]) -> str:
        """Convert (lat, lon) list to OSRM's 'lon,lat;lon,lat' format."""
        return ";".join(f"{lon},{lat}" for lat, lon in coords)

    def _get(self, url: str, params: dict) -> dict:
        resp = requests.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in ("Ok", None):
            raise ValueError(f"OSRM error {data.get('code')}: {data.get('message')}")
        return data

    @staticmethod
    def _to_array(matrix: Optional[list]) -> np.ndarray:
        """Convert OSRM matrix (list of lists, None entries) to np.ndarray."""
        if matrix is None:
            return np.array([])
        arr = np.array(
            [[v if v is not None else np.nan for v in row] for row in matrix],
            dtype=float,
        )
        return arr
