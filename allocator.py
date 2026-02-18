"""
Cross-window order allocation for multi-window route optimization.

This module handles the business logic for allocating orders across multiple
delivery windows before per-window route optimization.
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Dict, Optional


@dataclass
class OrderAllocation:
    """Result of allocating a single order."""
    order: dict  # Order dict from parser
    original_window: str  # e.g. "09:00 AM - 11:00 AM"
    assigned_window: Optional[str]  # Window order was assigned to (None if reschedule/cancel)
    decision: str  # "KEEP_WINDOW", "MOVED_EARLY", "RESCHEDULE", "CANCEL_RECOMMENDED"
    reason: str  # Human-readable explanation


@dataclass
class AllocationResult:
    """Complete allocation results for all orders across all windows."""
    kept_in_window: List[OrderAllocation]  # Orders staying in original window
    moved_early: List[OrderAllocation]  # Orders moved to earlier window
    moved_later: List[OrderAllocation]  # Orders moved to a later window (overflow rescue)
    reschedule: List[OrderAllocation]  # Orders that should be rescheduled (no window fit)
    cancel: List[OrderAllocation]  # Orders recommended for cancellation
    orders_by_window: Dict[str, List[dict]]  # {window_label: [order dicts]}


def window_duration_minutes(start: time, end: time) -> int:
    """
    Calculate duration between two times in minutes.

    Args:
        start: Window start time
        end: Window end time

    Returns:
        Duration in minutes
    """
    today = datetime.today().date()
    dt_start = datetime.combine(today, start)
    dt_end = datetime.combine(today, end)
    return int((dt_end - dt_start).total_seconds() / 60)


def window_label(start: time, end: time) -> str:
    """
    Create a readable window label.

    Args:
        start: Window start time
        end: Window end time

    Returns:
        Formatted label like "09:00 AM - 11:00 AM"
    """
    return f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}"


def is_priority_customer(order: dict) -> bool:
    """
    Check if order is from a priority customer.

    Priority customers: 'power' and 'vip' (case-insensitive).
    These orders are locked to their original window.

    Args:
        order: Order dict with customerTag field

    Returns:
        True if priority customer
    """
    tag = str(order.get('customerTag', '')).lower().strip()
    return tag in ['power', 'vip']


def hours_between_windows(earlier_start: time, later_start: time) -> float:
    """
    Calculate hours between two window start times.

    Args:
        earlier_start: Start time of earlier window
        later_start: Start time of later window

    Returns:
        Hours difference (positive if earlier_start is actually earlier)
    """
    today = datetime.today().date()
    dt1 = datetime.combine(today, earlier_start)
    dt2 = datetime.combine(today, later_start)
    return (dt2 - dt1).total_seconds() / 3600


def allocate_orders_across_windows(
    orders: List[dict],
    windows: List[tuple],  # list of (window_start, window_end) sorted by start
    window_capacities: Dict[str, int],  # {window_label: capacity_units}
    honor_priority: bool = True,  # If False, skip Pass 1 (priority lock)
    cancel_threshold: int = 75,  # Orders over this size → auto-cancel
    reschedule_threshold: int = 40,  # Orders over this size → auto-reschedule
) -> AllocationResult:
    """
    Allocate orders across multiple delivery windows using business rules.

    Multi-pass allocation:
    PRE-PASS: Filter oversized orders (>cancel_threshold → CANCEL, >reschedule_threshold → RESCHEDULE)
    1. Lock priority customers to their original window (OPTIONAL - controlled by honor_priority)
    2. Move early-eligible orders to earlier windows (small orders first, push large orders to end of day)
    3. Assign remaining orders to original windows
    4. Mark overflow as reschedule/cancel based on reschedule_count

    Args:
        orders: List of order dicts from parser
        windows: List of (start_time, end_time) tuples sorted by start time
        window_capacities: Capacity in units for each window
        honor_priority: If True, lock priority customers to original window (Pass 1).
                       If False, skip Pass 1 for "truly max orders" optimization.
        cancel_threshold: Orders with units > this value are auto-cancelled if they don't fit
        reschedule_threshold: Orders with units > this value are auto-rescheduled if they don't fit

    Returns:
        AllocationResult with allocation decisions and orders grouped by window
    """
    # Initialize tracking structures
    window_labels = {window_label(start, end): (start, end) for start, end in windows}
    remaining_capacity = {label: cap for label, cap in window_capacities.items()}

    # Group orders by original window
    orders_by_original_window = {}
    for order in orders:
        orig_window = window_label(order['delivery_window_start'], order['delivery_window_end'])
        if orig_window not in orders_by_original_window:
            orders_by_original_window[orig_window] = []
        orders_by_original_window[orig_window].append(order)

    # Result containers
    kept_in_window = []
    moved_early = []
    reschedule = []
    cancel = []
    assigned_orders = {label: [] for label in window_labels.keys()}
    unassigned_orders = []

    # PRE-PASS: Filter out oversized orders BEFORE allocation
    orders_to_allocate = []

    for order in orders:
        orig_window = window_label(order['delivery_window_start'], order['delivery_window_end'])
        units = order['units']
        reschedule_count = order.get('priorRescheduleCount', 0) or 0

        if isinstance(reschedule_count, str):
            reschedule_count = int(reschedule_count) if reschedule_count.strip() else 0

        # Size-based pre-filtering
        if units > cancel_threshold:
            # Too large - pre-cancel
            allocation = OrderAllocation(
                order=order,
                original_window=orig_window,
                assigned_window=None,
                decision="CANCEL_RECOMMENDED",
                reason=f"Order size {units} units exceeds cancel threshold ({cancel_threshold}) — too large for any route"
            )
            cancel.append(allocation)
        elif units > reschedule_threshold:
            # Large - pre-reschedule
            allocation = OrderAllocation(
                order=order,
                original_window=orig_window,
                assigned_window=None,
                decision="RESCHEDULE",
                reason=f"Order size {units} units exceeds reschedule threshold ({reschedule_threshold}) — reschedule to different day"
            )
            reschedule.append(allocation)
        else:
            # Normal size - proceed with allocation
            orders_to_allocate.append(order)

    # Pass 1: Lock priority customers to their original window (OPTIONAL)
    remaining_orders = orders_to_allocate[:]  # Start with orders that passed size filter

    if honor_priority:
        # Lock priority customers to original window
        for order in orders_to_allocate[:]:  # Copy to allow modification
            if is_priority_customer(order):
                orig_window = window_label(order['delivery_window_start'], order['delivery_window_end'])
                units = order['units']

                # Deduct from capacity (even if it goes negative - priority customers are honored)
                remaining_capacity[orig_window] -= units
                assigned_orders[orig_window].append(order)

                allocation = OrderAllocation(
                    order=order,
                    original_window=orig_window,
                    assigned_window=orig_window,
                    decision="KEEP_WINDOW",
                    reason="Priority customer — honoring original window"
                )
                kept_in_window.append(allocation)

        # Remove priority orders from consideration for future passes
        remaining_orders = [o for o in orders_to_allocate if not is_priority_customer(o)]
    # else: keep all orders_to_allocate in remaining_orders for Pass 2

    # Pass 2: Try to move early-eligible orders to earlier windows
    # Sort by units ascending (move smallest orders first - easier to fit)
    early_eligible = [o for o in remaining_orders if o.get('early_delivery_ok', False)]
    early_eligible.sort(key=lambda o: o['units'])

    for order in early_eligible:
        orig_window = window_label(order['delivery_window_start'], order['delivery_window_end'])
        orig_start = order['delivery_window_start']
        units = order['units']

        # Find candidate windows: earlier + within 6 hours + has capacity
        candidates = []
        for label, (win_start, win_end) in window_labels.items():
            # Must start earlier
            if win_start >= orig_start:
                continue

            # Must be within 6 hours
            hours_diff = hours_between_windows(win_start, orig_start)
            if hours_diff > 6:
                continue

            # Must have capacity
            if remaining_capacity[label] >= units:
                candidates.append((label, win_start))

        if candidates:
            # Pick the earliest window with capacity
            candidates.sort(key=lambda x: x[1])
            new_window_label = candidates[0][0]

            # Assign to new window
            remaining_capacity[new_window_label] -= units
            assigned_orders[new_window_label].append(order)

            allocation = OrderAllocation(
                order=order,
                original_window=orig_window,
                assigned_window=new_window_label,
                decision="MOVED_EARLY",
                reason=f"Early delivery — moved from {orig_window} to {new_window_label} (capacity available)"
            )
            moved_early.append(allocation)
        else:
            # Could not move early - will be handled in Pass 3
            unassigned_orders.append(order)

    # Add non-early-eligible orders to unassigned pool
    non_early = [o for o in remaining_orders if not o.get('early_delivery_ok', False)]
    unassigned_orders.extend(non_early)

    # Pass 3: Assign remaining orders to their original windows if capacity allows
    for order in unassigned_orders[:]:  # Copy to allow modification
        orig_window = window_label(order['delivery_window_start'], order['delivery_window_end'])
        units = order['units']

        if remaining_capacity[orig_window] >= units:
            # Fits in original window
            remaining_capacity[orig_window] -= units
            assigned_orders[orig_window].append(order)
            unassigned_orders.remove(order)

            allocation = OrderAllocation(
                order=order,
                original_window=orig_window,
                assigned_window=orig_window,
                decision="KEEP_WINDOW",
                reason="Fits in original window"
            )
            kept_in_window.append(allocation)

    # Pass 4: Identify overflow orders and apply size-based hard filters
    # Sort by units descending (largest orders first)
    unassigned_orders.sort(key=lambda o: o['units'], reverse=True)

    # overflow_orders: normal-sized orders that didn't fit their original window → try later windows in Pass 5
    overflow_orders = []

    for order in unassigned_orders:
        orig_window = window_label(order['delivery_window_start'], order['delivery_window_end'])
        units = order['units']

        # SIZE-BASED THRESHOLDS: hard filter, never try later windows for these
        if units > cancel_threshold:
            allocation = OrderAllocation(
                order=order,
                original_window=orig_window,
                assigned_window=None,
                decision="CANCEL_RECOMMENDED",
                reason=f"Does not fit {orig_window} — {units} units exceeds cancel threshold ({cancel_threshold}) — too large to reschedule"
            )
            cancel.append(allocation)
        elif units > reschedule_threshold:
            allocation = OrderAllocation(
                order=order,
                original_window=orig_window,
                assigned_window=None,
                decision="RESCHEDULE",
                reason=f"Does not fit {orig_window} — {units} units exceeds reschedule threshold ({reschedule_threshold}) — reschedule to different day"
            )
            reschedule.append(allocation)
        else:
            # Normal-sized order that overflowed → try later windows in Pass 5
            overflow_orders.append(order)

    # Pass 5: Rescue overflow orders into later windows
    # For each overflow order, try every later window in chronological order.
    # Capacity check only — the per-window optimizer handles geographic fit.
    moved_later = []

    # Sort window_labels by start time so we iterate chronologically
    sorted_window_items = sorted(window_labels.items(), key=lambda x: x[1][0])

    for order in overflow_orders:
        orig_window = window_label(order['delivery_window_start'], order['delivery_window_end'])
        orig_start = order['delivery_window_start']
        units = order['units']
        reschedule_count = order.get('priorRescheduleCount', 0) or 0

        if isinstance(reschedule_count, str):
            reschedule_count = int(reschedule_count) if reschedule_count.strip() else 0

        rescued = False
        for label, (win_start, win_end) in sorted_window_items:
            # Only try windows that START AFTER the original window
            if win_start <= orig_start:
                continue

            # Check capacity
            if remaining_capacity.get(label, 0) >= units:
                remaining_capacity[label] -= units
                assigned_orders[label].append(order)

                allocation = OrderAllocation(
                    order=order,
                    original_window=orig_window,
                    assigned_window=label,
                    decision="MOVED_LATER_WINDOW",
                    reason=f"Overflow from {orig_window} — moved to {label} (capacity available; route fit confirmed after optimization)"
                )
                moved_later.append(allocation)
                rescued = True
                break

        if not rescued:
            # No later window had capacity — apply reschedule count logic
            if reschedule_count >= 2:
                allocation = OrderAllocation(
                    order=order,
                    original_window=orig_window,
                    assigned_window=None,
                    decision="CANCEL_RECOMMENDED",
                    reason=f"Does not fit any window today — already rescheduled {reschedule_count} times — recommend cancel"
                )
                cancel.append(allocation)
            else:
                allocation = OrderAllocation(
                    order=order,
                    original_window=orig_window,
                    assigned_window=None,
                    decision="RESCHEDULE",
                    reason=f"No available capacity in any later window today — reschedule to new day (reschedule count: {reschedule_count})"
                )
                reschedule.append(allocation)

    return AllocationResult(
        kept_in_window=kept_in_window,
        moved_early=moved_early,
        moved_later=moved_later,
        reschedule=reschedule,
        cancel=cancel,
        orders_by_window=assigned_orders
    )
