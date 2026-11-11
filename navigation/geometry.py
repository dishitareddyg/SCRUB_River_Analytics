"""
navigation/geometry.py

Pure polygon helpers used for mission validation.  Coordinates are
(latitude, longitude) degrees; small-area work is done on a local
equirectangular metre plane (same projection as the gps-compass
boustrophedon generator), which is accurate for lake-sized polygons.
"""

from __future__ import annotations

import math
from typing import Sequence, Tuple

LatLon = Tuple[float, float]
XY = Tuple[float, float]

_M_PER_DEG_LAT = 110_540.0
_M_PER_DEG_LON_EQ = 111_320.0


def to_local(points: Sequence[LatLon], origin: LatLon) -> list[XY]:
    m_lon = _M_PER_DEG_LON_EQ * math.cos(math.radians(origin[0]))
    return [((lon - origin[1]) * m_lon, (lat - origin[0]) * _M_PER_DEG_LAT) for lat, lon in points]


def strip_closing_vertex(points: Sequence[LatLon]) -> list[LatLon]:
    pts = list(points)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def signed_area_m2(poly_xy: Sequence[XY]) -> float:
    n = len(poly_xy)
    return 0.5 * sum(
        poly_xy[i][0] * poly_xy[(i + 1) % n][1] - poly_xy[(i + 1) % n][0] * poly_xy[i][1]
        for i in range(n)
    )


def _orient(a: XY, b: XY, c: XY) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: XY, b: XY, p: XY, eps: float = 1e-9) -> bool:
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
            and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps)


def segments_intersect(p1: XY, p2: XY, q1: XY, q2: XY, eps: float = 1e-9) -> bool:
    d1, d2 = _orient(q1, q2, p1), _orient(q1, q2, p2)
    d3, d4 = _orient(p1, p2, q1), _orient(p1, p2, q2)
    if ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)) and \
       ((d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps)):
        return True
    if abs(d1) <= eps and _on_segment(q1, q2, p1):
        return True
    if abs(d2) <= eps and _on_segment(q1, q2, p2):
        return True
    if abs(d3) <= eps and _on_segment(p1, p2, q1):
        return True
    if abs(d4) <= eps and _on_segment(p1, p2, q2):
        return True
    return False


def is_self_intersecting(poly_xy: Sequence[XY]) -> bool:
    n = len(poly_xy)
    for i in range(n):
        a1, a2 = poly_xy[i], poly_xy[(i + 1) % n]
        for j in range(i + 1, n):
            # skip adjacent edges (they share a vertex)
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            if segments_intersect(a1, a2, poly_xy[j], poly_xy[(j + 1) % n]):
                return True
    return False


def point_in_polygon(p: XY, poly_xy: Sequence[XY]) -> bool:
    """Ray casting; works for concave polygons."""
    x, y = p
    inside = False
    n = len(poly_xy)
    for i in range(n):
        x1, y1 = poly_xy[i]
        x2, y2 = poly_xy[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def distance_to_polygon_edge_m(p: XY, poly_xy: Sequence[XY]) -> float:
    best = float("inf")
    n = len(poly_xy)
    for i in range(n):
        ax, ay = poly_xy[i]
        bx, by = poly_xy[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / seg2))
        cx, cy = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(p[0] - cx, p[1] - cy))
    return best


def polygon_to_ewkt(points: Sequence[LatLon]) -> str:
    """PostGIS EWKT polygon (lon lat order, closed ring, SRID 4326)."""
    ring = strip_closing_vertex(points)
    ring.append(ring[0])
    coords = ", ".join(f"{lon:.8f} {lat:.8f}" for lat, lon in ring)
    return f"SRID=4326;POLYGON(({coords}))"


def point_to_ewkt(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon:.8f} {lat:.8f})"
