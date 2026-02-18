"""
Geocoding and distance matrix functionality using Google Maps API.
"""

from typing import List, Dict, Optional, Tuple
import googlemaps
from config import get_google_maps_client, is_test_mode
import polyline
import random
import math
from utils import (
    UNREACHABLE_TIME,
    EARTH_RADIUS_KM,
    MOCK_BASE_LAT,
    MOCK_BASE_LNG,
    DISTANCE_MATRIX_BATCH_SIZE,
)


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
    # Seed random with address hash for consistency
    results = []
    for i, address in enumerate(addresses):
        # Create deterministic but pseudo-random coordinates
        # Use address hash for consistent results per address
        seed = hash(address) % 10000
        random.seed(seed + i)

        # Spread addresses within ~20km radius (0.1 degrees ≈ 11km at this latitude)
        lat_offset = random.uniform(-0.1, 0.1)
        lng_offset = random.uniform(-0.1, 0.1)

        results.append({
            "address": address,
            "lat": MOCK_BASE_LAT + lat_offset,
            "lng": MOCK_BASE_LNG + lng_offset
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
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    # Haversine formula
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_KM * c


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


def build_time_matrix(addresses: List[str]) -> List[List[int]]:
    """
    Build a time matrix (in minutes) between all addresses using Distance Matrix API.

    In test mode, uses estimated distances based on straight-line calculations
    to avoid API costs.

    The matrix is N x N where N = len(addresses).
    Matrix[i][j] represents travel time in minutes from address i to address j.

    Args:
        addresses: List of addresses (first should be depot)

    Returns:
        N x N matrix of travel times in minutes.
        Unreachable routes are set to 9999.

    Note:
        Google Distance Matrix API has limits:
        - Max 10 origins per request
        - Max 10 destinations per request
        We batch requests accordingly.
    """
    # Use mock data in test mode
    if is_test_mode():
        return _mock_build_time_matrix(addresses)

    # Real API call
    client = get_google_maps_client()
    n = len(addresses)
    time_matrix = [[UNREACHABLE_TIME for _ in range(n)] for _ in range(n)]

    # Set diagonal to 0 (time from location to itself)
    for i in range(n):
        time_matrix[i][i] = 0

    # Process in batches matching the Google Distance Matrix API limit
    batch_size = DISTANCE_MATRIX_BATCH_SIZE

    # Process in batches
    for i_start in range(0, n, batch_size):
        i_end = min(i_start + batch_size, n)
        origins = addresses[i_start:i_end]

        for j_start in range(0, n, batch_size):
            j_end = min(j_start + batch_size, n)
            destinations = addresses[j_start:j_end]

            try:
                # Call Distance Matrix API
                result = client.distance_matrix(
                    origins=origins,
                    destinations=destinations,
                    mode="driving",
                    units="metric"
                )

                # Parse results
                if result["status"] == "OK":
                    for i_local, row in enumerate(result["rows"]):
                        i_global = i_start + i_local
                        for j_local, element in enumerate(row["elements"]):
                            j_global = j_start + j_local
                            if element["status"] == "OK":
                                # Duration in seconds, convert to minutes
                                duration_seconds = element["duration"]["value"]
                                duration_minutes = int(duration_seconds / 60)
                                time_matrix[i_global][j_global] = duration_minutes
                            # If status != OK, leave as 9999 (unreachable)

            except Exception as e:
                print(f"Error fetching distance matrix for batch ({i_start}:{i_end}, {j_start}:{j_end}): {e}")
                # Leave as 9999 for this batch

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
