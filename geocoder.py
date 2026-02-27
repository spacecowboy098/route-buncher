"""
Geocoding and distance matrix functionality using Google Maps API.
"""

from typing import List, Dict, Optional, Tuple
import googlemaps
from config import get_google_maps_client, is_test_mode
import polyline
import random
import math
import json
import os
from datetime import datetime


# ============================================================================
# DISTANCE CACHE CONSTANTS
# ============================================================================

CACHE_FILE = "distance_cache.json"
CACHE_EXPIRY_DAYS = 30
HAVERSINE_THRESHOLD_KM = 25.0  # Skip Distance Matrix API for pairs beyond this distance


# ============================================================================
# MOCK FUNCTIONS FOR TEST MODE (bypass Google Maps API)
# ============================================================================

def _mock_geocode_addresses(addresses: List[str]) -> List[Dict[str, any]]:
    """
    Generate mock geocoded addresses for testing without API calls.

    Creates random coordinates in a ~20km x 20km area centered around a base point.
    This simulates a realistic delivery area without calling the Geocoding API.

    Args:
        addresses: List of address strings

    Returns:
        List of dicts with mock lat/lng coordinates
    """
    # Base coordinates (Minneapolis/St. Paul area as example)
    base_lat = 44.9778
    base_lng = -93.2650

    # Seed random with address hash for consistency
    results = []
    for i, address in enumerate(addresses):
        # Create deterministic but pseudo-random coordinates
        # Use address hash for consistent results per address
        seed = hash(address) % 10000
        random.seed(seed + i)

        # Spread addresses within ~20km radius
        # 0.1 degrees ≈ 11km at this latitude
        lat_offset = random.uniform(-0.1, 0.1)
        lng_offset = random.uniform(-0.1, 0.1)

        results.append({
            "address": address,
            "lat": base_lat + lat_offset,
            "lng": base_lng + lng_offset
        })

    return results


def _calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate approximate distance in kilometers using Haversine formula.

    Args:
        lat1, lng1: First point coordinates
        lat2, lng2: Second point coordinates

    Returns:
        Distance in kilometers
    """
    # Earth radius in km
    R = 6371.0

    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    # Haversine formula
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def _mock_build_time_matrix(addresses: List[str]) -> List[List[int]]:
    """
    Build mock time matrix using straight-line distances for testing.

    Estimates drive time based on Euclidean distance with an average speed factor.
    This avoids calling the Distance Matrix API while still providing reasonable data.

    Args:
        addresses: List of addresses

    Returns:
        N x N matrix of estimated travel times in minutes
    """
    # First, mock geocode to get coordinates
    geocoded = _mock_geocode_addresses(addresses)

    n = len(addresses)
    time_matrix = [[0 for _ in range(n)] for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                time_matrix[i][j] = 0
            else:
                # Calculate straight-line distance
                lat1, lng1 = geocoded[i]["lat"], geocoded[i]["lng"]
                lat2, lng2 = geocoded[j]["lat"], geocoded[j]["lng"]

                distance_km = _calculate_distance(lat1, lng1, lat2, lng2)

                # Estimate time: assume 30 km/h average (accounts for city driving, turns, etc.)
                # This is conservative compared to highway speeds
                time_hours = distance_km / 30.0
                time_minutes = int(time_hours * 60)

                # Add small random variation (±20%) to make it more realistic
                seed = hash(f"{i}-{j}") % 1000
                random.seed(seed)
                variation = random.uniform(0.8, 1.2)
                time_minutes = int(time_minutes * variation)

                # Minimum 1 minute even for very close addresses
                time_matrix[i][j] = max(1, time_minutes)

    return time_matrix


def _mock_get_route_polylines(addresses: List[str], waypoint_order: List[int]) -> List[Tuple[float, float]]:
    """
    Generate mock route polylines by connecting points with straight lines.

    Instead of calling Directions API, this simply draws straight lines between
    waypoints for visualization purposes during testing.

    Args:
        addresses: List of addresses
        waypoint_order: Order to visit addresses

    Returns:
        List of (lat, lng) tuples forming straight-line route
    """
    if len(waypoint_order) < 2:
        return []

    # Mock geocode to get coordinates
    geocoded = _mock_geocode_addresses(addresses)

    route_coords = []

    # Connect each pair of consecutive waypoints with a straight line
    for i in range(len(waypoint_order) - 1):
        from_idx = waypoint_order[i]
        to_idx = waypoint_order[i + 1]

        from_lat = geocoded[from_idx]["lat"]
        from_lng = geocoded[from_idx]["lng"]
        to_lat = geocoded[to_idx]["lat"]
        to_lng = geocoded[to_idx]["lng"]

        # Add start point
        route_coords.append((from_lat, from_lng))

        # Add intermediate points for smoother line (5 points between each pair)
        for j in range(1, 5):
            interp_lat = from_lat + (to_lat - from_lat) * (j / 5.0)
            interp_lng = from_lng + (to_lng - from_lng) * (j / 5.0)
            route_coords.append((interp_lat, interp_lng))

    # Add final destination
    final_idx = waypoint_order[-1]
    route_coords.append((geocoded[final_idx]["lat"], geocoded[final_idx]["lng"]))

    return route_coords


# ============================================================================
# DB-COORDINATE HELPERS (bypass Google Maps API when lat/lng come from DB)
# ============================================================================

def build_geocoded_from_db_orders(
    depot_address: str,
    orders: List[Dict],
    depot_lat: Optional[float],
    depot_lng: Optional[float],
) -> Optional[List[Dict]]:
    """
    Build a geocoded list from pre-fetched DB coordinates (skips Geocoding API).

    Returns None if any coordinate is missing so the caller can fall back to
    the Google Maps Geocoding API.

    Args:
        depot_address: Depot address string (used as the 'address' label only)
        orders: List of order dicts, each expected to have 'delivery_address',
                'lat', and 'lng' fields populated from the DB.
        depot_lat: Depot latitude fetched from the store table.
        depot_lng: Depot longitude fetched from the store table.

    Returns:
        List of {"address", "lat", "lng"} dicts (index 0 = depot), or None if
        any coordinate is missing.
    """
    if depot_lat is None or depot_lng is None:
        return None

    geocoded = [{"address": depot_address, "lat": depot_lat, "lng": depot_lng}]
    for order in orders:
        lat = order.get("lat")
        lng = order.get("lng")
        if lat is None or lng is None:
            return None
        geocoded.append({"address": order["delivery_address"], "lat": lat, "lng": lng})

    return geocoded


def build_time_matrix_from_coords(geocoded: List[Dict]) -> List[List[int]]:
    """
    Build a time matrix using Haversine distances from pre-fetched coordinates.

    Uses the same speed estimate as mock mode (30 km/h average) but with real
    DB coordinates, completely avoiding the Distance Matrix API.

    Args:
        geocoded: List of {"address", "lat", "lng"} dicts (index 0 = depot).

    Returns:
        N x N matrix of estimated travel times in minutes. Diagonal is 0.
    """
    n = len(geocoded)
    time_matrix = [[0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            lat1 = geocoded[i].get("lat")
            lng1 = geocoded[i].get("lng")
            lat2 = geocoded[j].get("lat")
            lng2 = geocoded[j].get("lng")

            if any(v is None for v in [lat1, lng1, lat2, lng2]):
                time_matrix[i][j] = 9999
                continue

            dist_km = _calculate_distance(lat1, lng1, lat2, lng2)
            time_matrix[i][j] = max(1, int(dist_km / 30.0 * 60))

    return time_matrix


# ============================================================================
# CACHE HELPERS
# ============================================================================

def _load_cache() -> Dict:
    """Load the distance cache from disk. Returns empty dict on any error."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load distance cache: {e}")
    return {}


def _save_cache(cache: Dict) -> None:
    """Persist the distance cache to disk."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"Warning: Could not save distance cache: {e}")


def _cache_key(addr_a: str, addr_b: str) -> str:
    """Canonical cache key — sorted so A→B and B→A share the same entry."""
    return "|||".join(sorted([addr_a.strip(), addr_b.strip()]))


def _is_cache_valid(entry: Dict) -> bool:
    """Return True if cache entry is younger than CACHE_EXPIRY_DAYS."""
    try:
        cached_at = datetime.fromisoformat(entry["cached_at"])
        return (datetime.now() - cached_at).days < CACHE_EXPIRY_DAYS
    except Exception:
        return False


# ============================================================================
# MAIN API FUNCTIONS (with test mode support)
# ============================================================================

def geocode_addresses(addresses: List[str]) -> List[Dict[str, any]]:
    """
    Geocode a list of addresses using Google Maps Geocoding API.

    In test mode, uses mock geocoding to avoid API costs.

    Args:
        addresses: List of address strings to geocode

    Returns:
        List of dicts with keys: "address", "lat", "lng"
        Invalid addresses will have lat=None, lng=None

    Example:
        [
            {"address": "123 Main St", "lat": 42.123, "lng": -83.456},
            {"address": "Invalid", "lat": None, "lng": None}
        ]
    """
    # Use mock data in test mode
    if is_test_mode():
        return _mock_geocode_addresses(addresses)

    # Real API call
    client = get_google_maps_client()
    results = []

    for address in addresses:
        try:
            geocode_result = client.geocode(address)
            if geocode_result and len(geocode_result) > 0:
                location = geocode_result[0]["geometry"]["location"]
                results.append({
                    "address": address,
                    "lat": location["lat"],
                    "lng": location["lng"]
                })
            else:
                # Geocoding failed - no results
                results.append({
                    "address": address,
                    "lat": None,
                    "lng": None
                })
        except Exception as e:
            # Handle API errors gracefully
            print(f"Error geocoding address '{address}': {e}")
            results.append({
                "address": address,
                "lat": None,
                "lng": None
            })

    return results


def build_time_matrix(addresses: List[str], geocoded: Optional[List[Dict]] = None) -> List[List[int]]:
    """
    Build a time matrix (in minutes) between all addresses using Distance Matrix API.

    Three optimizations reduce API cost by ~65-80%:
    1. Symmetric matrix — only queries upper triangle (i < j) and mirrors results,
       cutting element count roughly in half.
    2. Haversine pre-filter — pairs beyond HAVERSINE_THRESHOLD_KM get a straight-line
       estimate instead of an API call; they won't appear on the same route anyway.
    3. Local disk cache — results are persisted to distance_cache.json and reused
       across runs for CACHE_EXPIRY_DAYS days.

    Args:
        addresses: List of addresses (first should be depot).
        geocoded: Optional pre-computed geocode results (avoids a redundant API call
                  when the caller already has coordinates).

    Returns:
        N x N matrix of travel times in minutes. Diagonal is 0.
    """
    if is_test_mode():
        return _mock_build_time_matrix(addresses)

    client = get_google_maps_client()
    n = len(addresses)

    # Diagonal = 0, everything else starts at 9999
    time_matrix = [[0 if i == j else 9999 for j in range(n)] for i in range(n)]

    # Geocode internally only if coordinates weren't passed in
    if geocoded is None:
        geocoded = geocode_addresses(addresses)

    cache = _load_cache()
    cache_updated = False

    # -------------------------------------------------------------------------
    # Pass 1: fill from cache or Haversine estimate (upper triangle only)
    # -------------------------------------------------------------------------
    api_pairs: List[Tuple[int, int]] = []  # pairs that still need an API call

    for i in range(n):
        for j in range(i + 1, n):
            key = _cache_key(addresses[i], addresses[j])

            # Cache hit
            if key in cache and _is_cache_valid(cache[key]):
                minutes = cache[key]["minutes"]
                time_matrix[i][j] = minutes
                time_matrix[j][i] = minutes
                continue

            # Haversine pre-filter
            lat_i = geocoded[i].get("lat") if i < len(geocoded) else None
            lng_i = geocoded[i].get("lng") if i < len(geocoded) else None
            lat_j = geocoded[j].get("lat") if j < len(geocoded) else None
            lng_j = geocoded[j].get("lng") if j < len(geocoded) else None

            if all(v is not None for v in [lat_i, lng_i, lat_j, lng_j]):
                dist_km = _calculate_distance(lat_i, lng_i, lat_j, lng_j)
                if dist_km >= HAVERSINE_THRESHOLD_KM:
                    estimated = max(1, int(dist_km / 30.0 * 60))
                    time_matrix[i][j] = estimated
                    time_matrix[j][i] = estimated
                    continue

            api_pairs.append((i, j))

    # -------------------------------------------------------------------------
    # Pass 2: batch API calls for remaining pairs
    # -------------------------------------------------------------------------
    if api_pairs:
        batch_size = 10

        # Group by origin index so we can build efficient batches
        origin_to_dests: Dict[int, List[int]] = {}
        for i, j in api_pairs:
            origin_to_dests.setdefault(i, []).append(j)

        origin_indices = sorted(origin_to_dests.keys())

        for o_start in range(0, len(origin_indices), batch_size):
            o_end = min(o_start + batch_size, len(origin_indices))
            batch_origins = origin_indices[o_start:o_end]

            # Union of all destinations needed for this origin batch
            all_dests = sorted({j for i in batch_origins for j in origin_to_dests[i]})

            for d_start in range(0, len(all_dests), batch_size):
                d_end = min(d_start + batch_size, len(all_dests))
                batch_dests = all_dests[d_start:d_end]

                origins = [addresses[i] for i in batch_origins]
                destinations = [addresses[j] for j in batch_dests]

                try:
                    result = client.distance_matrix(
                        origins=origins,
                        destinations=destinations,
                        mode="driving",
                        units="metric"
                    )

                    if result["status"] == "OK":
                        for i_local, row in enumerate(result["rows"]):
                            i_global = batch_origins[i_local]
                            for j_local, element in enumerate(row["elements"]):
                                j_global = batch_dests[j_local]

                                if i_global == j_global:
                                    continue

                                if element["status"] == "OK":
                                    duration_minutes = int(element["duration"]["value"] / 60)

                                    # Fill symmetrically
                                    time_matrix[i_global][j_global] = duration_minutes
                                    time_matrix[j_global][i_global] = duration_minutes

                                    # Cache under canonical key
                                    key = _cache_key(addresses[i_global], addresses[j_global])
                                    cache[key] = {
                                        "minutes": duration_minutes,
                                        "cached_at": datetime.now().isoformat()
                                    }
                                    cache_updated = True

                except Exception as e:
                    print(f"Error fetching distance matrix batch (origins {batch_origins}, dests {batch_dests}): {e}")

    if cache_updated:
        _save_cache(cache)

    return time_matrix


def get_route_polylines(addresses: List[str], waypoint_order: List[int]) -> List[Tuple[float, float]]:
    """
    Get actual driving route polylines showing roads between stops.

    In test mode, returns straight lines between waypoints to avoid API costs.

    Uses Google Directions API to get turn-by-turn directions and decode the polyline
    to show the actual roads the driver will take.

    Args:
        addresses: List of addresses (first should be depot)
        waypoint_order: List of indices representing the order to visit addresses
                       e.g., [0, 3, 1, 5, 0] = depot -> addr[3] -> addr[1] -> addr[5] -> depot

    Returns:
        List of (lat, lng) tuples representing the complete route path on actual roads

    Note:
        This makes one Directions API call for the entire route.
        The API can handle up to 25 waypoints per request.
    """
    # Use mock data in test mode
    if is_test_mode():
        return _mock_get_route_polylines(addresses, waypoint_order)

    # Real API call
    client = get_google_maps_client()

    if len(waypoint_order) < 2:
        return []

    # Build origin, destination, and waypoints
    origin = addresses[waypoint_order[0]]
    destination = addresses[waypoint_order[-1]]

    # Middle stops are waypoints (skip first and last)
    waypoints = []
    if len(waypoint_order) > 2:
        waypoints = [addresses[i] for i in waypoint_order[1:-1]]

    try:
        # Call Directions API
        directions = client.directions(
            origin=origin,
            destination=destination,
            waypoints=waypoints if waypoints else None,
            mode="driving",
            optimize_waypoints=False  # We already have the optimized order
        )

        if not directions:
            print("No directions found")
            return []

        # Extract and decode polylines from all legs
        route_coords = []
        for leg in directions[0]["legs"]:
            for step in leg["steps"]:
                # Decode the polyline for this step
                encoded_polyline = step["polyline"]["points"]
                decoded = polyline.decode(encoded_polyline)
                # decoded is list of (lat, lng) tuples
                route_coords.extend(decoded)

        return route_coords

    except Exception as e:
        print(f"Error fetching directions: {e}")
        return []


def get_multi_route_polylines(routes_data: Dict[str, Dict]) -> Dict[str, List[Tuple[float, float]]]:
    """
    Get actual driving route polylines for multiple routes simultaneously.

    Args:
        routes_data: Dict mapping route_id to route data
                    {
                        'route_1': {
                            'addresses': [...],
                            'waypoint_order': [0, 3, 1, 5, 0]
                        },
                        'route_2': {
                            'addresses': [...],
                            'waypoint_order': [0, 2, 4, 0]
                        }
                    }

    Returns:
        Dict mapping route_id to list of (lat, lng) tuples
        {
            'route_1': [(lat1, lng1), (lat2, lng2), ...],
            'route_2': [(lat1, lng1), (lat2, lng2), ...]
        }
    """
    result = {}

    for route_id, route_data in routes_data.items():
        addresses = route_data['addresses']
        waypoint_order = route_data['waypoint_order']

        # Get polylines for this route
        polylines = get_route_polylines(addresses, waypoint_order)
        result[route_id] = polylines

    return result
