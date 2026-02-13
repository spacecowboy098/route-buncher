"""
Streamlit app for buncher-optimizer - Buncha Route Optimizer.
"""

import streamlit as st
import pandas as pd
from typing import List, Dict
from datetime import datetime
from streamlit_folium import st_folium

import config
import parser
import geocoder
import optimizer
import disposition
import chat_assistant


def format_time_minutes(minutes: int) -> str:
    """Format minutes as HH:MM."""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


def create_map_visualization(keep, cancel, early, reschedule, geocoded, depot_address, valid_orders, addresses, service_times):
    """Create an interactive Google Maps-style map using Folium."""
    try:
        import folium
        from folium import plugins

        # Get depot coordinates
        depot_geo = geocoded[0]
        if depot_geo["lat"] is None:
            return None

        # Calculate center point for map
        all_lats = [depot_geo["lat"]]
        all_lons = [depot_geo["lng"]]

        # Collect all coordinates
        for order in keep:
            if "node" in order and order["node"] is not None:
                try:
                    node_idx = int(order["node"])
                    if 0 <= node_idx < len(geocoded):
                        geo = geocoded[node_idx]
                        if geo["lat"] is not None:
                            all_lats.append(geo["lat"])
                            all_lons.append(geo["lng"])
                except (ValueError, TypeError, IndexError):
                    continue

        center_lat = sum(all_lats) / len(all_lats) if all_lats else depot_geo["lat"]
        center_lon = sum(all_lons) / len(all_lons) if all_lons else depot_geo["lng"]
    except Exception as e:
        print(f"Error in map setup: {e}")
        return None

    try:
        # Create Folium map with Google Maps tiles
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=12,
            tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}',
            attr='Google',
            name='Google Maps'
        )

        # Add route polyline FIRST (so it's under the markers)
        if keep:
            sorted_keep = sorted(keep, key=lambda x: x.get("sequence_index", 0))
            waypoint_order = [0]
            for order in sorted_keep:
                if "node" in order and order["node"] is not None:
                    try:
                        waypoint_order.append(int(order["node"]))
                    except (ValueError, TypeError):
                        pass
            waypoint_order.append(0)

            # Get actual road route
            try:
                route_coords = geocoder.get_route_polylines(addresses, waypoint_order)
                if route_coords:
                    # Draw the route as a green polyline
                    folium.PolyLine(
                        locations=route_coords,  # Already in (lat, lng) format
                        color='#00C800',  # Bright green
                        weight=4,
                        opacity=0.8,
                        tooltip="Delivery Route"
                    ).add_to(m)
            except Exception as e:
                print(f"Error drawing route polyline: {e}")
                # Continue without polyline
    except Exception as e:
        print(f"Error creating map object: {e}")
        return None

    try:
        # Add fulfillment location marker (blue)
        folium.Marker(
            location=[depot_geo["lat"], depot_geo["lng"]],
            popup=folium.Popup(f"<b>Fulfillment Location</b><br/>Starting Point", max_width=200),
            tooltip="🏠 Fulfillment Location",
            icon=folium.Icon(color='blue', icon='home', prefix='fa')
        ).add_to(m)
    except Exception as e:
        print(f"Error adding depot marker: {e}")

    # Add KEEP order markers (green)
    try:
        for order in sorted(keep, key=lambda x: x.get("sequence_index", 0)):
            if "node" not in order or order["node"] is None:
                continue
            try:
                node = int(order["node"])
                if node < 0 or node >= len(geocoded):
                    continue
                geo = geocoded[node]
                if geo["lat"] is None:
                    continue
                service_time = int(service_times[node]) if service_times and node < len(service_times) else 0

                # Ensure all order fields are properly typed
                order_id = str(order.get('order_id', ''))
                customer_name = str(order.get('customer_name', ''))
                units = int(order.get('units', 0))
                sequence_index = int(order.get('sequence_index', 0))
            except (ValueError, TypeError, IndexError, KeyError):
                continue

            # Detailed tooltip (shows on hover)
            tooltip_html = f"""
                <div style="font-family: Arial; font-size: 12px;">
                    <b>✅ Order #{order_id}</b><br/>
                    <b>Customer:</b> {customer_name}<br/>
                    <b>Units:</b> {units}<br/>
                    <b>Est. Service Time:</b> {service_time} min<br/>
                    <b>Sequence:</b> Stop #{sequence_index + 1}
                </div>
            """

            # Create custom icon with stop number
            stop_number = sequence_index + 1
            try:
                folium.Marker(
                    location=[geo["lat"], geo["lng"]],
                    tooltip=folium.Tooltip(tooltip_html, sticky=True),
                    icon=folium.DivIcon(html=f'''
                            <div style="
                                background-color: #28a745;
                                border: 2px solid white;
                                border-radius: 50%;
                                width: 30px;
                                height: 30px;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 14px;
                                font-weight: bold;
                                color: white;
                                box-shadow: 0 2px 5px rgba(0,0,0,0.3);
                            ">{stop_number}</div>
                        ''')
                ).add_to(m)
            except Exception as e:
                print(f"Error adding marker for order {order_id}: {e}")
                continue
    except Exception as e:
        print(f"Error in KEEP markers section: {e}")

    # Add EARLY/RESCHEDULE order markers (yellow/orange)
    try:
        for order in early + reschedule:
            try:
                order_id = str(order.get("order_id", ""))
                for idx, o in enumerate(valid_orders):
                    if o["order_id"] == order_id:
                        node = idx + 1
                        if node < len(geocoded):
                            geo = geocoded[node]
                            if geo["lat"] is not None:
                                category = str(order.get('category', 'RESCHEDULE'))
                                customer_name = str(order.get('customer_name', ''))
                                units = int(order.get('units', 0))
                                reason = str(order.get('reason', 'See details'))
                                tooltip_html = f"""
                                    <div style="font-family: Arial; font-size: 12px;">
                                        <b>🟡 Order #{order_id}</b><br/>
                                        <b>Customer:</b> {customer_name}<br/>
                                        <b>Units:</b> {units}<br/>
                                        <b>Action:</b> {category}<br/>
                                        <b>Reason:</b> {reason}
                                    </div>
                                """
                                folium.Marker(
                                    location=[geo["lat"], geo["lng"]],
                                    tooltip=folium.Tooltip(tooltip_html, sticky=True),
                                    icon=folium.Icon(color='orange', icon='clock', prefix='fa')
                                ).add_to(m)
                        break
            except Exception as e:
                print(f"Error adding early/reschedule marker: {e}")
                continue
    except Exception as e:
        print(f"Error in early/reschedule markers section: {e}")

    # Add CANCEL order markers (red)
    try:
        for order in cancel:
            try:
                order_id = str(order.get("order_id", ""))
                for idx, o in enumerate(valid_orders):
                    if o["order_id"] == order_id:
                        node = idx + 1
                        if node < len(geocoded):
                            geo = geocoded[node]
                            if geo["lat"] is not None:
                                customer_name = str(order.get('customer_name', ''))
                                units = int(order.get('units', 0))
                                reason = str(order.get('reason', 'Too far from route'))
                                tooltip_html = f"""
                                    <div style="font-family: Arial; font-size: 12px;">
                                        <b>🔴 Order #{order_id}</b><br/>
                                        <b>Customer:</b> {customer_name}<br/>
                                        <b>Units:</b> {units}<br/>
                                        <b>Action:</b> CANCEL<br/>
                                        <b>Reason:</b> {reason}
                                    </div>
                                """
                                folium.Marker(
                                    location=[geo["lat"], geo["lng"]],
                                    tooltip=folium.Tooltip(tooltip_html, sticky=True),
                                    icon=folium.Icon(color='red', icon='times', prefix='fa')
                                ).add_to(m)
                        break
            except Exception as e:
                print(f"Error adding cancel marker: {e}")
                continue
    except Exception as e:
        print(f"Error in cancel markers section: {e}")

    # Add fullscreen button
    try:
        plugins.Fullscreen().add_to(m)
    except Exception as e:
        print(f"Error adding fullscreen button: {e}")

    return m


def generate_route_explanation(keep, early, reschedule, cancel, time_matrix, vehicle_capacity, window_minutes):
    """Generate concise, utilitarian explanation for dispatchers."""
    explanation = []

    total_orders = len(keep) + len(early) + len(reschedule) + len(cancel)
    total_units = sum(o["units"] for o in keep)
    capacity_pct = (total_units / vehicle_capacity * 100) if vehicle_capacity > 0 else 0

    explanation.append(f"**Route Summary**: Optimized {total_orders} orders for {window_minutes}-min window")
    explanation.append(f"**Capacity Used**: {total_units}/{vehicle_capacity} units ({capacity_pct:.0f}%)\n")

    # KEEP rationale
    if keep:
        explanation.append(f"**✅ KEEP ({len(keep)} orders)**")
        explanation.append(f"These form a tight geographic cluster that fits capacity and time constraints. Route optimized to minimize drive time between stops.\n")

    # EARLY rationale
    if early:
        explanation.append(f"**⏰ EARLY DELIVERY ({len(early)} orders)**")
        explanation.append(f"Customer approved early delivery. These are <10 min from route cluster - move to earlier window for efficiency.\n")

    # RESCHEDULE rationale
    if reschedule:
        explanation.append(f"**📅 RESCHEDULE ({len(reschedule)} orders)**")
        explanation.append(f"Within 10-20 min of cluster but won't fit due to capacity/time. Move to adjacent window where they can group with other nearby orders.\n")

    # CANCEL rationale
    if cancel:
        explanation.append(f"**❌ CANCEL ({len(cancel)} orders)**")
        explanation.append(f"≥20 min from cluster - geographically isolated. Cost to serve exceeds revenue. Including them would force dropping multiple better-positioned orders.\n")

    explanation.append("**Why This Route**: Algorithm maximizes orders delivered within constraints. Uses real Google Maps drive times, not straight-line distance.")

    return "\n".join(explanation)


def display_optimization_results(keep, early, reschedule, cancel, kept, service_times, geocoded,
                                 depot_address, valid_orders, addresses, time_matrix,
                                 vehicle_capacity, window_minutes, strategy_desc, show_ai_explanations=True):
    """Display results for one optimization strategy."""

    # Summary metrics
    st.subheader("📊 Summary")
    col1, col2, col3, col4 = st.columns(4)

    total_kept_units = sum(o["units"] for o in keep)
    capacity_pct = (total_kept_units / vehicle_capacity * 100) if vehicle_capacity > 0 else 0

    with col1:
        st.metric("KEEP Orders", len(keep))
    with col2:
        st.metric("Capacity Used", f"{total_kept_units}/{vehicle_capacity}", f"{capacity_pct:.1f}%")
    with col3:
        if kept:
            # Calculate drive time
            drive_time = 0
            try:
                if kept:
                    first_node = int(kept[0]["node"])
                    drive_time += time_matrix[0][first_node]
                for i in range(len(kept) - 1):
                    from_node = int(kept[i]["node"])
                    to_node = int(kept[i + 1]["node"])
                    drive_time += time_matrix[from_node][to_node]
                if kept:
                    last_node = int(kept[-1]["node"])
                    drive_time += time_matrix[last_node][0]

                # Calculate service time
                total_service_time = 0
                if service_times:
                    for order in kept:
                        node = int(order["node"])
                        if node < len(service_times):
                            total_service_time += service_times[node]

                total_time = drive_time + total_service_time
                st.metric("Total Route Time", format_time_minutes(total_time),
                         f"Drive: {format_time_minutes(drive_time)}, Service: {format_time_minutes(total_service_time)}")
            except (ValueError, TypeError, KeyError, IndexError) as e:
                st.metric("Total Route Time", "Error calculating")
        else:
            st.metric("Total Route Time", "N/A")
    with col4:
        st.metric("Total Orders", len(keep) + len(early) + len(reschedule) + len(cancel))

    # Second row of KPIs
    col5, col6, col7, col8 = st.columns(4)

    # Calculate metrics for second row
    if kept:
        try:
            # Calculate drive time
            drive_time = 0
            if kept:
                first_node = int(kept[0]["node"])
                drive_time += time_matrix[0][first_node]
            for i in range(len(kept) - 1):
                from_node = int(kept[i]["node"])
                to_node = int(kept[i + 1]["node"])
                drive_time += time_matrix[from_node][to_node]
            if kept:
                last_node = int(kept[-1]["node"])
                drive_time += time_matrix[last_node][0]

            # Calculate service time
            total_service_time = 0
            if service_times:
                for order in kept:
                    node = int(order["node"])
                    if node < len(service_times):
                        total_service_time += service_times[node]

            total_time = drive_time + total_service_time
            route_miles = total_time * 0.5  # Approximate miles (0.5 miles per minute at 30 mph)
            deliveries_per_hour = (len(keep) / (total_time / 60)) if total_time > 0 else 0

            # Calculate dead leg (return to fulfillment location)
            last_node = int(kept[-1]["node"])
            dead_leg_time = time_matrix[last_node][0] if kept else 0
        except (ValueError, TypeError, KeyError, IndexError) as e:
            total_time = 0
            route_miles = 0
            deliveries_per_hour = 0
            dead_leg_time = 0
    else:
        total_time = 0
        route_miles = 0
        deliveries_per_hour = 0
        dead_leg_time = 0

    with col5:
        st.metric("Load Factor", f"{capacity_pct:.1f}%")
    with col6:
        st.metric("Route Miles", f"{route_miles:.1f}")
    with col7:
        st.metric("Deliveries/Hour", f"{deliveries_per_hour:.1f}")
    with col8:
        st.metric("Dead Leg", f"{dead_leg_time} min", help="Time from last delivery back to fulfillment location")

    # Map Visualization
    st.subheader("🗺️ Geographic Overview")
    try:
        map_chart = create_map_visualization(keep, cancel, early, reschedule, geocoded, depot_address,
                                            valid_orders, addresses, service_times)
        if map_chart:
            st_folium(map_chart, width=1200, height=600)

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown("🟢 **Green circle**: Orders to KEEP (on route)")
            with col2:
                st.markdown("🕒 **Orange clock**: Early/Reschedule options")
            with col3:
                st.markdown("❌ **Red X**: Orders to CANCEL (too far)")
            with col4:
                st.markdown("🏠 **Blue home**: Fulfillment Location")
        else:
            st.warning("❌ Error creating map: bad argument type for built-in operation")
            st.info("💡 Try loading a different cut or re-running the optimization.")
    except Exception as e:
        st.warning(f"❌ Error creating map: {str(e)}")
        st.info("💡 Try loading a different cut or re-running the optimization.")

    # Display route sequence
    if keep:
        st.subheader("🗺️ Route Sequence")
        route_parts = ["Fulfillment Location"]
        for k in sorted(keep, key=lambda x: x["sequence_index"]):
            route_parts.append(f"Order {k['order_id']}")
        route_parts.append("Fulfillment Location")
        st.write(" → ".join(route_parts))

    # Display KEEP orders
    st.subheader("✅ KEEP in this window")
    if keep:
        keep_data = []
        for k in sorted(keep, key=lambda x: x["sequence_index"]):
            row = {
                "Seq": k["sequence_index"] + 1,
                "Order ID": k["order_id"],
                "Customer": k["customer_name"],
                "Address": k["delivery_address"],
                "Units": k["units"],
                "Score": f"{k.get('optimal_score', 0)}/100",
                "Est. Service Time": f"{service_times[k['node']]} min" if service_times and k['node'] < len(service_times) else "N/A",
                "Est. Arrival": format_time_minutes(k["estimated_arrival"])
            }
            if show_ai_explanations:
                row["AI Explanation"] = k.get("ai_explanation", k.get("reason", ""))
            else:
                row["Reason"] = k.get("reason", "Included in route")
            keep_data.append(row)

        keep_df = pd.DataFrame(keep_data)
        st.dataframe(keep_df, width="stretch")
    else:
        st.info("No orders kept in route (capacity or time constraints too tight)")

    # Display EARLY DELIVERY orders
    st.subheader("⏰ Move to EARLY DELIVERY")
    if early:
        early_data = []
        for e in early:
            row = {
                "Order ID": e["order_id"],
                "Customer": e["customer_name"],
                "Address": e["delivery_address"],
                "Units": e["units"],
                "Score": f"{e.get('optimal_score', 0)}/100"
            }
            if show_ai_explanations:
                row["AI Explanation"] = e.get("ai_explanation", e.get("reason", ""))
            else:
                row["Reason"] = e.get("reason", "Close to route and early OK")
            early_data.append(row)

        early_df = pd.DataFrame(early_data)
        st.dataframe(early_df, width="stretch")
    else:
        st.info("No orders recommended for early delivery")

    # Display RESCHEDULE and CANCEL orders combined
    st.subheader("🚫 DO NOT DELIVER in this window")
    excluded_orders = []

    for r in reschedule:
        row = {
            "Action": "📅 RESCHEDULE",
            "Order ID": r["order_id"],
            "Customer": r["customer_name"],
            "Address": r["delivery_address"],
            "Units": r["units"],
            "Score": f"{r.get('optimal_score', 0)}/100"
        }
        if show_ai_explanations:
            row["AI Explanation"] = r.get("ai_explanation", r.get("reason", ""))
        else:
            row["Reason"] = r.get("reason", "Better fit in different window")
        excluded_orders.append(row)

    for c in cancel:
        row = {
            "Action": "❌ CANCEL",
            "Order ID": c["order_id"],
            "Customer": c["customer_name"],
            "Address": c["delivery_address"],
            "Units": c["units"],
            "Score": f"{c.get('optimal_score', 0)}/100"
        }
        if show_ai_explanations:
            row["AI Explanation"] = c.get("ai_explanation", c.get("reason", ""))
        else:
            row["Reason"] = c.get("reason", "Too far from cluster")
        excluded_orders.append(row)

    if excluded_orders:
        excluded_df = pd.DataFrame(excluded_orders)
        st.dataframe(excluded_df, width="stretch")

        # Summary counts
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"📅 {len(reschedule)} orders to reschedule")
        with col2:
            st.caption(f"❌ {len(cancel)} orders to cancel")
    else:
        st.info("All orders are being kept or delivered early")


def main():
    """Main Streamlit app."""
    st.set_page_config(page_title="The Buncher", page_icon="🚐", layout="wide")

    # Initialize session state for manual orders
    if "manual_orders" not in st.session_state:
        st.session_state.manual_orders = []

    # Initialize session state for chat
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "optimization_context" not in st.session_state:
        st.session_state.optimization_context = None
    if "waiting_for_ai_response" not in st.session_state:
        st.session_state.waiting_for_ai_response = False

    # Title
    st.title("🚐 The Buncher - Route Optimizer")

    st.markdown("""
    Internal tool for optimizing delivery routes with capacity and time constraints.
    Upload a CSV of orders to see which orders to keep, deliver early, reschedule, or cancel.
    """)

    # Sidebar configuration
    st.sidebar.header("Configuration")

    depot_address = st.sidebar.text_input(
        "Fulfillment Location",
        value=config.get_default_depot(),
        help="Starting location for deliveries"
    )

    vehicle_capacity = st.sidebar.number_input(
        "Vehicle Capacity (units)",
        min_value=50,
        max_value=500,
        value=config.get_default_capacity(),
        step=50,
        help="Maximum number of units the vehicle can carry"
    )

    window_override = st.sidebar.number_input(
        "Window Length Override (minutes)",
        min_value=0,
        max_value=240,
        value=0,
        step=15,
        help="Override delivery window length from CSV (0 = use CSV value). Useful when actual window is shorter than planned."
    )

    # File upload
    st.sidebar.header("Upload Orders")
    uploaded_file = st.sidebar.file_uploader(
        "Choose a CSV file",
        type=["csv"],
        help="Upload CSV with order data"
    )


    # Run buttons
    col1, col2 = st.sidebar.columns(2)
    with col1:
        run_with_ai = st.button("🚀 Run (with AI)", type="primary", use_container_width=True)
    with col2:
        run_no_ai = st.button("⚡ Run (no AI)", use_container_width=True)

    run_optimization = run_with_ai or run_no_ai
    use_ai = run_with_ai  # Track whether to use AI

    # Clear old results when starting new optimization
    if run_optimization:
        st.session_state.optimization_results = None
        st.session_state.optimization_context = None
        st.session_state.chat_messages = []
        st.session_state.use_ai = use_ai  # Store AI preference

    # AI Chat Assistant in sidebar (appears after optimization)
    if "optimization_results" in st.session_state and st.session_state.optimization_results:
        st.sidebar.markdown("---")
        st.sidebar.header("💬 Route Assistant")

        # Clear chat button
        if st.sidebar.button("🗑️ Clear Chat", key="clear_chat"):
            st.session_state.chat_messages = []
            st.session_state.waiting_for_ai_response = False
            st.rerun()

        # Chat messages container
        chat_container = st.sidebar.container(height=400)
        with chat_container:
            for message in st.session_state.chat_messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # Show loading indicator if waiting for AI response
            if st.session_state.waiting_for_ai_response:
                with st.chat_message("assistant"):
                    st.markdown("🤔 _Analyzing route data..._")

        # Process pending AI response if waiting
        if st.session_state.waiting_for_ai_response:
            api_key = config.get_anthropic_api_key()
            with st.spinner("AI is thinking..."):
                response = chat_assistant.chat_with_assistant(
                    st.session_state.chat_messages,
                    st.session_state.optimization_context,
                    api_key
                )
            st.session_state.chat_messages.append({"role": "assistant", "content": response})
            st.session_state.waiting_for_ai_response = False
            st.rerun()

        # Chat input
        if prompt := st.sidebar.chat_input("Ask about the route...", key="chat_input"):
            # Add user message and set waiting flag
            st.session_state.chat_messages.append({"role": "user", "content": prompt})
            st.session_state.waiting_for_ai_response = True
            st.rerun()

    # Main area
    if uploaded_file is None and not st.session_state.manual_orders:
        st.info("👈 Upload a CSV file or add orders manually to get started")

        st.subheader("Expected CSV Format")
        st.markdown("""
        Your CSV should have the following columns (exact names required):

        - `orderID` - Unique order identifier
        - `customer_name` - Customer name
        - `delivery_address` - Full delivery address
        - `number_of_units` - Number of units to deliver
        - `early_ok` - "Yes" or "No" (whether early delivery is allowed)
        - `delivery_window_start` - Start time (e.g., "09:00 AM")
        - `delivery_window_end` - End time (e.g., "11:00 AM")
        """)

        st.subheader("Example CSV")
        example_df = pd.DataFrame([
            {
                "orderID": "70509",
                "customer_name": "Michael Tomaszewski",
                "delivery_address": "6178 Gulley St Taylor 48180",
                "number_of_units": 2,
                "early_ok": "No",
                "delivery_window_start": "09:00 AM",
                "delivery_window_end": "11:00 AM"
            },
            {
                "orderID": "70592",
                "customer_name": "Gabriel Carrion",
                "delivery_address": "3522 Linden Street Dearborn 48124",
                "number_of_units": 26,
                "early_ok": "Yes",
                "delivery_window_start": "09:00 AM",
                "delivery_window_end": "11:00 AM"
            }
        ])
        st.dataframe(example_df, width="stretch")

    else:
        # Combine CSV orders with manual orders
        orders = []
        window_minutes = None

        try:
            if uploaded_file:
                csv_orders, window_minutes = parser.parse_csv(uploaded_file)
                orders.extend(csv_orders)

            if st.session_state.manual_orders:
                orders.extend(st.session_state.manual_orders)
                if window_minutes is None:
                    # Calculate from first manual order
                    first_order = st.session_state.manual_orders[0]
                    start_min = first_order["delivery_window_start"].hour * 60 + first_order["delivery_window_start"].minute
                    end_min = first_order["delivery_window_end"].hour * 60 + first_order["delivery_window_end"].minute
                    window_minutes = end_min - start_min

            # Apply window override if set
            original_window = window_minutes
            if window_override > 0:
                window_minutes = window_override
                st.info(f"⚙️ Window override applied: {original_window} min → {window_minutes} min")

            st.success(f"✅ Loaded {len(orders)} orders with {window_minutes}-minute delivery window")

            # Show preview with edit capability
            with st.expander("📋 Order Preview & Management", expanded=True):
                preview_df = pd.DataFrame([
                    {
                        "Order ID": o["order_id"],
                        "Customer": o["customer_name"],
                        "Address": o["delivery_address"],
                        "Units": o["units"],
                        "Early OK": "Yes" if o["early_delivery_ok"] else "No",
                        "Window": f"{o['delivery_window_start'].strftime('%I:%M %p')} - {o['delivery_window_end'].strftime('%I:%M %p')}"
                    }
                    for o in orders
                ])

                edited_df = st.data_editor(
                    preview_df,
                    num_rows="dynamic",
                    width="stretch",
                    key="order_editor"
                )

                st.caption(f"Showing all {len(orders)} orders. You can edit values directly or add/remove rows.")

            # Validate orders
            valid_orders, errors = parser.validate_orders(orders)

            if errors:
                st.error(f"❌ Found {len(errors)} validation errors:")
                for error in errors:
                    st.write(f"- {error}")

            if valid_orders and run_optimization:
                # Progress updates (no visual bar, just status messages)
                progress_text = st.empty()

                def update_progress(percent, step_name):
                    """Update progress status message"""
                    progress_text.markdown(f"🚐 **{step_name}** ({percent}%)")

                # Build address list: depot + order addresses
                update_progress(5, "Preparing addresses...")
                addresses = [depot_address] + [o["delivery_address"] for o in valid_orders]

                # Geocode and build time matrix
                update_progress(10, "Geocoding addresses...")
                geocoded = geocoder.geocode_addresses(addresses)

                # Check for geocoding failures
                failed_geocodes = [g for g in geocoded if g["lat"] is None]
                if failed_geocodes:
                    st.warning(f"⚠️ Failed to geocode {len(failed_geocodes)} addresses:")
                    for g in failed_geocodes[:5]:  # Show first 5
                        st.write(f"- {g['address']}")

                update_progress(25, "Building distance matrix...")
                time_matrix = geocoder.build_time_matrix(addresses)

                # Build demands array: depot has 0 demand
                update_progress(30, "Preparing optimization data...")
                demands = [0] + [o["units"] for o in valid_orders]

                # Build service times array: depot has 0 service time
                # Service time is unloading time per stop (2-7 minutes, non-linear with units)
                service_times = [0] + [optimizer.service_time_for_units(o["units"]) for o in valid_orders]

                # Run THREE optimization cuts with different strategies
                optimizations = {}

                # Helper function to calculate route metrics
                def calc_route_metrics(kept_orders, kept_nodes_data, service_times, time_matrix, vehicle_capacity):
                    total_units = sum(o["units"] for o in kept_orders)
                    load_factor = (total_units / vehicle_capacity * 100) if vehicle_capacity > 0 else 0

                    drive_time = 0
                    if kept_nodes_data:
                        try:
                            first_node = int(kept_nodes_data[0]["node"])
                            drive_time += time_matrix[0][first_node]
                            for i in range(len(kept_nodes_data) - 1):
                                from_node = int(kept_nodes_data[i]["node"])
                                to_node = int(kept_nodes_data[i + 1]["node"])
                                drive_time += time_matrix[from_node][to_node]
                            last_node = int(kept_nodes_data[-1]["node"])
                            drive_time += time_matrix[last_node][0]
                        except (ValueError, TypeError, KeyError, IndexError):
                            drive_time = 0

                    service_time = 0
                    try:
                        service_time = sum(service_times[int(o["node"])] for o in kept_nodes_data if int(o["node"]) < len(service_times))
                    except (ValueError, TypeError, KeyError, IndexError):
                        service_time = 0
                    total_time = drive_time + service_time

                    # Approximate miles (0.5 miles per minute at 30 mph average)
                    route_miles = total_time * 0.5
                    units_per_mile = total_units / route_miles if route_miles > 0 else 0
                    stops_per_mile = len(kept_orders) / route_miles if route_miles > 0 else 0

                    return {
                        'total_units': total_units,
                        'load_factor': load_factor,
                        'drive_time': drive_time,
                        'service_time': service_time,
                        'total_time': total_time,
                        'route_miles': route_miles,
                        'units_per_mile': units_per_mile,
                        'stops_per_mile': stops_per_mile
                    }

                # CUT 1: MAX ORDERS ON TIME (RECOMMENDED DEFAULT)
                update_progress(35, "Running Cut 1: Max Orders (Recommended)...")
                kept_max, dropped_max = optimizer.solve_route(
                    time_matrix=time_matrix,
                    demands=demands,
                    vehicle_capacity=vehicle_capacity,
                    max_route_time=window_minutes,
                    service_times=service_times,
                    drop_penalty=10000  # Very high - maximize orders served
                )
                keep_max, early_max, reschedule_max, cancel_max = disposition.classify_orders(
                    all_orders=valid_orders,
                    kept=kept_max,
                    dropped_nodes=dropped_max,
                    time_matrix=time_matrix
                )
                metrics_max = calc_route_metrics(keep_max, kept_max, service_times, time_matrix, vehicle_capacity)

                optimizations['max_orders'] = {
                    'keep': keep_max,
                    'early': early_max,
                    'reschedule': reschedule_max,
                    'cancel': cancel_max,
                    'kept': kept_max,
                    'cut_type': 'max_orders_recommended',
                    'strategy': 'Maximize orders served within constraints (RECOMMENDED)',
                    'penalty': 10000,
                    'orders_kept': len(keep_max),
                    **metrics_max
                }

                st.write(f"🔍 Cut 1 (Max Orders, penalty=10000): {len(keep_max)} orders, {metrics_max['total_units']} units ({metrics_max['load_factor']:.0f}%), {metrics_max['total_time']} min")
                st.write(f"   Density: {metrics_max['stops_per_mile']:.1f} stops/mile, {metrics_max['units_per_mile']:.1f} units/mile")

                # CUT 2: SHORTEST ROUTE THAT FILLS VAN
                # NEW APPROACH: Pre-filter by efficiency (units/distance), select most efficient orders
                update_progress(55, "Running Cut 2: Shortest Route (Efficiency-Based)...")

                # Step 1: Calculate efficiency score for each order (units per minute from depot)
                order_efficiency = []
                for idx, order in enumerate(valid_orders):
                    node = idx + 1  # Node 0 is depot, orders start at node 1
                    depot_distance = time_matrix[0][node]
                    if depot_distance > 0:
                        efficiency = order["units"] / depot_distance  # Units per minute
                    else:
                        efficiency = float('inf')  # At depot location

                    order_efficiency.append({
                        'order_idx': idx,
                        'node': node,
                        'order': order,
                        'efficiency': efficiency,
                        'depot_distance': depot_distance,
                        'units': order["units"]
                    })

                # Step 2: Sort by efficiency (highest first)
                order_efficiency.sort(key=lambda x: x['efficiency'], reverse=True)

                # Step 3: Greedily select most efficient orders until reaching 80-90% capacity
                target_capacity_min = vehicle_capacity * 0.80
                target_capacity_max = vehicle_capacity * 0.90

                selected_orders = []
                cumulative_units = 0

                for item in order_efficiency:
                    if cumulative_units >= target_capacity_max:
                        break
                    if cumulative_units + item['units'] <= vehicle_capacity:
                        selected_orders.append(item)
                        cumulative_units += item['units']
                        if cumulative_units >= target_capacity_min:
                            # We've hit target range, keep adding until we exceed max or run out
                            pass

                st.write(f"   Pre-selected {len(selected_orders)} most efficient orders ({cumulative_units} units, {cumulative_units/vehicle_capacity*100:.0f}% capacity)")
                st.write(f"   Efficiency range: {selected_orders[-1]['efficiency']:.2f} to {selected_orders[0]['efficiency']:.2f} units/min")

                # Step 4: Build filtered time matrix and demands for only selected orders
                selected_nodes = [0] + [item['node'] for item in selected_orders]  # Include depot

                # Create filtered time matrix
                filtered_time_matrix = []
                for from_node in selected_nodes:
                    row = []
                    for to_node in selected_nodes:
                        row.append(time_matrix[int(from_node)][int(to_node)])
                    filtered_time_matrix.append(row)

                # Create filtered demands and service times
                filtered_demands = [0] + [item['units'] for item in selected_orders]
                filtered_service_times = [0] + [service_times[item['node']] for item in selected_orders]

                # Step 5: Optimize ONLY the selected orders for shortest route
                update_progress(65, "Optimizing selected efficient orders...")
                kept_short_filtered, dropped_short_filtered = optimizer.solve_route(
                    time_matrix=filtered_time_matrix,
                    demands=filtered_demands,
                    vehicle_capacity=vehicle_capacity,
                    max_route_time=window_minutes,
                    service_times=filtered_service_times,
                    drop_penalty=100000  # High penalty - keep all selected orders if possible
                )

                # Map back to original node indexes
                kept_short = []
                for kept_item in kept_short_filtered:
                    filtered_node = kept_item['node']
                    if filtered_node > 0:  # Skip depot
                        original_node = selected_nodes[filtered_node]
                        kept_short.append({
                            'node': original_node,
                            'sequence_index': kept_item['sequence_index'],
                            'arrival_min': kept_item['arrival_min']
                        })

                # All non-selected orders are dropped
                all_selected_nodes = {item['node'] for item in selected_orders}
                kept_nodes = {k['node'] for k in kept_short}
                dropped_short = []
                for node in range(1, len(time_matrix)):
                    if node not in all_selected_nodes or node not in kept_nodes:
                        dropped_short.append(node)

                st.write(f"   Optimization kept {len(kept_short)}/{len(selected_orders)} pre-selected orders")

                keep_short, early_short, reschedule_short, cancel_short = disposition.classify_orders(
                    all_orders=valid_orders,
                    kept=kept_short,
                    dropped_nodes=dropped_short,
                    time_matrix=time_matrix
                )
                metrics_short = calc_route_metrics(keep_short, kept_short, service_times, time_matrix, vehicle_capacity)

                optimizations['shortest'] = {
                    'keep': keep_short,
                    'early': early_short,
                    'reschedule': reschedule_short,
                    'cancel': cancel_short,
                    'kept': kept_short,
                    'cut_type': 'shortest_route',
                    'strategy': 'Shortest route with most efficient orders (units/distance)',
                    'penalty': 100000,
                    'orders_kept': len(keep_short),
                    **metrics_short
                }

                st.write(f"🔍 Cut 2 (Shortest/Efficient): {len(keep_short)} orders, {metrics_short['total_units']} units ({metrics_short['load_factor']:.0f}%), {metrics_short['total_time']} min")
                st.write(f"   Efficiency: {metrics_short['units_per_mile']:.1f} units/mile, {metrics_short['stops_per_mile']:.1f} stops/mile")

                # CUT 3: HIGH DENSITY (maximize stops per minute within cluster, ignore depot distance)
                update_progress(75, "Running Cut 3: High Density (tight cluster)...")

                # Step 1: For each order, calculate average distance to all OTHER orders (cluster cohesion)
                order_cluster_scores = []
                for idx, order in enumerate(valid_orders):
                    node = idx + 1
                    # Calculate average distance to all other orders
                    distances_to_others = []
                    for other_idx in range(len(valid_orders)):
                        if other_idx != idx:
                            other_node = other_idx + 1
                            try:
                                distances_to_others.append(time_matrix[int(node)][int(other_node)])
                            except (ValueError, TypeError, IndexError):
                                pass

                    avg_distance_to_others = sum(distances_to_others) / len(distances_to_others) if distances_to_others else 0

                    order_cluster_scores.append({
                        'order_idx': idx,
                        'node': node,
                        'order': order,
                        'avg_distance_to_others': avg_distance_to_others,
                        'units': order["units"]
                    })

                # Step 2: Sort by cluster cohesion (lowest average distance to others = most central in cluster)
                order_cluster_scores.sort(key=lambda x: x['avg_distance_to_others'])

                # Step 3: Greedily select orders that are closest to each other
                target_capacity_min = vehicle_capacity * 0.80
                target_capacity_max = vehicle_capacity * 0.90

                dense_selected_orders = []
                cumulative_units_dense = 0

                for item in order_cluster_scores:
                    if cumulative_units_dense >= target_capacity_max:
                        break
                    if cumulative_units_dense + item['units'] <= vehicle_capacity:
                        dense_selected_orders.append(item)
                        cumulative_units_dense += item['units']
                        if cumulative_units_dense >= target_capacity_min:
                            pass

                st.write(f"   Pre-selected {len(dense_selected_orders)} tightly clustered orders ({cumulative_units_dense} units, {cumulative_units_dense/vehicle_capacity*100:.0f}% capacity)")
                if dense_selected_orders:
                    st.write(f"   Cluster cohesion: {dense_selected_orders[0]['avg_distance_to_others']:.1f} to {dense_selected_orders[-1]['avg_distance_to_others']:.1f} min avg distance")

                # Step 4: Build filtered time matrix and demands for dense cluster
                dense_nodes = [0] + [item['node'] for item in dense_selected_orders]

                # Create filtered time matrix
                dense_time_matrix = []
                for from_node in dense_nodes:
                    row = []
                    for to_node in dense_nodes:
                        row.append(time_matrix[int(from_node)][int(to_node)])
                    dense_time_matrix.append(row)

                # Create filtered demands and service times
                dense_demands = [0] + [item['units'] for item in dense_selected_orders]
                dense_service_times = [0] + [service_times[item['node']] for item in dense_selected_orders]

                # Step 5: Optimize for shortest route through dense cluster
                update_progress(85, "Optimizing dense cluster...")
                kept_dense_filtered, dropped_dense_filtered = optimizer.solve_route(
                    time_matrix=dense_time_matrix,
                    demands=dense_demands,
                    vehicle_capacity=vehicle_capacity,
                    max_route_time=window_minutes,
                    service_times=dense_service_times,
                    drop_penalty=100000  # High penalty - keep all selected orders
                )

                # Map back to original node indexes
                kept_dense = []
                for kept_item in kept_dense_filtered:
                    filtered_node = kept_item['node']
                    if filtered_node > 0:
                        original_node = dense_nodes[filtered_node]
                        kept_dense.append({
                            'node': original_node,
                            'sequence_index': kept_item['sequence_index'],
                            'arrival_min': kept_item['arrival_min']
                        })

                # All non-selected orders are dropped
                all_dense_nodes = {item['node'] for item in dense_selected_orders}
                kept_dense_nodes = {k['node'] for k in kept_dense}
                dropped_dense = []
                for node in range(1, len(time_matrix)):
                    if node not in all_dense_nodes or node not in kept_dense_nodes:
                        dropped_dense.append(node)

                st.write(f"   Optimization kept {len(kept_dense)}/{len(dense_selected_orders)} cluster orders")

                # Calculate cluster-only metrics (first stop to last stop, excluding depot)
                cluster_drive_time = 0
                if len(kept_dense) > 1:
                    sorted_dense = sorted(kept_dense, key=lambda x: x['sequence_index'])
                    for i in range(len(sorted_dense) - 1):
                        try:
                            from_node = int(sorted_dense[i]['node'])
                            to_node = int(sorted_dense[i + 1]['node'])
                            cluster_drive_time += time_matrix[from_node][to_node]
                        except (ValueError, TypeError, KeyError, IndexError):
                            pass

                cluster_density = len(kept_dense) / cluster_drive_time if cluster_drive_time > 0 else 0
                st.write(f"   Cluster density: {cluster_density:.2f} stops/min within cluster (excluding fulfillment location legs)")

                keep_dense, early_dense, reschedule_dense, cancel_dense = disposition.classify_orders(
                    all_orders=valid_orders,
                    kept=kept_dense,
                    dropped_nodes=dropped_dense,
                    time_matrix=time_matrix
                )
                metrics_dense = calc_route_metrics(keep_dense, kept_dense, service_times, time_matrix, vehicle_capacity)

                # Store cluster-specific density metric
                metrics_dense['cluster_density'] = cluster_density
                metrics_dense['cluster_drive_time'] = cluster_drive_time

                optimizations['high_density'] = {
                    'keep': keep_dense,
                    'early': early_dense,
                    'reschedule': reschedule_dense,
                    'cancel': cancel_dense,
                    'kept': kept_dense,
                    'cut_type': 'high_density',
                    'strategy': 'High-density cluster (maximize stops/min within cluster)',
                    'penalty': 100000,
                    'orders_kept': len(keep_dense),
                    **metrics_dense
                }

                st.write(f"🔍 Cut 3 (High Density): {len(keep_dense)} orders, {metrics_dense['total_units']} units ({metrics_dense['load_factor']:.0f}%), {metrics_dense['total_time']} min")
                st.write(f"   Cluster: {cluster_density:.2f} stops/min, overall: {metrics_dense['stops_per_mile']:.1f} stops/mile")

                st.write(f"\n📊 SUMMARY: Total input orders: {len(valid_orders)}")
                st.write(f"   Cut 1 (Max Orders): {len(keep_max)} orders, {metrics_max['total_units']} units, {metrics_max['total_time']} min, {metrics_max['stops_per_mile']:.1f} stops/mi")
                st.write(f"   Cut 2 (Shortest): {len(keep_short)} orders, {metrics_short['total_units']} units, {metrics_short['total_time']} min, {metrics_short['stops_per_mile']:.1f} stops/mi")
                st.write(f"   Cut 3 (High Density): {len(keep_dense)} orders, {metrics_dense['total_units']} units, {metrics_dense['total_time']} min, {cluster_density:.2f} cluster stops/min")

                # CUT 4: DISPATCHER SANDBOX (manual editing - initialized from Cut 1)
                # Initialize sandbox from Cut 1 (default), will be editable in the tab
                optimizations['sandbox'] = {
                    'keep': keep_max.copy(),
                    'early': early_max.copy(),
                    'reschedule': reschedule_max.copy(),
                    'cancel': cancel_max.copy(),
                    'kept': [k.copy() for k in kept_max],
                    'cut_type': 'sandbox',
                    'strategy': 'Dispatcher Sandbox (manual editing)',
                    'penalty': 10000,
                    'orders_kept': len(keep_max),
                    **metrics_max
                }

                # Generate AI explanations for MAX ORDERS strategy (recommended default) - ONLY if use_ai is True
                if st.session_state.get('use_ai', False):
                    update_progress(80, "Generating AI explanations...")
                    api_key = config.get_anthropic_api_key()
                    keep_rec = optimizations['max_orders']['keep']
                    early_rec = optimizations['max_orders']['early']
                    reschedule_rec = optimizations['max_orders']['reschedule']
                    cancel_rec = optimizations['max_orders']['cancel']

                    ai_explanations = chat_assistant.generate_order_explanations(
                        keep_rec, early_rec, reschedule_rec, cancel_rec, time_matrix, depot_address, api_key
                    )

                    # Update RECOMMENDED orders with AI-generated explanations
                    if ai_explanations:
                        for order in keep_rec + early_rec + reschedule_rec + cancel_rec:
                            order_id = str(order['order_id'])
                            if order_id in ai_explanations:
                                order['ai_explanation'] = ai_explanations[order_id]
                else:
                    update_progress(80, "Skipping AI explanations...")

                # Store both optimization results in session state
                update_progress(90, "Storing results...")
                st.session_state.optimization_results = {
                        'optimizations': optimizations,  # Dict with 'max_orders', 'shortest', 'high_density', 'sandbox'
                        'geocoded': geocoded,
                        'depot_address': depot_address,
                        'valid_orders': valid_orders,
                        'addresses': addresses,
                        'time_matrix': time_matrix,
                        'vehicle_capacity': vehicle_capacity,
                        'window_minutes': window_minutes,
                        'service_times': service_times
                }

                # Initialize chat messages with MAX ORDERS route explanation and AI validation - ONLY if use_ai is True
                if st.session_state.get('use_ai', False):
                    update_progress(95, "Preparing AI chat assistant...")
                    st.session_state.chat_messages = []

                    # Use MAX ORDERS strategy for chat context (recommended default)
                    keep_rec = optimizations['max_orders']['keep']
                    early_rec = optimizations['max_orders']['early']
                    reschedule_rec = optimizations['max_orders']['reschedule']
                    cancel_rec = optimizations['max_orders']['cancel']

                    # Add route explanation as first message
                    explanation = generate_route_explanation(
                        keep_rec, early_rec, reschedule_rec, cancel_rec,
                        time_matrix, vehicle_capacity, window_minutes
                    )
                    st.session_state.chat_messages.append({
                        "role": "assistant",
                        "content": explanation
                    })

                    # Add AI validation as second message (validates math and logic)
                    api_key = config.get_anthropic_api_key()
                    validation = chat_assistant.validate_optimization_results(
                        keep_rec, early_rec, reschedule_rec, cancel_rec, valid_orders,
                        time_matrix, service_times, vehicle_capacity, window_minutes, api_key
                    )

                    if validation:
                        st.session_state.chat_messages.append({
                            "role": "assistant",
                            "content": f"**🔍 AI Route Validation (Cut 1: Max Orders)**\n\n{validation}"
                        })

                    # Store optimization context for chat (using MAX ORDERS)
                    st.session_state.optimization_context = chat_assistant.create_context_for_ai(
                        keep_rec, early_rec, reschedule_rec, cancel_rec, valid_orders,
                        time_matrix, vehicle_capacity, window_minutes, depot_address
                    )
                else:
                    update_progress(95, "Skipping AI chat setup...")
                    st.session_state.chat_messages = []
                    st.session_state.optimization_context = None

                update_progress(100, "Complete! 🎉")

                # Clear progress text after a moment
                import time
                time.sleep(1)
                progress_text.empty()

                st.success("✅ Optimization complete!")

            # Display results (either from fresh optimization or from session state)
            if "optimization_results" in st.session_state and st.session_state.optimization_results:
                # Extract common data from session state
                results = st.session_state.optimization_results
                optimizations = results['optimizations']
                geocoded = results['geocoded']
                depot_address = results['depot_address']
                valid_orders = results['valid_orders']
                addresses = results['addresses']
                time_matrix = results['time_matrix']
                vehicle_capacity = results['vehicle_capacity']
                window_minutes = results['window_minutes']
                service_times = results.get('service_times', [])

                # Show 2-cut comparison summary
                # Create tabs for four optimization cuts with order counts in titles
                max_orders_count = optimizations['max_orders']['orders_kept']
                shortest_orders_count = optimizations['shortest']['orders_kept']
                density_orders_count = optimizations['high_density']['orders_kept']
                sandbox_orders_count = optimizations['sandbox']['orders_kept']

                tab1, tab2, tab3, tab4 = st.tabs([
                    f"✅ Cut 1: Max Orders ({max_orders_count} Orders) - RECOMMENDED",
                    f"⚡ Cut 2: Shortest Route ({shortest_orders_count} Orders)",
                    f"🎯 Cut 3: High Density ({density_orders_count} Orders)",
                    f"✏️ Cut 4: Dispatcher Sandbox ({sandbox_orders_count} Orders)"
                ])

                # TAB 1: MAX ORDERS (RECOMMENDED - default view)
                with tab1:
                    opt = optimizations['max_orders']
                    st.info(f"**Cut 1 - Max Orders on Time (RECOMMENDED)**: Maximizes number of orders delivered within constraints - **{opt['orders_kept']} orders, {opt['total_units']} units ({opt['load_factor']:.0f}%), {opt['route_miles']:.1f} miles, {opt['total_time']} min**")

                    st.markdown("---")

                    display_optimization_results(
                        keep=opt['keep'],
                        early=opt['early'],
                        reschedule=opt['reschedule'],
                        cancel=opt['cancel'],
                        kept=opt['kept'],
                        service_times=service_times,
                        geocoded=geocoded,
                        depot_address=depot_address,
                        valid_orders=valid_orders,
                        addresses=addresses,
                        time_matrix=time_matrix,
                        vehicle_capacity=vehicle_capacity,
                        window_minutes=window_minutes,
                        strategy_desc=opt['strategy'],
                        show_ai_explanations=True
                    )

                # TAB 2: SHORTEST ROUTE THAT FILLS VAN
                with tab2:
                    opt = optimizations['shortest']
                    st.info(f"**Cut 2 - Shortest Route (Efficiency-Based)**: Selects most efficient orders (high units/distance) targeting 80-90% capacity - **{opt['orders_kept']} orders, {opt['total_units']} units ({opt['load_factor']:.0f}%), {opt['route_miles']:.1f} miles, {opt['total_time']} min**")

                    display_optimization_results(
                        keep=opt['keep'],
                        early=opt['early'],
                        reschedule=opt['reschedule'],
                        cancel=opt['cancel'],
                        kept=opt['kept'],
                        service_times=service_times,
                        geocoded=geocoded,
                        depot_address=depot_address,
                        valid_orders=valid_orders,
                        addresses=addresses,
                        time_matrix=time_matrix,
                        vehicle_capacity=vehicle_capacity,
                        window_minutes=window_minutes,
                        strategy_desc=opt['strategy'],
                        show_ai_explanations=False
                    )

                # TAB 3: HIGH DENSITY CLUSTER
                with tab3:
                    opt = optimizations['high_density']
                    st.info(f"**Cut 3 - High Density Cluster**: Selects tightly grouped orders to maximize density within cluster - **{opt['orders_kept']} orders, {opt['total_units']} units ({opt['load_factor']:.0f}%), {opt['route_miles']:.1f} miles, {opt['total_time']} min**")

                    display_optimization_results(
                        keep=opt['keep'],
                        early=opt['early'],
                        reschedule=opt['reschedule'],
                        cancel=opt['cancel'],
                        kept=opt['kept'],
                        service_times=service_times,
                        geocoded=geocoded,
                        depot_address=depot_address,
                        valid_orders=valid_orders,
                        addresses=addresses,
                        time_matrix=time_matrix,
                        vehicle_capacity=vehicle_capacity,
                        window_minutes=window_minutes,
                        strategy_desc=opt['strategy'],
                        show_ai_explanations=False
                    )

                # TAB 4: DISPATCHER SANDBOX (MANUAL EDITING)
                with tab4:
                    st.info("**Cut 4 - Dispatcher Sandbox**: Manually adjust orders, reorder stops, and move orders between categories. Map and KPIs update in real-time.")

                    # Selector to choose starting cut
                    starting_cut = st.selectbox(
                        "Start from:",
                        options=["Cut 1: Max Orders", "Cut 2: Shortest Route", "Cut 3: High Density"],
                        key="sandbox_starting_cut"
                    )

                    if st.button("📋 Load Selected Cut", type="primary", use_container_width=True):
                            # Load selected cut into sandbox
                            if "Cut 1" in starting_cut:
                                source_opt = optimizations['max_orders']
                            elif "Cut 2" in starting_cut:
                                source_opt = optimizations['shortest']
                            else:
                                source_opt = optimizations['high_density']

                            # Deep copy to avoid modifying source
                            st.session_state.optimization_results['optimizations']['sandbox'] = {
                                'keep': [o.copy() for o in source_opt['keep']],
                                'early': [o.copy() for o in source_opt['early']],
                                'reschedule': [o.copy() for o in source_opt['reschedule']],
                                'cancel': [o.copy() for o in source_opt['cancel']],
                                'kept': [k.copy() for k in source_opt['kept']],
                                'cut_type': 'sandbox',
                                'strategy': f'Dispatcher Sandbox (from {starting_cut})',
                                'penalty': source_opt['penalty'],
                                'orders_kept': source_opt['orders_kept'],
                                **{k: v for k, v in source_opt.items() if k not in ['keep', 'early', 'reschedule', 'cancel', 'kept', 'cut_type', 'strategy', 'penalty', 'orders_kept']}
                            }
                            st.success(f"✅ Loaded {starting_cut} into Sandbox! Scroll down to see updated map and make edits.")

                    st.markdown("---")

                    opt = optimizations['sandbox']

                    # Show current metrics (with safety checks)
                    try:
                        total_time = opt.get('total_time', 0)
                        orders_kept = opt.get('orders_kept', 0)
                        deliveries_per_hour = (orders_kept / (total_time / 60)) if total_time > 0 else 0

                        metric_col1, metric_col2, metric_col3 = st.columns(3)
                        with metric_col1:
                            st.metric("Load Factor", f"{opt.get('load_factor', 0):.1f}%")
                        with metric_col2:
                            st.metric("Route Miles", f"{opt.get('route_miles', 0):.1f}")
                        with metric_col3:
                            st.metric("Deliveries/Hour", f"{deliveries_per_hour:.1f}")
                    except Exception as e:
                        st.error(f"Error displaying metrics: {e}")

                    st.markdown("---")

                    st.subheader("📝 Edit Orders")

                    # Combine all orders into a single editable dataframe
                    all_orders_for_edit = []

                    # KEEP orders
                    for order in opt['keep']:
                        all_orders_for_edit.append({
                            'Order ID': order['order_id'],
                            'Customer': order['customer_name'],
                            'Units': order['units'],
                            'Status': 'KEEP',
                            'Sequence': order.get('sequence_index', 0) + 1,
                            'Address': order['delivery_address']
                        })

                    # EARLY orders
                    for order in opt['early']:
                        all_orders_for_edit.append({
                            'Order ID': order['order_id'],
                            'Customer': order['customer_name'],
                            'Units': order['units'],
                            'Status': 'EARLY',
                            'Sequence': None,
                            'Address': order['delivery_address']
                        })

                    # RESCHEDULE orders
                    for order in opt['reschedule']:
                        all_orders_for_edit.append({
                            'Order ID': order['order_id'],
                            'Customer': order['customer_name'],
                            'Units': order['units'],
                            'Status': 'RESCHEDULE',
                            'Sequence': None,
                            'Address': order['delivery_address']
                        })

                    # CANCEL orders
                    for order in opt['cancel']:
                        all_orders_for_edit.append({
                            'Order ID': order['order_id'],
                            'Customer': order['customer_name'],
                            'Units': order['units'],
                            'Status': 'CANCEL',
                            'Sequence': None,
                            'Address': order['delivery_address']
                        })

                    edit_df = pd.DataFrame(all_orders_for_edit)

                    st.write("**Instructions**: Change Status dropdown to move orders between categories. For KEEP orders, adjust Sequence to reorder stops. Click Apply Changes when done.")

                    edited_df = st.data_editor(
                        edit_df,
                        column_config={
                            "Status": st.column_config.SelectboxColumn(
                                "Status",
                                options=["KEEP", "EARLY", "RESCHEDULE", "CANCEL"],
                                required=True
                            ),
                            "Sequence": st.column_config.NumberColumn(
                                "Sequence",
                                help="Stop order for KEEP orders (1, 2, 3...)",
                                min_value=1,
                                step=1
                            )
                        },
                        disabled=["Order ID", "Customer", "Units", "Address"],
                        hide_index=True,
                        use_container_width=True,
                        key="sandbox_editor"
                    )

                    if st.button("✅ Apply Changes & Recalculate", type="primary", use_container_width=True):
                        # Rebuild optimization based on edited dataframe
                        new_keep = []
                        new_early = []
                        new_reschedule = []
                        new_cancel = []

                        for _, row in edited_df.iterrows():
                            # Find original order
                            order_id = row['Order ID']
                            original_order = None
                            for o in valid_orders:
                                if o['order_id'] == order_id:
                                    original_order = o
                                    break

                            if not original_order:
                                continue

                            # Build order dict based on status
                            order_dict = {
                                'order_id': order_id,
                                'customer_name': row['Customer'],
                                'delivery_address': row['Address'],
                                'units': row['Units'],
                                'early_delivery_ok': original_order['early_delivery_ok'],
                                'category': row['Status']
                            }

                            if row['Status'] == 'KEEP':
                                seq = int(row['Sequence']) if pd.notna(row['Sequence']) else 1
                                order_dict['sequence_index'] = seq - 1
                                order_dict['node'] = valid_orders.index(original_order) + 1
                                new_keep.append(order_dict)
                            elif row['Status'] == 'EARLY':
                                order_dict['reason'] = 'Moved to Early by dispatcher'
                                new_early.append(order_dict)
                            elif row['Status'] == 'RESCHEDULE':
                                order_dict['reason'] = 'Moved to Reschedule by dispatcher'
                                new_reschedule.append(order_dict)
                            else:  # CANCEL
                                order_dict['reason'] = 'Moved to Cancel by dispatcher'
                                new_cancel.append(order_dict)

                        # Sort KEEP by sequence
                        new_keep.sort(key=lambda x: x['sequence_index'])

                        # Recalculate route metrics
                        # Build kept nodes for metrics calculation
                        new_kept = []
                        for order in new_keep:
                            new_kept.append({
                                'node': order['node'],
                                'sequence_index': order['sequence_index'],
                                'arrival_min': 0  # Placeholder, will recalc
                            })

                        # Calculate metrics
                        def calc_route_metrics_sandbox(kept_orders, kept_nodes_data, service_times, time_matrix, vehicle_capacity):
                            total_units = sum(int(o["units"]) for o in kept_orders)
                            load_factor = (total_units / vehicle_capacity * 100) if vehicle_capacity > 0 else 0

                            drive_time = 0
                            if kept_nodes_data and len(kept_nodes_data) > 0:
                                try:
                                    # Depot to first stop
                                    first_node = int(kept_nodes_data[0]["node"])
                                    drive_time += int(time_matrix[0][first_node])

                                    # Between stops
                                    for i in range(len(kept_nodes_data) - 1):
                                        from_node = int(kept_nodes_data[i]["node"])
                                        to_node = int(kept_nodes_data[i + 1]["node"])
                                        drive_time += int(time_matrix[from_node][to_node])

                                    # Last stop to depot
                                    last_node = int(kept_nodes_data[-1]["node"])
                                    drive_time += int(time_matrix[last_node][0])
                                except (TypeError, ValueError, IndexError) as e:
                                    st.warning(f"Error calculating drive time: {e}")
                                    drive_time = 0

                            service_time = 0
                            for o in kept_nodes_data:
                                node = int(o["node"])
                                if node < len(service_times):
                                    service_time += int(service_times[node])

                            total_time = drive_time + service_time

                            route_miles = total_time * 0.5
                            units_per_mile = total_units / route_miles if route_miles > 0 else 0
                            stops_per_mile = len(kept_orders) / route_miles if route_miles > 0 else 0

                            return {
                                'total_units': int(total_units),
                                'load_factor': float(load_factor),
                                'drive_time': int(drive_time),
                                'service_time': int(service_time),
                                'total_time': int(total_time),
                                'route_miles': float(route_miles),
                                'units_per_mile': float(units_per_mile),
                                'stops_per_mile': float(stops_per_mile)
                            }

                        new_metrics = calc_route_metrics_sandbox(new_keep, new_kept, service_times, time_matrix, vehicle_capacity)

                        # Update sandbox optimization
                        st.session_state.optimization_results['optimizations']['sandbox'] = {
                            'keep': new_keep,
                            'early': new_early,
                            'reschedule': new_reschedule,
                            'cancel': new_cancel,
                            'kept': new_kept,
                            'cut_type': 'sandbox',
                            'strategy': 'Dispatcher Sandbox (manually edited)',
                            'penalty': 0,
                            'orders_kept': len(new_keep),
                            **new_metrics
                        }

                        st.success(f"✅ Recalculated! Route now has {len(new_keep)} orders. Scroll down to see updated map.")

                    st.markdown("---")

                    # Refresh opt from session state (in case it was updated by Apply Changes button)
                    opt = st.session_state.optimization_results['optimizations']['sandbox']

                    # Display map only (no detailed breakdowns)
                    st.subheader("📍 Route Map")
                    try:
                        # Ensure all required data exists
                        if opt.get('keep') is not None and geocoded and depot_address:
                            map_chart = create_map_visualization(
                                opt.get('keep', []),
                                opt.get('cancel', []),
                                opt.get('early', []),
                                opt.get('reschedule', []),
                                geocoded,
                                depot_address,
                                valid_orders,
                                addresses,
                                service_times
                            )
                            st.components.v1.html(map_chart, height=600)
                        else:
                            st.warning("⚠️ Map data not available. Please load a cut using the button above.")
                    except Exception as e:
                        st.error(f"❌ Error creating map: {e}")
                        st.info("Try loading a different cut or re-running the optimization.")

        except Exception as e:
            st.error(f"❌ Error processing file: {e}")
            import traceback
            with st.expander("Error details"):
                st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
