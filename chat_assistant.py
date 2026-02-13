"""
AI Chat Assistant for route optimization conversations.
Helps dispatchers understand decisions and make adjustments.
"""

import anthropic
from typing import List, Dict, Optional
import config


def create_context_for_ai(keep, early, reschedule, cancel, valid_orders, time_matrix, vehicle_capacity, window_minutes, depot_address):
    """
    Create a comprehensive context string for the AI assistant.
    """
    # Calculate current route metrics
    kept_units = sum(o['units'] for o in keep)
    remaining_capacity = vehicle_capacity - kept_units

    # Calculate total route time
    total_route_time = 0
    if keep:
        sorted_keep = sorted(keep, key=lambda x: x.get('sequence_index', 0))
        kept_nodes = [k['node'] for k in sorted_keep]
        total_route_time = time_matrix[0][kept_nodes[0]]  # Depot to first
        for i in range(len(kept_nodes) - 1):
            total_route_time += time_matrix[kept_nodes[i]][kept_nodes[i + 1]]
        total_route_time += time_matrix[kept_nodes[-1]][0]  # Last to depot

    remaining_time = window_minutes - total_route_time

    # Create comprehensive context
    context = f"""You are an AI assistant helping a Buncha dispatcher understand and optimize delivery routes.

OPTIMIZATION CONFIGURATION:
===========================
- Fulfillment Location: {depot_address}
- Vehicle Capacity: {vehicle_capacity} units (Currently using: {kept_units} units, Remaining: {remaining_capacity} units)
- Delivery Window: {window_minutes} minutes (Route time: {total_route_time} min, Remaining: {remaining_time} min)
- Total Orders Processed: {len(valid_orders)}

COMPLETE ORDER DETAILS:
======================

KEPT ORDERS ({len(keep)} orders, {kept_units} units):
"""

    # Add detailed info for kept orders
    for order in sorted(keep, key=lambda x: x.get('sequence_index', 0)):
        context += f"\n- Order #{order['order_id']}: {order['customer_name']}"
        context += f"\n  Address: {order['delivery_address']}"
        context += f"\n  Units: {order['units']}"
        context += f"\n  Sequence: Stop #{order.get('sequence_index', 0) + 1}"
        context += f"\n  Est. Arrival: {order.get('estimated_arrival', 0)} min from start"
        context += f"\n  Status: KEPT - On optimized route"

    context += f"\n\nEARLY DELIVERY CANDIDATES ({len(early)} orders):"
    for order in early:
        # Find full order details from valid_orders
        full_order = next((o for o in valid_orders if o['order_id'] == order['order_id']), None)
        context += f"\n- Order #{order['order_id']}: {order['customer_name']}"
        context += f"\n  Address: {order['delivery_address']}"
        context += f"\n  Units: {order['units']}"
        if full_order:
            context += f"\n  Early Delivery OK: {'Yes' if full_order.get('early_delivery_ok') else 'No'}"
        context += f"\n  Status: EARLY - {order['reason']}"

    context += f"\n\nRESCHEDULE CANDIDATES ({len(reschedule)} orders):"
    for order in reschedule:
        full_order = next((o for o in valid_orders if o['order_id'] == order['order_id']), None)
        context += f"\n- Order #{order['order_id']}: {order['customer_name']}"
        context += f"\n  Address: {order['delivery_address']}"
        context += f"\n  Units: {order['units']}"
        context += f"\n  Status: RESCHEDULE - {order['reason']}"

    context += f"\n\nCANCEL RECOMMENDATIONS ({len(cancel)} orders):"
    for order in cancel:
        full_order = next((o for o in valid_orders if o['order_id'] == order['order_id']), None)
        context += f"\n- Order #{order['order_id']}: {order['customer_name']}"
        context += f"\n  Address: {order['delivery_address']}"
        context += f"\n  Units: {order['units']}"
        context += f"\n  Status: CANCEL - {order['reason']}"

    context += f"""

ROUTE CONSTRAINTS & METRICS:
============================
- Current route uses {kept_units}/{vehicle_capacity} units ({(kept_units/vehicle_capacity*100):.1f}% capacity)
- Current route time: {total_route_time}/{window_minutes} minutes ({(total_route_time/window_minutes*100):.1f}% of window)
- Spare capacity: {remaining_capacity} units
- Spare time: {remaining_time} minutes

YOUR ROLE & CAPABILITIES:
========================
When a dispatcher asks questions, you should:

1. **"Why is order #X not included?"**
   - Look up order #X in the EARLY/RESCHEDULE/CANCEL lists above
   - Explain the specific reason listed
   - Reference capacity, time, or geographic constraints
   - Be specific about distances/times if mentioned in the reason

2. **"Can you add order #X back?"**
   - Locate order #X and its units
   - Check if spare capacity ({remaining_capacity} units) can accommodate it
   - Check if spare time ({remaining_time} min) is sufficient
   - If YES: Explain that adding it is feasible if it's geographically close to the route
   - If NO: Explain which constraint(s) prevent it (capacity or time)
   - Mention that adding an order far from the cluster will use more time than adding a nearby one
   - ALWAYS remind them they need to re-run optimization to actually add it

3. **"What would happen if I remove order #X?"**
   - Find order #X in the KEPT list
   - State how many units would be freed up
   - Estimate time savings (depends on where it is in sequence)
   - Mention this could allow adding other orders back

4. **General questions about decisions:**
   - Reference the actual metrics above (capacity %, time %, etc.)
   - Explain the optimization prioritizes: (1) Max orders delivered, (2) Minimize drive time
   - Use real order numbers and data from this context

IMPORTANT RULES:
- You CANNOT modify the route - only explain what would happen
- Always use specific order numbers when referring to orders
- Be concise but data-driven
- When asked about adding orders back, explain both feasibility AND geography
- Remind dispatchers they must re-run optimization to make actual changes
"""

    return context


def chat_with_assistant(messages: List[Dict[str, str]], context: str, api_key: str) -> str:
    """
    Send messages to Claude AI and get a response.

    Args:
        messages: List of message dicts with 'role' and 'content'
        context: System context about the optimization
        api_key: Anthropic API key

    Returns:
        str: Assistant's response
    """
    if not api_key or api_key == "YOUR_ANTHROPIC_API_KEY_HERE":
        return "⚠️ Chat assistant is not configured. Please add your ANTHROPIC_API_KEY to the .env file to enable AI chat."

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Filter messages - API requires alternating user/assistant, starting with user
        # Skip any leading assistant messages (like our route explanation)
        api_messages = []
        for msg in messages:
            if len(api_messages) == 0 and msg["role"] == "assistant":
                # Skip leading assistant messages
                continue
            api_messages.append(msg)

        # If no messages to send, return empty
        if not api_messages:
            return ""

        # Format system as list of content blocks for SDK 0.79.0
        # Explicitly ensure context is a string
        system_blocks = [
            {
                "type": "text",
                "text": str(context)
            }
        ]

        # Call Claude API - use Claude Sonnet 4.5 (current as of 2026)
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1500,
            system=system_blocks,
            messages=api_messages
        )

        return response.content[0].text

    except Exception as e:
        return f"❌ Error communicating with AI assistant: {str(e)}"


def validate_optimization_results(keep, early, reschedule, cancel, valid_orders, time_matrix,
                                   service_times, vehicle_capacity, window_minutes, api_key):
    """
    Use AI to validate optimization results and explain route logic.

    Returns:
        str: AI validation and explanation
    """
    if not api_key or api_key == "YOUR_ANTHROPIC_API_KEY_HERE":
        return None

    # Calculate actual totals for validation
    total_kept_units = sum(o["units"] for o in keep)

    # Calculate drive time and service time
    drive_time = 0
    if keep:
        sorted_keep = sorted(keep, key=lambda x: x.get('sequence_index', 0))
        kept_nodes = [k['node'] for k in sorted_keep]
        drive_time = time_matrix[0][kept_nodes[0]]
        for i in range(len(kept_nodes) - 1):
            drive_time += time_matrix[kept_nodes[i]][kept_nodes[i + 1]]
        drive_time += time_matrix[kept_nodes[-1]][0]

    total_service_time = 0
    if service_times:
        for order in keep:
            node = order["node"]
            if node < len(service_times):
                total_service_time += service_times[node]

    total_route_time = drive_time + total_service_time

    # Create validation prompt
    validation_prompt = f"""You are an expert logistics analyst reviewing an optimized delivery route.
Your job is to:
1. Validate the math and logic
2. Explain why this route makes the most sense
3. Flag any concerns or considerations

OPTIMIZATION RESULTS:
===================
Total Orders: {len(valid_orders)}
- KEPT: {len(keep)} orders ({total_kept_units} units)
- EARLY DELIVERY: {len(early)} orders
- RESCHEDULE: {len(reschedule)} orders
- CANCEL: {len(cancel)} orders

CONSTRAINTS:
- Vehicle Capacity: {vehicle_capacity} units
- Delivery Window: {window_minutes} minutes

ROUTE METRICS:
- Capacity Used: {total_kept_units}/{vehicle_capacity} units ({total_kept_units/vehicle_capacity*100:.1f}%)
- Drive Time: {drive_time} minutes
- Service Time: {total_service_time} minutes (unloading at {len(keep)} stops)
- Total Route Time: {total_route_time} minutes ({total_route_time/window_minutes*100:.1f}% of window)

KEPT ORDERS SEQUENCE:
"""

    for order in sorted(keep, key=lambda x: x.get('sequence_index', 0)):
        node = order["node"]
        service_time = service_times[node] if service_times and node < len(service_times) else 0
        validation_prompt += f"\n{order['sequence_index']+1}. Order #{order['order_id']}: {order['units']} units, {service_time} min service time"

    validation_prompt += f"""

DROPPED ORDERS:
- {len(early)} orders marked for early delivery (customer approved)
- {len(reschedule)} orders to reschedule (10-20 min from cluster)
- {len(cancel)} orders to cancel (>20 min from cluster)

YOUR TASK:
=========
1. **Validate Math**: Verify capacity ({total_kept_units} ≤ {vehicle_capacity}) and time ({total_route_time} ≤ {window_minutes})
2. **Check Logic**: Confirm dropped orders make sense given constraints
3. **Explain Route**: Why is THIS specific route optimal? What makes it better than alternatives?
4. **Flag Concerns**: Any edge cases, tight margins, or risks?

Provide a concise analysis (4-6 sentences) that helps the dispatcher understand and trust this route.
Focus on:
- Why we kept these {len(keep)} orders specifically
- Why we dropped the others
- Any tight constraints (capacity at {total_kept_units/vehicle_capacity*100:.0f}%, time at {total_route_time/window_minutes*100:.0f}%)
- Overall confidence in this route
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)

        system_message = [{"type": "text", "text": "You are an expert logistics analyst validating delivery route optimizations."}]

        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=800,
            system=system_message,
            messages=[{"role": "user", "content": validation_prompt}]
        )

        return response.content[0].text

    except Exception as e:
        return f"⚠️ Could not validate results: {str(e)}"


def get_suggested_questions() -> List[str]:
    """Return a list of suggested questions dispatchers might ask."""
    return [
        "Why was order #70592 kept in the route?",
        "Can you add back order #70610?",
        "What would happen if I remove order #70509?",
        "Why are some orders recommended for cancellation?",
        "How can I fit more orders in this route?",
        "Which rescheduled orders are closest to the current route?",
    ]


def generate_order_explanations(keep, early, reschedule, cancel, time_matrix, depot_address, api_key):
    """
    Use AI to generate specific, detailed explanations for each order's disposition.

    Args:
        keep: List of orders kept in route
        early: List of orders for early delivery
        reschedule: List of orders to reschedule
        cancel: List of orders to cancel
        time_matrix: Travel time matrix
        depot_address: Depot location
        api_key: Anthropic API key

    Returns:
        Dict mapping order_id to AI-generated explanation
    """
    if not api_key or api_key == "YOUR_ANTHROPIC_API_KEY_HERE":
        # Return None if AI not configured - will use default reasons
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Build comprehensive prompt with all order details
        prompt = f"""You are a logistics expert explaining route optimization decisions to a dispatcher.

CONTEXT:
- Fulfillment Location: {depot_address}
- Total orders processed: {len(keep) + len(early) + len(reschedule) + len(cancel)}
- Orders kept in route: {len(keep)}
- Orders for alternate handling: {len(early) + len(reschedule) + len(cancel)}

ORDERS KEPT IN ROUTE:
"""

        for order in keep:
            node = order['node']
            depot_dist = time_matrix[0][node]
            prompt += f"\n- Order #{order['order_id']}: {order['customer_name']}, {order['units']} units"
            prompt += f"\n  Stop #{order['sequence_index']+1}, {depot_dist} min from depot"
            prompt += f"\n  Optimal Score: {order.get('optimal_score', 'N/A')}/100"

        prompt += f"\n\nEARLY DELIVERY CANDIDATES ({len(early)} orders):"
        for order in early:
            prompt += f"\n- Order #{order['order_id']}: {order['customer_name']}, {order['units']} units"
            prompt += f"\n  Address: {order['delivery_address']}"
            prompt += f"\n  Optimal Score: {order.get('optimal_score', 'N/A')}/100"

        prompt += f"\n\nRESCHEDULE CANDIDATES ({len(reschedule)} orders):"
        for order in reschedule:
            prompt += f"\n- Order #{order['order_id']}: {order['customer_name']}, {order['units']} units"
            prompt += f"\n  Address: {order['delivery_address']}"
            prompt += f"\n  Optimal Score: {order.get('optimal_score', 'N/A')}/100"

        prompt += f"\n\nCANCEL RECOMMENDATIONS ({len(cancel)} orders):"
        for order in cancel:
            prompt += f"\n- Order #{order['order_id']}: {order['customer_name']}, {order['units']} units"
            prompt += f"\n  Address: {order['delivery_address']}"
            prompt += f"\n  Optimal Score: {order.get('optimal_score', 'N/A')}/100"

        prompt += """

YOUR TASK:
Generate a brief, specific explanation (1-2 sentences) for EACH order explaining why it received its disposition.

Format your response EXACTLY as follows (one line per order):
ORDER_ID|explanation text here

Examples:
70509|Kept in route - optimal position in cluster, minimizes total drive time while fitting capacity constraints.
70592|Recommended for early delivery - only 8 minutes from route cluster and customer approved early delivery.
70610|Recommended for rescheduling - 15 minutes from cluster, would add significant time but could fit in adjacent window.
70611|Recommended for cancellation - 25+ minutes from route cluster, cost to serve exceeds delivery value.

Generate explanations for ALL orders listed above. Be specific about:
- Geographic reasoning (distances, cluster positioning)
- Efficiency factors (units delivered, time added)
- Constraint impacts (capacity, time window)
- Strategic recommendations (why this disposition makes business sense)

Format: ORDER_ID|explanation (one per line, no extra text)
"""

        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse response into dict
        explanations = {}
        response_text = response.content[0].text.strip()

        for line in response_text.split('\n'):
            line = line.strip()
            if '|' in line:
                parts = line.split('|', 1)
                if len(parts) == 2:
                    order_id = parts[0].strip()
                    explanation = parts[1].strip()
                    explanations[order_id] = explanation

        return explanations

    except Exception as e:
        print(f"Error generating order explanations: {e}")
        return None
