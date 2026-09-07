"""Small bounded geometry helpers shared by PCB data extractors."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def as_xy(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    x, y = value.get("x"), value.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    if not math.isfinite(float(x)) or not math.isfinite(float(y)):
        return None
    return float(x), float(y)


def distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(second[0] - first[0], second[1] - first[1])


def bounding_box(points: Iterable[tuple[float, float]]) -> dict[str, float] | None:
    coordinates = list(points)
    if not coordinates:
        return None
    return {
        "minX": min(item[0] for item in coordinates),
        "minY": min(item[1] for item in coordinates),
        "maxX": max(item[0] for item in coordinates),
        "maxY": max(item[1] for item in coordinates),
    }


def polygon_area(points: Iterable[tuple[float, float]]) -> float:
    vertices = list(points)
    if len(vertices) < 3:
        return 0.0
    total = 0.0
    for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0
