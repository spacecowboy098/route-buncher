"""
Shared constants and helper utilities for the Route Buncher application.

Centralizes values and functions that are used across multiple modules to
eliminate duplication and provide a single source of truth.
"""

import math
from typing import Dict


# ============================================================================
# CONSTANTS
# ============================================================================

# Sentinel value for unreachable routes in time matrices
UNREACHABLE_TIME = 9999

# Earth radius for Haversine distance calculations
EARTH_RADIUS_KM = 6371.0

# Base coordinates for mock geocoding (Minneapolis/St. Paul area)
MOCK_BASE_LAT = 44.9778
MOCK_BASE_LNG = -93.2650

# Google Distance Matrix API batch limit
DISTANCE_MATRIX_BATCH_SIZE = 10

# Values treated as boolean True when parsing CSV fields
TRUTHY_VALUES = {"yes", "y", "true", "1"}

# Distance thresholds (minutes) for order disposition classification
EARLY_DELIVERY_THRESHOLD_MINUTES = 10   # Closer than this → eligible for early delivery
RESCHEDULE_THRESHOLD_MINUTES = 20       # Closer than this → reschedule; farther → cancel


# ============================================================================
# ORDER HELPERS
# ============================================================================

def parse_reschedule_count(order: dict) -> int:
    """
    Safely parse the priorRescheduleCount field from an order dict.

    Handles None, missing, and string representations.

    Args:
        order: Order dict (may contain priorRescheduleCount key)

    Returns:
        Integer reschedule count, defaulting to 0
    """
    count = order.get('priorRescheduleCount', 0) or 0
    if isinstance(count, str):
        count = int(count) if count.strip() else 0
    return count


def parse_boolean(value) -> bool:
    """
    Parse a value as boolean, handling None, empty strings, and common truthy strings.

    Args:
        value: Value to parse (string, None, or other)

    Returns:
        True if value is a truthy string, False otherwise
    """
    import pandas as pd
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in TRUTHY_VALUES


def create_classified_order(order: dict, category: str, reason: str, score: int, **extras) -> dict:
    """
    Create a classified order dict by copying all original fields and adding classification metadata.

    Args:
        order: Original order dict (all fields are preserved)
        category: Classification category (KEEP, EARLY_DELIVERY, RESCHEDULE, CANCEL)
        reason: Human-readable reason for classification
        score: Optimal score (0-100)
        **extras: Additional fields to include (e.g., estimated_arrival, sequence_index)

    Returns:
        New dict with all original fields plus classification metadata
    """
    result = dict(order)
    result.update({
        "category": category,
        "reason": reason,
        "optimal_score": score,
        **extras
    })
    return result


# ============================================================================
# MAP HELPERS
# ============================================================================

def create_numbered_marker_html(stop_number: int, color: str, size: int = 30) -> str:
    """
    Generate HTML for a circular numbered stop marker used in Folium maps.

    Args:
        stop_number: The stop sequence number to display
        color: CSS color value (hex, named, or rgb)
        size: Diameter in pixels (default 30)

    Returns:
        HTML string for use in folium.DivIcon
    """
    font_size = max(10, size - 16)
    return f"""<div style="
        background-color: {color};
        border: 2px solid white;
        border-radius: 50%;
        width: {size}px;
        height: {size}px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: {font_size}px;
        font-weight: bold;
        color: white;
        box-shadow: 0 2px 5px rgba(0,0,0,0.3);
    ">{stop_number}</div>"""
