"""
Route optimization using OR-Tools CVRPTW solver.
Implements Capacitated Vehicle Routing Problem with Time Windows.
"""

from typing import List, Dict, Tuple
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp


def service_time_for_units(units: int) -> int:
    """
    Calculate estimated service time (unloading time) at a stop based on number of units.

    Uses power function (units^1.3) for faster increase as size grows:
    - Minimum: 2 minutes (small orders)
    - Maximum: 7 minutes (cap for very large orders)
    - Formula: min(7, 1.6 + (units^1.3) * 0.045), rounded to nearest minute

    Examples:
        - 2 units  → 1.7 → 2 minutes
        - 5 units  → 2.0 → 2 minutes
        - 10 units → 2.5 → 3 minutes
        - 18 units → 3.7 → 4 minutes (typical range starts)
        - 20 units → 4.0 → 4 minutes (typical mid-range)
        - 25 units → 4.7 → 5 minutes (typical range)
        - 30 units → 5.4 → 5 minutes
        - 40 units → 7.2 → 7 minutes (reaches cap)

    This reflects operational reality where:
    - Small orders (2-10 units): 2-3 minutes
    - Typical orders (18-25 units): 3-5 minutes
    - Large orders (30-40 units): 5-7 minutes
    - Power curve means larger orders take disproportionately more time

    Args:
        units: Number of units to deliver

    Returns:
        Estimated service time in minutes (integer)
    """
    raw = 1.6 + (units ** 1.3) * 0.045
    return int(round(min(7, raw)))


def solve_route(
    time_matrix: List[List[int]],
    demands: List[int],
    vehicle_capacity: int,
    max_route_time: int,
    service_times: List[int],
    drop_penalty: int = 100000
) -> Tuple[List[Dict], List[int]]:
    """
    Solve single-vehicle CVRPTW to find optimal route respecting capacity and time constraints.

    Args:
        time_matrix: N x N matrix of travel times in minutes (index 0 is depot)
        demands: List of demands (units) for each node (index 0 is depot with 0 demand)
        vehicle_capacity: Maximum capacity of vehicle in units
        max_route_time: Maximum route duration in minutes (delivery window length)
        service_times: List of service times (unloading time) in minutes for each node
                      (index 0 is depot with 0 service time)
        drop_penalty: Penalty for dropping an order (default 100,000)
                     Higher penalty = prioritize order count
                     Lower penalty = prioritize short routes

    Returns:
        Tuple of (kept_orders, dropped_nodes) where:
        - kept_orders: List of dicts with:
            - node: int (node index in time_matrix)
            - sequence_index: int (position in route, 0-based)
            - arrival_min: int (arrival time in minutes from depot departure)
        - dropped_nodes: List of node indexes that were not served

    Notes:
        - Uses OR-Tools with guided local search metaheuristic
        - Allows dropping nodes with configurable penalty
        - Time limit: 5 seconds
        - Time dimension includes both drive time AND per-stop service time
          (service time increases with order size, bounded 2-7 minutes)
    """
    # Store problem data for callbacks
    data = {
        "time_matrix": time_matrix,
        "demands": demands,
        "vehicle_capacity": vehicle_capacity,
        "max_route_time": max_route_time,
        "service_times": service_times
    }

    # Create routing index manager
    # Number of nodes, number of vehicles (1), depot index (0)
    manager = pywrapcp.RoutingIndexManager(
        len(time_matrix),  # Number of nodes
        1,                  # Number of vehicles
        0                   # Depot index
    )

    # Create routing model
    routing = pywrapcp.RoutingModel(manager)

    # Create time callback
    # Time = drive time from->to + service time at FROM node
    # Service time represents unloading time, non-linear with units (2-5 min)
    def time_callback(from_index, to_index):
        """Return total time: drive time + service time at FROM node."""
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        drive_time = data["time_matrix"][from_node][to_node]
        service_time = data["service_times"][from_node]
        return drive_time + service_time

    transit_callback_index = routing.RegisterTransitCallback(time_callback)

    # Set arc cost evaluator (use time as cost)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Add Time dimension
    routing.AddDimension(
        transit_callback_index,
        30,               # Slack: allow 30 minutes of waiting time
        max_route_time,   # Maximum route time
        False,            # Don't force start cumul to zero
        'Time'
    )
    time_dimension = routing.GetDimensionOrDie('Time')

    # Add Capacity dimension
    def demand_callback(from_index):
        """Return demand (units) at node."""
        from_node = manager.IndexToNode(from_index)
        return data["demands"][from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)

    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,                 # No slack for capacity
        [vehicle_capacity],  # Vehicle capacity (list for each vehicle)
        True,              # Start cumul at zero
        'Capacity'
    )

    # Allow dropping nodes with penalty
    # Disjunction penalty determines order vs travel time trade-off
    # HIGH PENALTY (100,000+) = Maximize order count (paid per order)
    #   - Solver will keep maximum orders that fit constraints
    #   - Travel time becomes secondary (tiebreaker only)
    # LOW PENALTY (500-1,000) = Minimize travel time (paid per mile)
    #   - Solver drops orders to reduce driving
    #   - Only keeps orders very close to route
    # MEDIUM PENALTY (50,000) = Balanced approach
    #   - Fits many orders but considers travel efficiency
    #
    # Penalty should be >> max possible travel time to prioritize order count
    penalty = drop_penalty
    for node in range(1, len(time_matrix)):  # Skip depot (node 0)
        routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

    # Set search parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = 5

    # Solve
    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        # No solution found - return empty route and all nodes as dropped
        dropped_nodes = list(range(1, len(time_matrix)))
        return [], dropped_nodes

    # Extract solution
    kept_orders = []
    dropped_nodes = []

    # Track which nodes were visited
    visited_nodes = set()

    # Extract route for vehicle 0
    index = routing.Start(0)
    sequence_index = 0

    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)

        if node != 0:  # Skip depot in kept_orders
            time_var = time_dimension.CumulVar(index)
            arrival_min = solution.Value(time_var)

            kept_orders.append({
                "node": node,
                "sequence_index": sequence_index,
                "arrival_min": arrival_min
            })
            visited_nodes.add(node)
            sequence_index += 1

        index = solution.Value(routing.NextVar(index))

    # Identify dropped nodes
    for node in range(1, len(time_matrix)):
        if node not in visited_nodes:
            dropped_nodes.append(node)

    return kept_orders, dropped_nodes


def solve_route_two_van(
    time_matrix: List[List[int]],
    demands: List[int],
    vehicle_capacity: int,
    max_route_time: int,
    service_times: List[int],
    drop_penalty: int = 100000
) -> Tuple[List[Dict], List[Dict], List[int]]:
    """
    Solve two-vehicle closed-route CVRPTW (both start and end at depot).
    Same capacity and time window for both vehicles.

    Args:
        time_matrix: N x N matrix of travel times in minutes (index 0 is depot)
        demands: List of demands (units) for each node (index 0 is depot with 0 demand)
        vehicle_capacity: Maximum capacity of each vehicle in units (both vans identical)
        max_route_time: Maximum route duration in minutes for each vehicle
        service_times: List of service times in minutes for each node (index 0 is depot)
        drop_penalty: Penalty for dropping an order (default 100,000)

    Returns:
        Tuple of (van1_kept_orders, van2_kept_orders, dropped_nodes) where:
        - van1_kept_orders: List of dicts for vehicle 0 (node, sequence_index, arrival_min)
        - van2_kept_orders: List of dicts for vehicle 1 (node, sequence_index, arrival_min)
        - dropped_nodes: List of node indexes not served by either vehicle
    """
    data = {
        "time_matrix": time_matrix,
        "demands": demands,
        "vehicle_capacity": vehicle_capacity,
        "max_route_time": max_route_time,
        "service_times": service_times
    }

    # 2 vehicles, shared depot at node 0
    manager = pywrapcp.RoutingIndexManager(
        len(time_matrix),
        2,
        0
    )

    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        drive_time = data["time_matrix"][from_node][to_node]
        service_time = data["service_times"][from_node]
        return drive_time + service_time

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    routing.AddDimension(
        transit_callback_index,
        30,
        max_route_time,
        False,
        'Time'
    )
    time_dimension = routing.GetDimensionOrDie('Time')

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return data["demands"][from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)

    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,
        [vehicle_capacity, vehicle_capacity],  # Both vans same capacity
        True,
        'Capacity'
    )

    # Allow dropping nodes with penalty
    penalty = drop_penalty
    for node in range(1, len(time_matrix)):
        routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = 5

    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        return [], [], list(range(1, len(time_matrix)))

    van1_kept = []
    van2_kept = []

    for vehicle_id in range(2):
        kept_orders = []
        index = routing.Start(vehicle_id)
        sequence_index = 0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:  # Skip depot
                time_var = time_dimension.CumulVar(index)
                arrival_min = solution.Value(time_var)
                kept_orders.append({
                    "node": node,
                    "sequence_index": sequence_index,
                    "arrival_min": arrival_min
                })
                sequence_index += 1
            index = solution.Value(routing.NextVar(index))

        if vehicle_id == 0:
            van1_kept = kept_orders
        else:
            van2_kept = kept_orders

    visited_nodes = set(o["node"] for o in van1_kept + van2_kept)
    dropped_nodes = [node for node in range(1, len(time_matrix)) if node not in visited_nodes]

    return van1_kept, van2_kept, dropped_nodes
