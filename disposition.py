"""
Order disposition logic - classify orders into KEEP, EARLY_DELIVERY, RESCHEDULE, or CANCEL.
"""

from typing import List, Dict, Tuple
import math
from utils import (
    UNREACHABLE_TIME,
    EARLY_DELIVERY_THRESHOLD_MINUTES,
    RESCHEDULE_THRESHOLD_MINUTES,
    create_classified_order,
)


def calculate_order_score(
    order_category: str,
    avg_distance_to_cluster: float,
    units: int,
    depot_distance: float = None
) -> int:
    """
    Calculate an optimal order score (0-100) based on multiple factors.

    Higher scores = more optimal for delivery

    Score breakdown:
    - KEEP orders: 85-100 (on optimal route)
    - EARLY orders: 65-84 (close to route, timing issue)
    - RESCHEDULE orders: 35-64 (moderately close)
    - CANCEL orders: 0-34 (too far/isolated)

    Within each category, score is refined by:
    - Distance from cluster (closer = higher score)
    - Order size (larger = slightly higher score, more efficient)

    Args:
        order_category: KEEP, EARLY_DELIVERY, RESCHEDULE, or CANCEL
        avg_distance_to_cluster: Average travel time to cluster in minutes
        units: Number of units in the order
        depot_distance: Distance from depot (optional, for additional context)

    Returns:
        Score from 0-100
    """
    # Base score by category
    if order_category == "KEEP":
        base_score = 90
        # Refine by position efficiency (earlier in route = slightly higher)
        # Distance factor: closer to cluster = higher score
        distance_penalty = min(20, avg_distance_to_cluster * 0.5)
        score = base_score - distance_penalty

    elif order_category == "EARLY_DELIVERY":
        base_score = 75
        # Close to route but timing doesn't fit
        distance_penalty = min(15, avg_distance_to_cluster * 1.0)
        score = base_score - distance_penalty

    elif order_category == "RESCHEDULE":
        base_score = 50
        # Moderate distance, better fit elsewhere
        distance_penalty = min(20, (avg_distance_to_cluster - 10) * 1.5)
        score = base_score - distance_penalty

    else:  # CANCEL
        base_score = 20
        # Very far from cluster
        distance_penalty = min(20, (avg_distance_to_cluster - 20) * 0.5)
        score = base_score - distance_penalty

    # Small bonus for larger orders (more efficient delivery)
    size_bonus = min(5, math.log(units + 1))
    score += size_bonus

    # Clamp to 0-100
    return max(0, min(100, int(round(score))))


def classify_orders(
    all_orders: List[Dict],
    kept: List[Dict],
    dropped_nodes: List[int],
    time_matrix: List[List[int]]
) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict]]:
    """
    Classify all orders into four categories based on optimization results.

    Args:
        all_orders: All orders from CSV (order_id, customer_name, units, early_delivery_ok, etc.)
        kept: Orders kept in route from optimizer (node, sequence_index, arrival_min)
        dropped_nodes: Node indexes that were dropped by optimizer
        time_matrix: N x N travel time matrix (index 0 is depot)

    Returns:
        Tuple of (keep, early, reschedule, cancel) where each is a list of order dicts with:
        - order_id
        - customer_name
        - delivery_address
        - units
        - early_delivery_ok
        - category
        - reason
        - (estimated_arrival for KEEP orders)
        - (sequence_index for KEEP orders)

    Classification logic for dropped orders:
    - EARLY_DELIVERY: early_ok=True AND avg_distance_to_cluster < 10 min
    - RESCHEDULE: avg_distance_to_cluster < 20 min
    - CANCEL: avg_distance_to_cluster >= 20 min

    Note: The 10 and 20-minute thresholds are initial guesses.
          These should be tuned based on Buncha's operational data.
    """
    # Build set of kept node indexes
    kept_nodes = {k["node"] for k in kept}

    # Initialize result lists
    keep = []
    early = []
    reschedule = []
    cancel = []

    # Process KEEP orders
    for kept_order in kept:
        node = kept_order["node"]
        # Node indexes: 0 = depot, 1..N = orders
        # all_orders is 0-indexed, so order at node i is all_orders[i-1]
        order = all_orders[node - 1]

        # Calculate average distance to other kept orders (cluster cohesion)
        if len(kept_nodes) > 1:
            distances = [time_matrix[node][k] for k in kept_nodes if k != node]
            avg_distance = sum(distances) / len(distances) if distances else 0
        else:
            avg_distance = 0

        # Calculate depot distance
        depot_distance = time_matrix[0][node]

        # Calculate score
        score = calculate_order_score("KEEP", avg_distance, order["units"], depot_distance)

        keep.append(create_classified_order(
            order, "KEEP", "Included in optimized route", score,
            estimated_arrival=kept_order["arrival_min"],
            sequence_index=kept_order["sequence_index"],
            node=kept_order["node"],
        ))

    # Process DROPPED orders
    for node in dropped_nodes:
        order = all_orders[node - 1]

        # Calculate average distance to cluster (kept orders)
        if kept_nodes:
            distances = [time_matrix[node][k] for k in kept_nodes]
            avg_distance_to_cluster = sum(distances) / len(distances)
        else:
            # Degenerate case: no orders kept in route — treat as isolated
            avg_distance_to_cluster = UNREACHABLE_TIME

        # Classify based on thresholds
        # NOTE: These thresholds are initial guesses defined in utils.py.
        #       They should be tuned based on operational data and dispatcher feedback.

        # Calculate depot distance for scoring
        depot_distance = time_matrix[0][node]

        if order["early_delivery_ok"] and avg_distance_to_cluster < EARLY_DELIVERY_THRESHOLD_MINUTES:
            # EARLY_DELIVERY: Close to cluster and customer allows early delivery
            score = calculate_order_score("EARLY_DELIVERY", avg_distance_to_cluster, order["units"], depot_distance)
            early.append(create_classified_order(
                order, "EARLY_DELIVERY",
                f"Close to current cluster (<{EARLY_DELIVERY_THRESHOLD_MINUTES} min) and marked early_ok",
                score,
            ))
        elif avg_distance_to_cluster < RESCHEDULE_THRESHOLD_MINUTES:
            # RESCHEDULE: Moderately close, better fit in different window
            score = calculate_order_score("RESCHEDULE", avg_distance_to_cluster, order["units"], depot_distance)
            reschedule.append(create_classified_order(
                order, "RESCHEDULE",
                f"Moderately close (<{RESCHEDULE_THRESHOLD_MINUTES} min); better fit in a different window",
                score,
            ))
        else:
            # CANCEL: Geographically isolated
            score = calculate_order_score("CANCEL", avg_distance_to_cluster, order["units"], depot_distance)
            cancel.append(create_classified_order(
                order, "CANCEL",
                f"Geographically isolated (>={RESCHEDULE_THRESHOLD_MINUTES} min from cluster)",
                score,
            ))

    return keep, early, reschedule, cancel
