"""
Dispatch Review Page

Focused view for dispatchers to review optimization decisions at a glance.
Shows only orders requiring decisions (non-KEEP) organized by store with
clear actions and justifications to reduce cognitive load.

Future-proofed for multi-store support via Chrome-style tabs.
"""

import streamlit as st
from datetime import datetime
from typing import List, Dict, Optional

st.set_page_config(page_title="Dispatch Review", layout="wide")


def get_action_badge_html(action: str) -> str:
    """
    Return HTML for a colored action badge.

    Args:
        action: Action string ('Deliver Early', 'Move to Later Window', 'Reschedule Today', 'Cancel')

    Returns:
        HTML string for styled badge
    """
    colors = {
        "Deliver Early": "#4A90E2",  # Blue
        "Move to Later Window": "#959595",  # Gray
        "Reschedule Today": "#F5A623",  # Orange
        "Cancel": "#D0021B",  # Red
    }

    color = colors.get(action, "#999")
    return f'<span style="background-color: {color}; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500;">{action}</span>'


def group_orders_by_store(orders_data: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group orders by fulfillment location (store).

    Args:
        orders_data: List of order dicts with decision info

    Returns:
        Dict mapping store name to list of orders
    """
    stores = {}
    for order in orders_data:
        store = order.get('fulfillmentLocation', 'Unknown Store')
        if store not in stores:
            stores[store] = []
        stores[store].append(order)

    # Sort stores alphabetically for consistent tab order
    return {k: stores[k] for k in sorted(stores.keys())}


def extract_decision_orders_multiwindow(allocation_result) -> List[Dict]:
    """
    Extract orders needing decisions from multi-window allocation results.

    Args:
        allocation_result: AllocationResult dataclass from allocator.py

    Returns:
        List of order dicts with decision info
    """
    decision_orders = []

    # Deliver Early (moved_early)
    for alloc in allocation_result.moved_early:
        decision_orders.append({
            **alloc.order,
            'action': 'Deliver Early',
            'justification': alloc.reason,
            'new_run': alloc.assigned_window,
            'allocation': alloc
        })

    # Move to Later Window (moved_later)
    for alloc in allocation_result.moved_later:
        decision_orders.append({
            **alloc.order,
            'action': 'Move to Later Window',
            'justification': alloc.reason,
            'new_run': alloc.assigned_window,
            'allocation': alloc
        })

    # Reschedule (reschedule)
    for alloc in allocation_result.reschedule:
        decision_orders.append({
            **alloc.order,
            'action': 'Reschedule Today',
            'justification': alloc.reason,
            'new_run': '–',
            'allocation': alloc
        })

    # Cancel (cancel)
    for alloc in allocation_result.cancel:
        decision_orders.append({
            **alloc.order,
            'action': 'Cancel',
            'justification': alloc.reason,
            'new_run': '–',
            'allocation': alloc
        })

    return decision_orders


def extract_decision_orders_onewindow(optimizations_dict) -> List[Dict]:
    """
    Extract orders needing decisions from one-window optimization results.

    Uses the 'max_orders' cut (recommended strategy).

    Args:
        optimizations_dict: Dict with 'max_orders' key from optimization_results

    Returns:
        List of order dicts with decision info
    """
    decision_orders = []
    max_orders = optimizations_dict.get('max_orders', {})

    # Map from optimizer disposition to action label
    disposition_to_action = {
        'early': 'Deliver Early',
        'reschedule': 'Reschedule Today',
        'cancel': 'Cancel'
    }

    for disposition, action_label in disposition_to_action.items():
        orders = max_orders.get(disposition, [])
        for order in orders:
            decision_orders.append({
                **order,
                'action': action_label,
                'justification': order.get('reason', ''),
                'new_run': '–',
                'allocation': None  # One-window doesn't use allocation objects
            })

    return decision_orders


def render_dispatch_review():
    """Main page render logic."""

    # Page header
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.title("Dispatch Review")

    with col2:
        # Date display
        today = datetime.now().strftime("%b %d, %Y")
        st.metric("Date", today, delta=None)

    with col3:
        # Summary counters
        st.metric("Pending", "–", delta=None)

    st.divider()

    # Check if optimization has been run
    full_day_results = st.session_state.get('full_day_results')
    optimization_results = st.session_state.get('optimization_results')

    if not full_day_results and not optimization_results:
        st.info(
            "📊 **No optimization results yet**\n\n"
            "Run an optimization in the main app to see decision review here."
        )
        return

    # Determine which mode was used and extract decision orders
    if full_day_results:
        # Multi-window mode
        allocation_result = full_day_results.get('allocation_result')
        if not allocation_result:
            st.error("Allocation result missing from session state")
            return

        decision_orders = extract_decision_orders_multiwindow(allocation_result)
        mode = "Multiple Windows"
    else:
        # One-window mode
        optimizations = optimization_results.get('optimizations', {})
        if not optimizations:
            st.error("Optimization results missing from session state")
            return

        decision_orders = extract_decision_orders_onewindow(optimizations)
        mode = "One Window"

    if not decision_orders:
        st.success(
            "✅ **All orders approved**\n\n"
            "No decisions needed — all orders are scheduled for delivery or have been reviewed."
        )
        return

    # Progress indicator
    st.markdown(f"**Progress:** 0 of {len(decision_orders)} reviewed")
    st.divider()

    # Group by store and create tabs
    orders_by_store = group_orders_by_store(decision_orders)

    if not orders_by_store:
        st.warning("No orders found")
        return

    # Create store tabs (Chrome-style)
    store_names = list(orders_by_store.keys())
    tabs = st.tabs([f"{store} ({len(orders_by_store[store])})" for store in store_names])

    # Render table for each store
    for tab, store_name in zip(tabs, store_names):
        with tab:
            orders = orders_by_store[store_name]

            # Prepare table data
            table_data = []
            for order in orders:
                table_data.append({
                    'Current Run': order.get('runId', '–'),
                    'Order ID': order.get('order_id', order.get('orderId', '–')),
                    'New Run': order.get('new_run', '–'),
                    'Action': order.get('action', ''),
                    'Justification': order.get('justification', ''),
                })

            if not table_data:
                st.info(f"No decisions needed for {store_name}")
                continue

            # Build table with columns
            col1, col2, col3, col4, col5, col6 = st.columns([0.5, 1.5, 1.5, 1.5, 2, 3])

            with col1:
                st.markdown("**☐**")
            with col2:
                st.markdown("**Current Run**")
            with col3:
                st.markdown("**Order ID**")
            with col4:
                st.markdown("**New Run**")
            with col5:
                st.markdown("**Action**")
            with col6:
                st.markdown("**Justification**")

            st.divider()

            # Data rows
            for i, row in enumerate(table_data):
                col1, col2, col3, col4, col5, col6 = st.columns([0.5, 1.5, 1.5, 1.5, 2, 3])

                with col1:
                    st.checkbox("", disabled=True, key=f"checkbox_{store_name}_{i}")
                with col2:
                    st.code(row['Current Run'], language=None)
                with col3:
                    st.code(row['Order ID'], language=None)
                with col4:
                    st.code(row['New Run'], language=None)
                with col5:
                    st.markdown(get_action_badge_html(row['Action']), unsafe_allow_html=True)
                with col6:
                    st.caption(row['Justification'])

            st.divider()
            st.caption("_Approve/reject decision flow coming in next iteration_")


# Main execution
try:
    render_dispatch_review()
except Exception as e:
    st.error(f"Error rendering page: {str(e)}")
    import traceback
    st.code(traceback.format_exc())
