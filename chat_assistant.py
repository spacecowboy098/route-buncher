"""
AI Chat Assistant for route optimization conversations.
Helps dispatchers understand decisions and ask questions.
"""

import anthropic
from typing import List, Dict, Optional, Tuple
import config
import json


def generate_mock_validation(keep, early, reschedule, cancel, vehicle_capacity, window_minutes):
    """
    Generate template-based validation for test mode (no API call).

    Args:
        keep: List of orders kept in route
        early: List of orders for early delivery
        reschedule: List of orders to reschedule
        cancel: List of orders to cancel
        vehicle_capacity: Vehicle capacity in units
        window_minutes: Delivery window in minutes

    Returns:
        str: Mock validation message
    """
    kept_units = sum(o.get('units', 0) for o in keep)
    capacity_pct = (kept_units / vehicle_capacity * 100) if vehicle_capacity > 0 else 0

    return f"""✅ Route validation (Test Mode - Mock Response):

**Capacity Check:**
- {len(keep)} orders kept ({kept_units}/{vehicle_capacity} units = {capacity_pct:.1f}%)
- Capacity constraint satisfied

**Order Disposition:**
- {len(keep)} orders on route
- {len(early)} orders for early delivery
- {len(reschedule)} orders to reschedule
- {len(cancel)} orders to cancel

**Time Estimate:**
- Estimated route time: {window_minutes} minutes (test mode uses simplified calculation)

**Test Mode Notice:** This is a mock validation. Enable AI (disable test mode) for detailed route analysis."""


def generate_mock_order_explanations(orders):
    """
    Generate generic explanations for test mode (no API call).

    Args:
        orders: List of orders needing explanations

    Returns:
        Dict mapping order_id to generic explanation
    """
    explanations = {}
    for order in orders:
        order_id = str(order.get('order_id', ''))
        category = order.get('category', 'UNKNOWN').upper()

        if category == 'KEEP':
            explanation = "Test mode - Order kept in optimized route"
        elif category == 'EARLY':
            explanation = "Test mode - Order eligible for early delivery"
        elif category == 'RESCHEDULE':
            explanation = "Test mode - Order recommended for rescheduling"
        elif category == 'CANCEL':
            explanation = "Test mode - Order recommended for cancellation"
        else:
            explanation = "Test mode - Generic reason"

        explanations[order_id] = explanation

    return explanations


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
You can answer questions about the optimization results and help dispatchers understand routing decisions.

**What You Can Do:**
- Explain why specific orders were kept, rescheduled, or cancelled
- Analyze capacity and time constraints
- Answer "what if" questions about route modifications
- Suggest which orders are easiest to add back or remove
- Provide insights on route efficiency and optimization trade-offs

**Common Questions:**
**"Why is order #X not included?"**
→ Explain the reason based on distance, capacity, or time constraints

**"What if I remove order #X?"**
→ Calculate the impact on capacity and time

**"Can order #X be added back?"**
→ Analyze feasibility based on current route constraints

**IMPORTANT:**
✅ Provide specific data-driven answers using the optimization context
✅ Reference actual order numbers, distances, and constraints
✅ Explain trade-offs clearly when suggesting modifications
✅ Note that to make actual changes, dispatcher should re-run optimization or adjust constraints
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
        str: AI response text
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

        # Format system as list of content blocks
        system_blocks = [{"type": "text", "text": str(context)}]

        # Call Claude API (no tool support)
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1500,
            system=system_blocks,
            messages=api_messages
        )

        # Extract text response
        final_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                final_text += block.text

        return final_text

    except Exception as e:
        return f"❌ Error communicating with AI assistant: {str(e)}"


def validate_optimization_results(keep, early, reschedule, cancel, valid_orders, time_matrix,
                                   service_times, vehicle_capacity, window_minutes, api_key):
    """
    Use AI to validate optimization results and explain route logic.

    Returns:
        str: AI validation and explanation
    """
    # Check if AI is enabled (considers test mode and API key)
    if not config.is_ai_enabled():
        return generate_mock_validation(keep, early, reschedule, cancel, vehicle_capacity, window_minutes)

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
        "Can I add back order #70610?",
        "What if I remove order #70509?",
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
    # Check if AI is enabled (considers test mode and API key)
    if not config.is_ai_enabled():
        all_orders = keep + early + reschedule + cancel
        return generate_mock_order_explanations(all_orders)

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


def call_claude_api(prompt: str, api_key: str = None) -> str:
    """
    Simple helper function to call Claude API with a single prompt.
    Used for validation and analysis tasks.

    Args:
        prompt: The prompt to send to Claude
        api_key: Anthropic API key (optional, will use config if not provided)

    Returns:
        Claude's response text
    """
    if api_key is None:
        api_key = config.get_anthropic_api_key()

    if not api_key or api_key == "YOUR_ANTHROPIC_API_KEY_HERE":
        return "⚠️ AI assistant is not configured. Please add your ANTHROPIC_API_KEY to the .env file."

    try:
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        return response.content[0].text

    except Exception as e:
        return f"⚠️ Error calling Claude API: {str(e)}"
