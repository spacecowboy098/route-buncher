"""
Geocoding and distance matrix functionality using Google Maps API.
"""

from typing import List, Dict, Optional, Tuple
import googlemaps
from config import get_google_maps_client
import polyline


def geocode_addresses(addresses: List[str]) -> List[Dict[str, any]]:
    """
    Geocode a list of addresses using Google Maps Geocoding API.

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
    client = get_google_maps_client()
    n = len(addresses)
    time_matrix = [[9999 for _ in range(n)] for _ in range(n)]

    # Set diagonal to 0 (time from location to itself)
    for i in range(n):
        time_matrix[i][i] = 0

    # Batch size for API limits (10x10)
    batch_size = 10

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
