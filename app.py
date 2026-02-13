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


def extract_all_csv_fields(order: Dict) -> Dict:
    """
    Extract all original CSV fields from an order object.
    Returns a dict with all CSV columns that should be displayed.
    """
    # Fields to exclude from display (internal optimizer fields and already-shown core fields)
    exclude_fields = {
        "node", "sequence_index", "estimated_arrival", "optimal_score",
        "ai_explanation", "reason", "early_delivery_ok", "delivery_window_start",
        "delivery_window_end", "order_id", "customer_name", "delivery_address", "units"
    }

    # Extract all fields that aren't internal or already displayed
    csv_fields = {}
    for key, value in order.items():
        if key not in exclude_fields and value is not None:
            csv_fields[key] = value

    return csv_fields


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
                    <b>customerID:</b> {customer_name}<br/>
                    <b>numberOfUnits:</b> {units}<br/>
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
                                        <b>customerID:</b> {customer_name}<br/>
                                        <b>numberOfUnits:</b> {units}<br/>
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
                                        <b>customerID:</b> {customer_name}<br/>
                                        <b>numberOfUnits:</b> {units}<br/>
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
            # Start with key display fields
            row = {
                "Seq": k["sequence_index"] + 1,
                "externalOrderId": k["order_id"],
                "customerID": k["customer_name"],
                "address": k["delivery_address"],
                "numberOfUnits": k["units"]
            }

            # Add all original CSV fields
            csv_fields = extract_all_csv_fields(k)
            row.update(csv_fields)

            # Add optimizer-computed fields at the end
            row["Score"] = f"{k.get('optimal_score', 0)}/100"
            row["Est. Service Time"] = f"{service_times[k['node']]} min" if service_times and k['node'] < len(service_times) else "N/A"
            row["Est. Arrival"] = format_time_minutes(k["estimated_arrival"])

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
            # Start with key display fields
            row = {
                "externalOrderId": e["order_id"],
                "customerID": e["customer_name"],
                "address": e["delivery_address"],
                "numberOfUnits": e["units"]
            }

            # Add all original CSV fields
            csv_fields = extract_all_csv_fields(e)
            row.update(csv_fields)

            # Add optimizer-computed fields at the end
            row["Score"] = f"{e.get('optimal_score', 0)}/100"

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
        # Start with key display fields
        row = {
            "Action": "📅 RESCHEDULE",
            "externalOrderId": r["order_id"],
            "customerID": r["customer_name"],
            "address": r["delivery_address"],
            "numberOfUnits": r["units"]
        }

        # Add all original CSV fields
        csv_fields = extract_all_csv_fields(r)
        row.update(csv_fields)

        # Add optimizer-computed fields at the end
        row["Score"] = f"{r.get('optimal_score', 0)}/100"

        if show_ai_explanations:
            row["AI Explanation"] = r.get("ai_explanation", r.get("reason", ""))
        else:
            row["Reason"] = r.get("reason", "Better fit in different window")
        excluded_orders.append(row)

    for c in cancel:
        # Start with key display fields
        row = {
            "Action": "❌ CANCEL",
            "externalOrderId": c["order_id"],
            "customerID": c["customer_name"],
            "address": c["delivery_address"],
            "numberOfUnits": c["units"]
        }

        # Add all original CSV fields
        csv_fields = extract_all_csv_fields(c)
        row.update(csv_fields)

        # Add optimizer-computed fields at the end
        row["Score"] = f"{c.get('optimal_score', 0)}/100"

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


def check_password() -> bool:
    """
    Password protection for the app.

    Returns:
        bool: True if user is authenticated, False otherwise
    """
    # Initialize authentication state
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    # If already authenticated, return True
    if st.session_state.authenticated:
        return True

    # Get the correct password from config
    correct_password = config.get_app_password()

    # Show login form
    st.title("🔒 The Buncher - Login")
    st.markdown("Please enter the password to access the route optimizer.")

    # Create a form for password entry
    with st.form("login_form"):
        password = st.text_input("Password", type="password", key="password_input")
        submit = st.form_submit_button("Login", type="primary", use_container_width=True)

        if submit:
            if password == correct_password:
                st.session_state.authenticated = True
                st.success("✅ Login successful! Redirecting...")
                st.rerun()
            else:
                st.error("❌ Incorrect password. Please try again.")
                return False

    # Show help text
    st.info("💡 Contact your administrator if you need access.")

    return False


def main():
    """Main Streamlit app."""
    st.set_page_config(page_title="The Buncher", page_icon="🚐", layout="wide")

    # Check password before showing app
    if not check_password():
        st.stop()

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

    # Service time configuration
    # Get default method from config
    default_method = config.get_default_service_time_method()
    default_index = 0 if default_method == "smart" else 1

    service_time_method = st.sidebar.radio(
        "Service Time Method",
        options=["Smart (Variable by Units)", "Fixed (Same for All Stops)"],
        index=default_index,
        help="Choose how to calculate service time at each stop"
    )

    if service_time_method == "Fixed (Same for All Stops)":
        fixed_service_time = st.sidebar.number_input(
            "Minutes per Stop",
            min_value=1,
            max_value=15,
            value=config.get_default_fixed_service_time(),
            step=1,
            help="Fixed service time applied to every stop"
        )
    else:
        # Smart service time - show info about the logic
        with st.sidebar.expander("ℹ️ How Smart Service Time Works"):
            st.markdown("""
            **Smart service time** calculates time based on order size using real operational data:

            **Formula**: `time = 1.6 + (units^1.3) × 0.045`

            **Examples**:
            - 2-10 units → 2-3 minutes *(small orders)*
            - 18-25 units → 3-5 minutes *(typical orders)*
            - 30-40 units → 5-7 minutes *(large orders)*

            **Why it works**:
            - Larger orders take disproportionately more time
            - Reflects actual unloading patterns
            - Power curve (^1.3) captures efficiency loss at scale
            - Capped at 7 minutes maximum

            **When to use**:
            - ✅ Variable order sizes (mix of small and large)
            - ✅ Want realistic time estimates
            - ✅ Typical grocery/retail delivery

            **When to use Fixed instead**:
            - Orders are all similar size
            - You have exact timing data
            - Simplicity preferred over accuracy
            """)
        fixed_service_time = None  # Not used in smart mode

    # File upload
    st.sidebar.markdown("---")
    st.sidebar.header("Upload Orders")
    uploaded_file = st.sidebar.file_uploader(
        "Choose a CSV file",
        type=["csv"],
        help="Upload CSV with order data"
    )

    # Order status filter (for new CSV format with orderStatus field)
    status_filter = st.sidebar.multiselect(
        "Filter by Order Status",
        options=["delivered", "cancelled"],
        default=["delivered", "cancelled"],
        help="Select which order statuses to include (used for audit purposes)"
    )

    # Random sample button
    if st.sidebar.button("🎲 Generate Random Sample", use_container_width=True, help="Generate random orders for testing", type="primary"):
        # Set flag to show parameter questions
        st.session_state.show_random_sample_questions = True
        st.rerun()

    # Handle random sample generation with interactive form
    if st.session_state.get('show_random_sample_questions', False):
        st.sidebar.markdown("---")
        st.sidebar.subheader("🎲 Random Sample Settings")

        with st.sidebar.form("random_sample_form"):
            st.markdown("**Configure your random test data:**")

            order_count = st.selectbox(
                "How many orders?",
                options=["10 orders", "25 orders", "50 orders", "100 orders"],
                index=1,
                help="Number of random orders to generate"
            )

            spread = st.selectbox(
                "Geographic spread?",
                options=[
                    "Tight cluster (5 mi radius)",
                    "Medium spread (10 mi radius)",
                    "Wide area (20 mi radius)"
                ],
                index=1,
                help="How spread out should addresses be?"
            )

            size_mix = st.selectbox(
                "Order size mix?",
                options=[
                    "Small orders (2-10 units)",
                    "Mixed sizes (2-40 units)",
                    "Large orders (20-50 units)"
                ],
                index=1,
                help="Distribution of order sizes"
            )

            early_pct = st.selectbox(
                "Early delivery allowed?",
                options=["None (0%)", "Some (25%)", "Half (50%)", "Most (75%)"],
                index=2,
                help="Percentage of orders allowing early delivery"
            )

            col1, col2 = st.columns(2)
            with col1:
                generate_btn = st.form_submit_button("✅ Generate", type="primary", use_container_width=True)
            with col2:
                cancel_btn = st.form_submit_button("❌ Cancel", use_container_width=True)

            if cancel_btn:
                st.session_state.show_random_sample_questions = False
                st.rerun()

            if generate_btn:
                # Generate random sample based on form inputs
                import random

                # Parse form values
                num_orders = int(order_count.split()[0])

                if "5 mi" in spread:
                    radius_miles = 5
                elif "20 mi" in spread:
                    radius_miles = 20
                else:
                    radius_miles = 10

                if "Small" in size_mix:
                    unit_min, unit_max = 2, 10
                elif "Large" in size_mix:
                    unit_min, unit_max = 20, 50
                else:
                    unit_min, unit_max = 2, 40

                if "None" in early_pct:
                    early_percentage = 0
                elif "Some" in early_pct:
                    early_percentage = 25
                elif "Most" in early_pct:
                    early_percentage = 75
                else:
                    early_percentage = 50

                # Generate random orders
                first_names = ["John", "Sarah", "Michael", "Emily", "David", "Jessica", "James", "Amanda",
                              "Robert", "Lisa", "William", "Jennifer", "Richard", "Michelle", "Joseph",
                              "Karen", "Thomas", "Nancy", "Charles", "Betty", "Daniel", "Linda", "Matthew",
                              "Elizabeth", "Anthony", "Barbara", "Mark", "Susan", "Donald", "Margaret"]

                last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
                             "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
                             "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Thompson", "White",
                             "Harris", "Clark", "Lewis", "Robinson", "Walker", "Young", "Hall"]

                # Detroit area streets and cities
                streets = ["Main St", "Oak Ave", "Maple Dr", "Washington Blvd", "Jefferson Ave", "Woodward Ave",
                          "Gratiot Ave", "Grand River Ave", "Michigan Ave", "Fort St", "Vernor Hwy", "Warren Ave",
                          "Joy Rd", "Plymouth Rd", "7 Mile Rd", "8 Mile Rd", "Livernois Ave", "Greenfield Rd",
                          "Southfield Rd", "Telegraph Rd", "Dequindre Rd", "Van Dyke Ave", "Schoenherr Rd"]

                cities = ["Detroit", "Dearborn", "Taylor", "Lincoln Park", "Allen Park", "Southgate", "Wyandotte",
                         "Riverview", "Trenton", "Flat Rock", "Romulus", "Westland", "Garden City", "Inkster",
                         "Redford", "Livonia", "Plymouth", "Canton", "Novi", "Farmington Hills"]

                zip_bases = [48120, 48124, 48126, 48146, 48180, 48183, 48184, 48186, 48192, 48195]

                # Generate CSV content (new format)
                import uuid
                from datetime import date, timedelta

                csv_content = "orderId,runId,externalOrderId,orderStatus,customerID,customerTag,address,deliveryDate,deliveryWindow,earlyEligible,priorRescheduleCount,numberOfUnits,fulfillmentLocation,fulfillmentGeo,fulfillmentLocationAddress,extendedCutOffTime\n"

                # Random base run ID
                base_run_id = random.randint(60000, 70000)

                # Fulfillment locations in Detroit area
                fulfillment_locations = [
                    ("Clinton Twp - 243", "Detroit", "40445 S. Groesbeck Hwy, Clinton Twp., MI 48036"),
                    ("Lincoln Park - 208", "Detroit", "3710 Dix Hwy Lincoln Park, MI 48146"),
                    ("Wixom - 122", "Detroit", "49900 Grand River Ave. Wixom, MI 48393"),
                    ("Waterford - 53", "Detroit", "4200 Highland Rd. Waterford, MI 48328"),
                    ("Belleville - 72", "Detroit", "9701 Belleville Rd Belleville, MI 48111")
                ]

                for i in range(num_orders):
                    # Generate UUIDs
                    order_uuid = str(uuid.uuid4())
                    customer_uuid = str(uuid.uuid4())

                    # Order IDs
                    external_order_id = 1290000000 + random.randint(1000, 999999)
                    run_id = f'"{base_run_id + random.randint(0, 3):,}"'  # Format with comma

                    # Order status (mix of delivered and cancelled)
                    order_status = random.choice(["delivered"] * 8 + ["cancelled"] * 2)  # 80% delivered

                    # Customer tag
                    customer_tag = random.choice(["new", "power", "unsatisfied"])

                    # Generate address
                    street_num = random.randint(100, 9999)
                    street = random.choice(streets)
                    city = random.choice(cities)
                    zip_code = random.choice(zip_bases) + random.randint(0, 20)
                    delivery_address = f"{street_num} {street} {zip_code} {city}"

                    # Delivery date (today)
                    delivery_date = date.today().strftime("%B %d, %Y")

                    # Delivery window (combined format)
                    window_start = "09:00 AM"
                    window_end = "11:00 AM"
                    delivery_window = f"{window_start} {window_end}"

                    # Early delivery allowed?
                    early_eligible = "true" if random.randint(1, 100) <= early_percentage else "false"

                    # Prior reschedule count (some orders have history)
                    prior_reschedule = "" if random.random() > 0.3 else str(random.randint(1, 3))

                    # Generate units
                    units = random.randint(unit_min, unit_max)

                    # Fulfillment location
                    fulfillment = random.choice(fulfillment_locations)
                    fulfillment_location = fulfillment[0]
                    fulfillment_geo = fulfillment[1]
                    fulfillment_address = fulfillment[2]

                    # Extended cutoff time (e.g., 2 hours before window)
                    cutoff_hour = 7  # 7 AM for 9 AM window
                    extended_cutoff = f"{delivery_date}, {cutoff_hour}:00 AM"

                    csv_content += f'{order_uuid},{run_id},{external_order_id},{order_status},{customer_uuid},{customer_tag},"{delivery_address}","{delivery_date}",{delivery_window},{early_eligible},{prior_reschedule},{units},{fulfillment_location},{fulfillment_geo},"{fulfillment_address}","{extended_cutoff}"\n'

                # Store generated CSV
                st.session_state.sample_file_content = csv_content.encode('utf-8')
                st.session_state.use_random_sample = True
                st.session_state.use_sample_file = False
                st.session_state.show_random_sample_questions = False

                st.success(f"✅ Generated {num_orders} random orders! Scroll down and click Run to optimize.")
                st.rerun()

    # Use random sample if generated
    if st.session_state.get('use_random_sample', False) and uploaded_file is None:
        from io import BytesIO
        uploaded_file = BytesIO(st.session_state.sample_file_content)
        uploaded_file.name = "random_sample.csv"

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

            # Get sandbox data and other parameters for tool calling
            results = st.session_state.optimization_results
            if results:
                sandbox_data = results['optimizations'].get('sandbox', {})
                valid_orders = results.get('valid_orders', [])
                time_matrix = results.get('time_matrix', [])
                vehicle_capacity = results.get('vehicle_capacity', 80)
                window_minutes = results.get('window_minutes', 120)
                service_times = results.get('service_times', [])
            else:
                sandbox_data = None
                valid_orders = None
                time_matrix = None
                vehicle_capacity = None
                window_minutes = None
                service_times = None

            with st.spinner("AI is thinking..."):
                response, updated_sandbox, tool_executions = chat_assistant.chat_with_assistant(
                    st.session_state.chat_messages,
                    st.session_state.optimization_context,
                    api_key,
                    sandbox_data=sandbox_data,
                    valid_orders=valid_orders,
                    time_matrix=time_matrix,
                    vehicle_capacity=vehicle_capacity,
                    window_minutes=window_minutes,
                    service_times=service_times
                )

            # If sandbox was updated, save it and recalculate metrics
            if updated_sandbox is not None and results:
                # Recalculate metrics for updated sandbox
                def calc_route_metrics(kept_orders, kept_nodes_data, service_times, time_matrix, vehicle_capacity):
                    total_units = sum(int(o["units"]) for o in kept_orders)
                    load_factor = (total_units / vehicle_capacity * 100) if vehicle_capacity > 0 else 0

                    drive_time = 0
                    if kept_nodes_data and len(kept_nodes_data) > 0:
                        try:
                            first_node = int(kept_nodes_data[0]["node"])
                            drive_time += int(time_matrix[0][first_node])
                            for i in range(len(kept_nodes_data) - 1):
                                from_node = int(kept_nodes_data[i]["node"])
                                to_node = int(kept_nodes_data[i + 1]["node"])
                                drive_time += int(time_matrix[from_node][to_node])
                            last_node = int(kept_nodes_data[-1]["node"])
                            drive_time += int(time_matrix[last_node][0])
                        except (TypeError, ValueError, IndexError):
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

                # Build kept nodes for metrics
                kept_nodes = []
                for order in updated_sandbox.get('keep', []):
                    kept_nodes.append({
                        'node': order['node'],
                        'sequence_index': order['sequence_index'],
                        'arrival_min': 0
                    })

                new_metrics = calc_route_metrics(
                    updated_sandbox.get('keep', []),
                    kept_nodes,
                    service_times,
                    time_matrix,
                    vehicle_capacity
                )

                # Update sandbox in session state
                st.session_state.optimization_results['optimizations']['sandbox'] = {
                    **updated_sandbox,
                    'cut_type': 'sandbox',
                    'strategy': 'Dispatcher Sandbox (AI-modified)',
                    'kept': kept_nodes,
                    'orders_kept': len(updated_sandbox.get('keep', [])),
                    **new_metrics
                }

                # Switch to Dispatcher Sandbox tab to show changes
                st.session_state.active_tab = 3

            # Add tool execution messages if any
            if tool_executions:
                for tool_msg in tool_executions:
                    st.session_state.chat_messages.append({"role": "assistant", "content": tool_msg})

            # Add AI response
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

                # Apply status filter if orderStatus field exists
                if csv_orders and "orderStatus" in csv_orders[0]:
                    original_count = len(csv_orders)
                    csv_orders = [o for o in csv_orders if o.get("orderStatus") in status_filter]
                    filtered_count = original_count - len(csv_orders)
                    if filtered_count > 0:
                        st.info(f"🔍 Filtered out {filtered_count} orders based on status (keeping: {', '.join(status_filter)})")

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
                # Build preview dataframe with all available fields
                preview_rows = []
                for o in orders:
                    row = {
                        "externalOrderId": o["order_id"],
                        "customerID": o["customer_name"],
                        "address": o["delivery_address"],
                        "numberOfUnits": o["units"],
                        "earlyEligible": "true" if o["early_delivery_ok"] else "false",
                        "deliveryWindow": f"{o['delivery_window_start'].strftime('%I:%M %p')} {o['delivery_window_end'].strftime('%I:%M %p')}"
                    }

                    # Add optional fields from new CSV format if present
                    optional_fields = ["orderId", "runId", "orderStatus", "customerTag",
                                     "deliveryDate", "priorRescheduleCount", "fulfillmentLocation",
                                     "fulfillmentGeo", "fulfillmentLocationAddress", "extendedCutOffTime"]

                    for field in optional_fields:
                        if field in o and o[field] is not None:
                            row[field] = o[field]

                    preview_rows.append(row)

                preview_df = pd.DataFrame(preview_rows)

                edited_df = st.data_editor(
                    preview_df,
                    num_rows="dynamic",
                    width="stretch",
                    key="order_editor",
                    height=400
                )

                st.caption(f"Showing all {len(orders)} orders with all available fields. You can edit values directly or add/remove rows.")

            # Extract depot address from fulfillmentLocationAddress (same for all orders)
            depot_address_from_csv = None
            if orders and 'fulfillmentLocationAddress' in orders[0]:
                depot_address_from_csv = orders[0]['fulfillmentLocationAddress']
                if depot_address_from_csv and depot_address_from_csv.strip():
                    depot_address = depot_address_from_csv.strip()
                    st.info(f"📍 Depot auto-detected from CSV: {depot_address}")

            # Detect unique delivery windows
            unique_windows = set()
            for order in orders:
                window_start = order['delivery_window_start']
                window_end = order['delivery_window_end']
                unique_windows.add((window_start, window_end))

            # Sort windows by start time
            sorted_windows = sorted(list(unique_windows), key=lambda w: w[0])

            # Create window labels
            from allocator import window_label
            window_labels_list = [window_label(start, end) for start, end in sorted_windows]

            st.markdown("---")
            st.subheader("🚐 Optimization Mode")

            # Mode selector
            mode = st.radio(
                "Choose optimization mode:",
                ["One window", "Full day"],
                index=1,  # Default to "Full day"
                help="One window: optimize a single delivery window. Full day: allocate orders across multiple windows."
            )

            # Validate orders
            valid_orders, errors = parser.validate_orders(orders)

            if errors:
                st.error(f"❌ Found {len(errors)} validation errors:")
                for error in errors:
                    st.write(f"- {error}")

            # Mode-specific configuration
            selected_window = None
            window_capacities = {}

            if mode == "One window":
                st.markdown("### 📅 Select Window")
                selected_window_label = st.selectbox(
                    "Choose delivery window to optimize:",
                    window_labels_list,
                    help="Select the delivery window you want to optimize"
                )

                # Find the corresponding window tuple
                selected_window_index = window_labels_list.index(selected_window_label)
                selected_window = sorted_windows[selected_window_index]

                # Show window summary
                window_orders = [o for o in valid_orders if
                               o['delivery_window_start'] == selected_window[0] and
                               o['delivery_window_end'] == selected_window[1]]
                total_units = sum(o['units'] for o in window_orders)

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Orders in window", len(window_orders))
                with col2:
                    st.metric("Total units", total_units)
                with col3:
                    st.metric("Vehicle capacity", vehicle_capacity)

            else:  # Full day mode
                # Show window labels in header
                window_summary = " | ".join([f"**{label}**" for label in window_labels_list])
                st.markdown(f"### 🚛 Configure Capacity Per Window\n{window_summary}")

                # Build capacity configuration table with editable times
                from datetime import datetime, time as dt_time
                capacity_data = []
                window_times_map = {}  # Store original window times for matching orders later

                for i, (win_start, win_end) in enumerate(sorted_windows):
                    label = window_labels_list[i]
                    window_orders = [o for o in valid_orders if
                                   o['delivery_window_start'] == win_start and
                                   o['delivery_window_end'] == win_end]
                    total_units = sum(o['units'] for o in window_orders)

                    # Calculate window length in minutes
                    start_minutes = win_start.hour * 60 + win_start.minute
                    end_minutes = win_end.hour * 60 + win_end.minute
                    window_length = end_minutes - start_minutes

                    utilization = round((total_units / 300) * 100, 1) if 300 > 0 else 0
                    status = "🟢" if total_units <= 300 else "🔴"

                    capacity_data.append({
                        "Window": label,  # Keep for internal use but hide in display
                        "Start": win_start,  # Keep as time object for TimeColumn
                        "End": win_end,  # Keep as time object for TimeColumn
                        "Length (min)": window_length,
                        "Orders": len(window_orders),
                        "Units": total_units,
                        "Capacity": 300,  # Default capacity
                        "Utilization %": utilization,
                        "Status": status
                    })

                    # Store mapping for later
                    window_times_map[label] = (win_start, win_end)

                # Create editable dataframe
                capacity_df = pd.DataFrame(capacity_data)

                edited_df = st.data_editor(
                    capacity_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Window": None,  # Hide this column
                        "Start": st.column_config.TimeColumn(
                            "Start",
                            format="hh:mm a",
                            width="small",
                            help="Edit window start time"
                        ),
                        "End": st.column_config.TimeColumn(
                            "End",
                            format="hh:mm a",
                            width="small",
                            help="Edit window end time"
                        ),
                        "Length (min)": st.column_config.NumberColumn(
                            "Length (min)",
                            disabled=True,
                            width="small",
                            help="Calculated from Start/End"
                        ),
                        "Orders": st.column_config.NumberColumn(
                            "Orders",
                            disabled=True,
                            width="small"
                        ),
                        "Units": st.column_config.NumberColumn(
                            "Units",
                            disabled=True,
                            width="small",
                            help="Total units"
                        ),
                        "Capacity": st.column_config.NumberColumn(
                            "Capacity",
                            min_value=0,
                            max_value=1000,
                            step=10,
                            width="small",
                            help="Edit vehicle capacity (units)"
                        ),
                        "Utilization %": st.column_config.NumberColumn(
                            "Util %",
                            disabled=True,
                            width="small",
                            help="Capacity utilization percentage"
                        ),
                        "Status": st.column_config.TextColumn(
                            "Status",
                            disabled=True,
                            width="small",
                            help="🟢 = Sufficient | 🔴 = Over capacity"
                        )
                    },
                    key="capacity_editor"
                )

                # Update window_capacities dict and recalculate based on edits
                updated_windows = []  # Store updated window times
                for idx, row in edited_df.iterrows():
                    label = row["Window"]
                    capacity = row["Capacity"]
                    units = row["Units"]
                    window_capacities[label] = capacity

                    # Parse edited times and calculate length
                    try:
                        if isinstance(row["Start"], str):
                            start_time = datetime.strptime(row["Start"], "%I:%M %p").time()
                        else:
                            start_time = row["Start"]

                        if isinstance(row["End"], str):
                            end_time = datetime.strptime(row["End"], "%I:%M %p").time()
                        else:
                            end_time = row["End"]

                        # Calculate window length
                        start_minutes = start_time.hour * 60 + start_time.minute
                        end_minutes = end_time.hour * 60 + end_time.minute
                        window_length = end_minutes - start_minutes

                        # Update the length column
                        edited_df.at[idx, "Length (min)"] = window_length

                        # Store updated window times
                        updated_windows.append((label, start_time, end_time))

                    except (ValueError, AttributeError):
                        # If parsing fails, use original times
                        orig_start, orig_end = window_times_map[label]
                        updated_windows.append((label, orig_start, orig_end))

                    # Recalculate utilization and status based on edited capacity
                    utilization = round((units / capacity) * 100, 1) if capacity > 0 else 0
                    status = "🟢" if units <= capacity else "🔴"
                    edited_df.at[idx, "Utilization %"] = utilization
                    edited_df.at[idx, "Status"] = status

                # Store updated window times in session state for use in optimization
                st.session_state['updated_window_times'] = {label: (start, end) for label, start, end in updated_windows}

                # Show summary of capacity issues
                insufficient_windows = edited_df[edited_df["Units"] > edited_df["Capacity"]]
                if not insufficient_windows.empty:
                    total_overflow = (insufficient_windows["Units"] - insufficient_windows["Capacity"]).sum()
                    st.warning(f"⚠️ {len(insufficient_windows)} window(s) with insufficient capacity. Total overflow: {int(total_overflow)} units will need reallocation.")
                else:
                    st.success("✅ All windows have sufficient capacity")

                # Allocation strategy options
                st.markdown("### ⚙️ Allocation Strategy")
                honor_priority = st.checkbox(
                    "Honor priority customers (power/vip stay in original window)",
                    value=False,
                    help="When checked: Priority customers locked to original window (Pass 1). Uncheck for 'truly max orders' view that ignores customer priority."
                )

                if not honor_priority:
                    st.info("🔓 Priority customer lock disabled - optimizing for maximum orders across all windows regardless of customer tags")

                # Overflow thresholds
                col1, col2 = st.columns(2)
                with col1:
                    cancel_threshold = st.number_input(
                        "Auto-cancel threshold (units)",
                        min_value=0,
                        value=75,
                        step=5,
                        help="Orders over this size automatically cancelled if they don't fit"
                    )
                with col2:
                    reschedule_threshold = st.number_input(
                        "Auto-reschedule threshold (units)",
                        min_value=0,
                        value=40,
                        step=5,
                        help="Orders over this size automatically rescheduled if they don't fit"
                    )

                st.caption(f"💡 Strategy: Orders >{cancel_threshold} units → CANCEL, >{reschedule_threshold} units → RESCHEDULE, else use reschedule_count")

            if valid_orders and run_optimization:
                # Progress updates (no visual bar, just status messages)
                progress_text = st.empty()

                def update_progress(percent, step_name):
                    """Update progress status message"""
                    progress_text.markdown(f"🚐 **{step_name}** ({percent}%)")

                # MODE-SPECIFIC OPTIMIZATION
                if mode == "One window":
                    # Filter orders to selected window
                    window_orders = [o for o in valid_orders if
                                   o['delivery_window_start'] == selected_window[0] and
                                   o['delivery_window_end'] == selected_window[1]]

                    if not window_orders:
                        st.error(f"❌ No orders found for selected window")
                    else:
                        # Compute window duration from selected window times
                        from allocator import window_duration_minutes
                        window_minutes = window_duration_minutes(selected_window[0], selected_window[1])

                        st.info(f"🎯 Optimizing {len(window_orders)} orders for window {window_labels_list[sorted_windows.index(selected_window)]} ({window_minutes} minutes)")

                        # Use window_orders for optimization (existing V1 flow)
                        orders_to_optimize = window_orders

                        # Build address list: depot + order addresses
                        update_progress(5, "Preparing addresses...")
                        addresses = [depot_address] + [o["delivery_address"] for o in orders_to_optimize]

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
                        demands = [0] + [o["units"] for o in orders_to_optimize]

                        # Build service times array: depot has 0 service time
                        # Service time is unloading time per stop
                        if service_time_method == "Fixed (Same for All Stops)":
                            # Fixed service time for all stops
                            service_times = [0] + [fixed_service_time for o in orders_to_optimize]
                        else:
                            # Smart service time: variable by units (2-7 minutes, non-linear with units)
                            service_times = [0] + [optimizer.service_time_for_units(o["units"]) for o in orders_to_optimize]

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

                        # Show service time method info
                        if service_time_method == "Fixed (Same for All Stops)":
                            st.info(f"⏱️ Using **Fixed Service Time**: {fixed_service_time} minutes per stop")
                        else:
                            st.info("⏱️ Using **Smart Service Time**: Variable by order size (2-7 min based on units)")

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

                        # Initialize active tab in session state (defaults to Cut 1)
                        if "active_tab" not in st.session_state:
                            st.session_state.active_tab = 0

                        # Show 2-cut comparison summary
                        # Create tabs for four optimization cuts with order counts in titles
                        max_orders_count = optimizations['max_orders']['orders_kept']
                        shortest_orders_count = optimizations['shortest']['orders_kept']
                        density_orders_count = optimizations['high_density']['orders_kept']
                        sandbox_orders_count = optimizations['sandbox']['orders_kept']

                        # Tab selector that persists in session state
                        tab_options = [
                            f"✅ Cut 1: Max Orders ({max_orders_count} Orders) - RECOMMENDED",
                            f"⚡ Cut 2: Shortest Route ({shortest_orders_count} Orders)",
                            f"🎯 Cut 3: High Density ({density_orders_count} Orders)",
                            f"✏️ Cut 4: Dispatcher Sandbox ({sandbox_orders_count} Orders)"
                        ]

                        selected_tab = st.selectbox(
                            "Select View:",
                            options=tab_options,
                            index=st.session_state.active_tab,
                            key="tab_selector",
                            label_visibility="collapsed"
                        )

                        # Update active tab in session state
                        st.session_state.active_tab = tab_options.index(selected_tab)

                        st.markdown("---")

                        # TAB 1: MAX ORDERS (RECOMMENDED - default view)
                        if st.session_state.active_tab == 0:
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
                        elif st.session_state.active_tab == 1:
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
                        elif st.session_state.active_tab == 2:
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
                        elif st.session_state.active_tab == 3:
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
                                    # Stay on Dispatcher Sandbox tab
                                    st.session_state.active_tab = 3
                                    st.success(f"✅ Loaded {starting_cut} into Sandbox! Scroll down to see updated map and make edits.")
                                    st.rerun()

                            st.markdown("---")

                            opt = optimizations['sandbox']

                            # Show current metrics (with safety checks) - matching other cuts
                            st.subheader("📊 Summary")
                            try:
                                total_units = opt.get('total_units', 0)
                                load_factor = opt.get('load_factor', 0)
                                drive_time = opt.get('drive_time', 0)
                                service_time = opt.get('service_time', 0)
                                total_time = opt.get('total_time', 0)
                                route_miles = opt.get('route_miles', 0)
                                orders_kept = opt.get('orders_kept', 0)
                                deliveries_per_hour = (orders_kept / (total_time / 60)) if total_time > 0 else 0

                                # Calculate dead leg (return time from last stop to fulfillment)
                                dead_leg_time = 0
                                if opt.get('kept') and len(opt['kept']) > 0:
                                    try:
                                        last_node = int(opt['kept'][-1]['node'])
                                        dead_leg_time = int(time_matrix[last_node][0])
                                    except (ValueError, TypeError, KeyError, IndexError):
                                        dead_leg_time = 0

                                # First row of KPIs
                                col1, col2, col3, col4 = st.columns(4)
                                with col1:
                                    st.metric("KEEP Orders", orders_kept)
                                with col2:
                                    capacity_pct = load_factor
                                    st.metric("Capacity Used", f"{total_units}/{vehicle_capacity}", f"{capacity_pct:.1f}%")
                                with col3:
                                    st.metric("Total Route Time", format_time_minutes(total_time),
                                             f"Drive: {format_time_minutes(drive_time)}, Service: {format_time_minutes(service_time)}")
                                with col4:
                                    total_orders = orders_kept + len(opt.get('early', [])) + len(opt.get('reschedule', [])) + len(opt.get('cancel', []))
                                    st.metric("Total Orders", total_orders)

                                # Second row of KPIs
                                col5, col6, col7, col8 = st.columns(4)
                                with col5:
                                    st.metric("Load Factor", f"{load_factor:.1f}%")
                                with col6:
                                    st.metric("Route Miles", f"{route_miles:.1f}")
                                with col7:
                                    st.metric("Deliveries/Hour", f"{deliveries_per_hour:.1f}")
                                with col8:
                                    st.metric("Dead Leg", f"{dead_leg_time} min", help="Time from last delivery back to fulfillment location")
                            except Exception as e:
                                st.error(f"Error displaying metrics: {e}")

                            st.markdown("---")

                            st.subheader("📝 Edit Orders")

                            # Combine all orders into a single editable dataframe
                            all_orders_for_edit = []

                            # KEEP orders
                            for order in opt['keep']:
                                all_orders_for_edit.append({
                                    'externalOrderId': order['order_id'],
                                    'customerID': order['customer_name'],
                                    'numberOfUnits': order['units'],
                                    'Status': 'KEEP',
                                    'Sequence': order.get('sequence_index', 0) + 1,
                                    'address': order['delivery_address']
                                })

                            # EARLY orders
                            for order in opt['early']:
                                all_orders_for_edit.append({
                                    'externalOrderId': order['order_id'],
                                    'customerID': order['customer_name'],
                                    'numberOfUnits': order['units'],
                                    'Status': 'EARLY',
                                    'Sequence': None,
                                    'address': order['delivery_address']
                                })

                            # RESCHEDULE orders
                            for order in opt['reschedule']:
                                all_orders_for_edit.append({
                                    'externalOrderId': order['order_id'],
                                    'customerID': order['customer_name'],
                                    'numberOfUnits': order['units'],
                                    'Status': 'RESCHEDULE',
                                    'Sequence': None,
                                    'address': order['delivery_address']
                                })

                            # CANCEL orders
                            for order in opt['cancel']:
                                all_orders_for_edit.append({
                                    'externalOrderId': order['order_id'],
                                    'customerID': order['customer_name'],
                                    'numberOfUnits': order['units'],
                                    'Status': 'CANCEL',
                                    'Sequence': None,
                                    'address': order['delivery_address']
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
                                disabled=["externalOrderId", "customerID", "numberOfUnits", "address"],
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
                                    order_id = row['externalOrderId']
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
                                        'customer_name': row['customerID'],
                                        'delivery_address': row['address'],
                                        'units': row['numberOfUnits'],
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

                                # Stay on Dispatcher Sandbox tab
                                st.session_state.active_tab = 3
                                st.success(f"✅ Recalculated! Route now has {len(new_keep)} orders. Scroll down to see updated map.")
                                st.rerun()

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
                                    if map_chart:
                                        st_folium(map_chart, width=1200, height=600)

                                        # Map legend
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
                                else:
                                    st.warning("⚠️ Map data not available. Please load a cut using the button above.")
                            except Exception as e:
                                st.warning(f"❌ Error creating map: {str(e)}")
                                st.info("💡 Try loading a different cut or re-running the optimization.")

                            # Display route sequence table with service times
                            st.markdown("---")
                            keep_orders = opt.get('keep', [])
                            if keep_orders:
                                st.subheader("🗺️ Route Sequence")

                                # Build route sequence string
                                route_parts = ["Fulfillment Location"]
                                for k in sorted(keep_orders, key=lambda x: x.get("sequence_index", 0)):
                                    route_parts.append(f"Order {k['order_id']}")
                                route_parts.append("Fulfillment Location")
                                st.write(" → ".join(route_parts))

                                st.markdown("---")

                                # Build detailed table
                                route_table_data = []
                                for k in sorted(keep_orders, key=lambda x: x.get("sequence_index", 0)):
                                    try:
                                        node = int(k.get('node', 0))
                                        service_time = int(service_times[node]) if service_times and node < len(service_times) else 0

                                        row = {
                                            "Seq": int(k.get("sequence_index", 0)) + 1,
                                            "externalOrderId": str(k.get("order_id", "")),
                                            "customerID": str(k.get("customer_name", "")),
                                            "address": str(k.get("delivery_address", "")),
                                            "numberOfUnits": int(k.get("units", 0))
                                        }

                                        # Add all original CSV fields
                                        csv_fields = extract_all_csv_fields(k)
                                        row.update(csv_fields)

                                        # Add service time at the end
                                        row["Est. Service Time"] = f"{service_time} min"

                                        route_table_data.append(row)
                                    except (ValueError, TypeError, KeyError, IndexError):
                                        continue

                                if route_table_data:
                                    route_df = pd.DataFrame(route_table_data)
                                    st.dataframe(route_df, use_container_width=True)
                                else:
                                    st.info("No route data available")
                            else:
                                st.info("No orders in route. Load a cut or add orders to KEEP status.")

                elif mode == "Full day":
                    # FULL DAY MODE: Allocate orders across windows, then optimize each window
                    st.markdown("## 🌅 Full Day Optimization")

                    # Import allocator
                    from allocator import allocate_orders_across_windows, window_label

                    # Use updated window times if available (from editable table)
                    if 'updated_window_times' in st.session_state:
                        # Build windows list from updated times
                        allocation_windows = []
                        for label in window_labels_list:
                            if label in st.session_state['updated_window_times']:
                                start_time, end_time = st.session_state['updated_window_times'][label]
                                allocation_windows.append((start_time, end_time))
                            else:
                                # Fallback to original window
                                idx = window_labels_list.index(label)
                                allocation_windows.append(sorted_windows[idx])
                    else:
                        allocation_windows = sorted_windows

                    # Run allocator
                    if honor_priority:
                        st.info("📊 Running cross-window allocation (honoring priority customers)...")
                    else:
                        st.info("📊 Running cross-window allocation (max orders mode - priority customers can be moved)...")

                    allocation_result = allocate_orders_across_windows(
                        orders=valid_orders,
                        windows=allocation_windows,
                        window_capacities=window_capacities,
                        honor_priority=honor_priority,
                        cancel_threshold=cancel_threshold,
                        reschedule_threshold=reschedule_threshold
                    )

                    # Show global allocation summary
                    st.markdown("### 📈 Allocation Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Kept in window", len(allocation_result.kept_in_window))
                    with col2:
                        st.metric("Moved early", len(allocation_result.moved_early))
                    with col3:
                        st.metric("Reschedule", len(allocation_result.reschedule))
                    with col4:
                        st.metric("Cancel recommended", len(allocation_result.cancel))

                    st.markdown("---")

                    # Now optimize each window separately
                    st.markdown("### 🚛 Per-Window Optimization Results")

                    window_results = {}

                    for i, (win_start, win_end) in enumerate(allocation_windows):
                        win_label = window_labels_list[i]
                        win_orders = allocation_result.orders_by_window.get(win_label, [])

                        if not win_orders:
                            with st.expander(f"**{win_label}** — No orders assigned", expanded=False):
                                st.info("No orders were assigned to this window after allocation.")
                            continue

                        with st.expander(f"**{win_label}** — {len(win_orders)} orders", expanded=True):
                            # Compute window duration (using edited times if available)
                            from allocator import window_duration_minutes
                            win_duration = window_duration_minutes(win_start, win_end)

                            st.info(f"Optimizing {len(win_orders)} orders ({sum(o['units'] for o in win_orders)} units) in {win_duration}-minute window")

                            # Build addresses for this window
                            win_addresses = [depot_address] + [o["delivery_address"] for o in win_orders]

                            # Geocode
                            win_geocoded = geocoder.geocode_addresses(win_addresses)

                            # Build time matrix
                            win_time_matrix = geocoder.build_time_matrix(win_addresses)

                            # Build demands
                            win_demands = [0] + [o["units"] for o in win_orders]

                            # Build service times
                            if service_time_method == "Fixed (Same for All Stops)":
                                win_service_times = [0] + [fixed_service_time for _ in win_orders]
                            else:
                                win_service_times = [0] + [optimizer.service_time_for_units(o["units"]) for o in win_orders]

                            # Get window capacity
                            win_capacity = window_capacities[win_label]

                            # Run optimizer (use high drop_penalty to maximize orders kept)
                            kept, dropped = optimizer.solve_route(
                                time_matrix=win_time_matrix,
                                demands=win_demands,
                                vehicle_capacity=win_capacity,
                                max_route_time=win_duration,
                                service_times=win_service_times,
                                drop_penalty=10000  # High penalty - maximize orders
                            )

                            # Classify orders
                            keep, early, reschedule, cancel = disposition.classify_orders(
                                all_orders=win_orders,
                                kept=kept,
                                dropped_nodes=dropped,
                                time_matrix=win_time_matrix
                            )

                            # Store results (including geocoded data for global map)
                            window_results[win_label] = {
                                'keep': keep,
                                'early': early,
                                'reschedule': reschedule,
                                'cancel': cancel,
                                'orders_kept': len(keep),
                                'total_units': sum(o['units'] for o in keep),
                                'geocoded': win_geocoded,  # Store for global map
                                'addresses': win_addresses  # Store for reference
                            }

                            # Display results
                            st.markdown(f"**Route Summary**: {len(keep)} orders, {sum(o['units'] for o in keep)} units")

                            # Show KEEP orders
                            if keep:
                                st.markdown("#### ✅ KEEP (On Route)")
                                keep_data = []
                                for k in sorted(keep, key=lambda x: x["sequence_index"]):
                                    row = {
                                        "Seq": k["sequence_index"] + 1,
                                        "externalOrderId": k["order_id"],
                                        "customerID": k["customer_name"],
                                        "address": k["delivery_address"],
                                        "numberOfUnits": k["units"]
                                    }
                                    csv_fields = extract_all_csv_fields(k)
                                    row.update(csv_fields)
                                    keep_data.append(row)
                                keep_df = pd.DataFrame(keep_data)
                                st.dataframe(keep_df, use_container_width=True)

                            # Show EARLY orders
                            if early:
                                st.markdown("#### ⏰ EARLY DELIVERY")
                                early_data = []
                                for e in early:
                                    row = {
                                        "externalOrderId": e["order_id"],
                                        "customerID": e["customer_name"],
                                        "address": e["delivery_address"],
                                        "numberOfUnits": e["units"]
                                    }
                                    csv_fields = extract_all_csv_fields(e)
                                    row.update(csv_fields)
                                    early_data.append(row)
                                early_df = pd.DataFrame(early_data)
                                st.dataframe(early_df, use_container_width=True)

                            # Show RESCHEDULE orders
                            if reschedule:
                                st.markdown("#### 📅 RESCHEDULE")
                                resc_data = []
                                for r in reschedule:
                                    row = {
                                        "externalOrderId": r["order_id"],
                                        "customerID": r["customer_name"],
                                        "address": r["delivery_address"],
                                        "numberOfUnits": r["units"]
                                    }
                                    csv_fields = extract_all_csv_fields(r)
                                    row.update(csv_fields)
                                    resc_data.append(row)
                                resc_df = pd.DataFrame(resc_data)
                                st.dataframe(resc_df, use_container_width=True)

                            # Show CANCEL orders
                            if cancel:
                                st.markdown("#### ❌ CANCEL")
                                cancel_data = []
                                for c in cancel:
                                    row = {
                                        "externalOrderId": c["order_id"],
                                        "customerID": c["customer_name"],
                                        "address": c["delivery_address"],
                                        "numberOfUnits": c["units"]
                                    }
                                    csv_fields = extract_all_csv_fields(c)
                                    row.update(csv_fields)
                                    cancel_data.append(row)
                                cancel_df = pd.DataFrame(cancel_data)
                                st.dataframe(cancel_df, use_container_width=True)

                    st.markdown("---")

                    # Global Summary Map
                    st.markdown("### 🗺️ Global Route Summary Map")
                    st.markdown("All routes displayed together with color-coded windows")

                    # Debug: Show number of window results
                    st.info(f"🔍 Debug: Found {len(window_results)} window(s) with results")

                    # Wrap entire map section to prevent auto-refresh on errors
                    try:
                        import folium
                        from folium import plugins

                        # Get depot coordinates from first window's geocoded data
                        if not window_results:
                            st.warning("No routes to display on map - window_results is empty")
                        else:
                            st.info(f"✅ Processing {len(window_results)} windows for map visualization")
                            first_window = list(window_results.values())[0]

                            # Debug: Check if geocoded data exists
                            if 'geocoded' not in first_window:
                                st.error("❌ No 'geocoded' key in window results")
                            else:
                                st.success(f"✅ Found geocoded data with {len(first_window['geocoded'])} entries")

                            depot_geo = first_window['geocoded'][0] if first_window.get('geocoded') else None

                            if depot_geo is None:
                                st.warning("⚠️ Depot location is None. Cannot display map.")
                            elif depot_geo.get("lat") is None:
                                st.warning(f"⚠️ Depot location has no latitude. Data: {depot_geo}")
                            else:
                                st.success(f"✅ Depot located at ({depot_geo['lat']}, {depot_geo['lng']})")
                                # Define distinct colors for each window
                                route_colors = [
                                    '#FF0000',  # Red
                                    '#0000FF',  # Blue
                                    '#00FF00',  # Green
                                    '#FF00FF',  # Magenta
                                    '#FFA500',  # Orange
                                    '#800080',  # Purple
                                    '#00FFFF',  # Cyan
                                    '#FFD700',  # Gold
                                ]

                                # Calculate map center from all routes
                                all_lats = [depot_geo["lat"]]
                                all_lons = [depot_geo["lng"]]

                                for win_label, result in window_results.items():
                                    win_geocoded = result.get('geocoded', [])
                                    for order in result['keep']:
                                        if 'node' in order:
                                            node_idx = order['node']
                                            if 0 <= node_idx < len(win_geocoded):
                                                geo = win_geocoded[node_idx]
                                                if geo.get("lat") is not None:
                                                    all_lats.append(geo["lat"])
                                                    all_lons.append(geo["lng"])

                                if len(all_lats) > 1:
                                    center_lat = sum(all_lats) / len(all_lats)
                                    center_lon = sum(all_lons) / len(all_lons)

                                    # Create map
                                    global_map = folium.Map(
                                        location=[center_lat, center_lon],
                                        zoom_start=11,
                                        tiles='OpenStreetMap'
                                    )

                                    # Add depot marker
                                    folium.Marker(
                                        location=[depot_geo["lat"], depot_geo["lng"]],
                                        popup=f"<b>Depot</b><br>{depot_address}",
                                        icon=folium.Icon(color='blue', icon='home', prefix='fa'),
                                        tooltip="Fulfillment Location"
                                    ).add_to(global_map)

                                    # Plot each window's route with different color
                                    for idx, (win_label, result) in enumerate(window_results.items()):
                                        color = route_colors[idx % len(route_colors)]
                                        keep_orders = result['keep']
                                        win_geocoded_data = result.get('geocoded', [])

                                        if keep_orders and win_geocoded_data:
                                            # Sort by sequence
                                            sorted_orders = sorted(keep_orders, key=lambda x: x.get('sequence_index', 0))

                                            # Add markers for each stop
                                            for i, order in enumerate(sorted_orders):
                                                if 'node' in order:
                                                    node_idx = order['node']
                                                    if 0 <= node_idx < len(win_geocoded_data):
                                                        geo = win_geocoded_data[node_idx]
                                                        if geo.get("lat") is not None:
                                                            popup_html = f"""
                                                            <b>Window: {win_label}</b><br>
                                                            Stop #{i+1}<br>
                                                            Order: {order.get('order_id', 'N/A')}<br>
                                                            Customer: {order.get('customer_name', 'N/A')}<br>
                                                            Units: {order.get('units', 'N/A')}
                                                            """

                                                            folium.CircleMarker(
                                                                location=[geo["lat"], geo["lng"]],
                                                                radius=8,
                                                                popup=folium.Popup(popup_html, max_width=300),
                                                                color=color,
                                                                fill=True,
                                                                fillColor=color,
                                                                fillOpacity=0.7,
                                                                weight=2,
                                                                tooltip=f"{win_label}: Stop {i+1}"
                                                            ).add_to(global_map)

                                            # Draw route lines connecting stops
                                            route_coords = [[depot_geo["lat"], depot_geo["lng"]]]  # Start at depot
                                            for order in sorted_orders:
                                                if 'node' in order:
                                                    node_idx = order['node']
                                                    if 0 <= node_idx < len(win_geocoded_data):
                                                        geo = win_geocoded_data[node_idx]
                                                        if geo.get("lat") is not None:
                                                            route_coords.append([geo["lat"], geo["lng"]])
                                            route_coords.append([depot_geo["lat"], depot_geo["lng"]])  # Return to depot

                                            # Add route line
                                            folium.PolyLine(
                                                locations=route_coords,
                                                color=color,
                                                weight=3,
                                                opacity=0.7,
                                                popup=f"Route: {win_label}",
                                                tooltip=f"{win_label} - {len(sorted_orders)} stops"
                                            ).add_to(global_map)

                                    # Add legend
                                    legend_html = '<div style="position: fixed; bottom: 50px; left: 50px; z-index: 1000; background-color: white; padding: 10px; border: 2px solid grey; border-radius: 5px;">'
                                    legend_html += '<h4 style="margin: 0 0 10px 0;">Routes by Window</h4>'
                                    for idx, win_label in enumerate(window_results.keys()):
                                        color = route_colors[idx % len(route_colors)]
                                        legend_html += f'<p style="margin: 5px;"><span style="background-color: {color}; width: 20px; height: 10px; display: inline-block; margin-right: 5px;"></span>{win_label}</p>'
                                    legend_html += '</div>'
                                    global_map.get_root().html.add_child(folium.Element(legend_html))

                                    # Display map
                                    st_folium(global_map, width=None, height=600)

                                    st.caption("🎨 Each color represents a different delivery window route")
                                else:
                                    st.info("No route data available for map visualization")
                    except Exception as e:
                        import traceback
                        st.error(f"❌ Error creating global map: {str(e)}")
                        with st.expander("🐛 Debug: Full error details"):
                            st.code(traceback.format_exc())
                        st.info("💡 Map visualization requires valid geocoded addresses")

                    # Ensure this section completes without issues
                    st.success("✅ Map section completed")

                    st.markdown("---")

                    # Show global allocation tables
                    st.markdown("### 📊 Global Allocation Details")

                    # Orders moved early
                    if allocation_result.moved_early:
                        with st.expander("🟢 Orders Moved Early", expanded=True):
                            moved_data = []
                            for a in allocation_result.moved_early:
                                row = {
                                    "externalOrderId": a.order["order_id"],
                                    "customerID": a.order["customer_name"],
                                    "address": a.order["delivery_address"],
                                    "numberOfUnits": a.order["units"]
                                }
                                csv_fields = extract_all_csv_fields(a.order)
                                row.update(csv_fields)
                                row["From Window"] = a.original_window
                                row["To Window"] = a.assigned_window
                                row["Reason"] = a.reason
                                moved_data.append(row)
                            moved_df = pd.DataFrame(moved_data)
                            st.dataframe(moved_df, use_container_width=True)

                    # Orders recommended for reschedule
                    if allocation_result.reschedule:
                        with st.expander("🟡 Orders Recommended for Reschedule", expanded=True):
                            resc_data = []
                            for a in allocation_result.reschedule:
                                row = {
                                    "externalOrderId": a.order["order_id"],
                                    "customerID": a.order["customer_name"],
                                    "address": a.order["delivery_address"],
                                    "numberOfUnits": a.order["units"]
                                }
                                csv_fields = extract_all_csv_fields(a.order)
                                row.update(csv_fields)
                                row["Original Window"] = a.original_window
                                row["Reschedule Count"] = a.order.get("priorRescheduleCount", 0) or 0
                                row["Reason"] = a.reason
                                resc_data.append(row)
                            resc_df = pd.DataFrame(resc_data)
                            st.dataframe(resc_df, use_container_width=True)

                    # Orders recommended for cancel
                    if allocation_result.cancel:
                        with st.expander("🔴 Orders Recommended for Cancel", expanded=True):
                            cancel_data = []
                            for a in allocation_result.cancel:
                                row = {
                                    "externalOrderId": a.order["order_id"],
                                    "customerID": a.order["customer_name"],
                                    "address": a.order["delivery_address"],
                                    "numberOfUnits": a.order["units"]
                                }
                                csv_fields = extract_all_csv_fields(a.order)
                                row.update(csv_fields)
                                row["Original Window"] = a.original_window
                                row["Reschedule Count"] = a.order.get("priorRescheduleCount", 0) or 0
                                row["Reason"] = a.reason
                                cancel_data.append(row)
                            cancel_df = pd.DataFrame(cancel_data)
                            st.dataframe(cancel_df, use_container_width=True)

                    # AI VALIDATION FOR FULL DAY MODE
                    st.markdown("---")
                    st.markdown("### 🤖 AI Validation & Analysis")

                    # Check if AI is available
                    anthropic_key = config.get_anthropic_api_key()
                    ai_available = anthropic_key and anthropic_key != "YOUR_ANTHROPIC_API_KEY_HERE"

                    if ai_available and run_with_ai:
                        with st.spinner("🤖 AI analyzing full day allocation and routes..."):
                            try:
                                # Build comprehensive summary for AI
                                validation_context = f"""
FULL DAY OPTIMIZATION ANALYSIS

Total Orders: {len(valid_orders)}
Windows: {len(sorted_windows)}

ALLOCATION SUMMARY:
- Kept in original window: {len(allocation_result.kept_in_window)}
- Moved to earlier window: {len(allocation_result.moved_early)}
- Recommended for reschedule: {len(allocation_result.reschedule)}
- Recommended for cancel: {len(allocation_result.cancel)}

PRIORITY CUSTOMER HANDLING:
"""
                                # Check priority customer handling
                                priority_orders = [o for o in valid_orders if o.get('customerTag', '').lower() in ['power', 'vip']]
                                validation_context += f"- Total priority customers (power/vip): {len(priority_orders)}\n"
                                priority_moved = [a for a in allocation_result.moved_early if a.order.get('customerTag', '').lower() in ['power', 'vip']]
                                if priority_moved:
                                    validation_context += f"- ⚠️ WARNING: {len(priority_moved)} priority customers were moved early (should not happen)\n"
                                else:
                                    validation_context += f"- ✅ All priority customers kept in original windows\n"

                                validation_context += "\nEARLY MOVES VALIDATION:\n"
                                if allocation_result.moved_early:
                                    validation_context += f"- {len(allocation_result.moved_early)} orders moved early\n"
                                    for move in allocation_result.moved_early[:5]:  # Sample first 5
                                        validation_context += f"  • Order {move.order['order_id']}: {move.order['units']} units, {move.original_window} → {move.assigned_window}\n"

                                validation_context += "\nPER-WINDOW RESULTS:\n"
                                for i, (win_start, win_end) in enumerate(allocation_windows):
                                    win_label = window_labels_list[i]
                                    if win_label in window_results:
                                        wr = window_results[win_label]
                                        capacity = window_capacities[win_label]
                                        load_pct = (wr['total_units'] / capacity * 100) if capacity > 0 else 0
                                        validation_context += f"\n{win_label}:\n"
                                        validation_context += f"  - Capacity: {capacity} units\n"
                                        validation_context += f"  - Kept on route: {wr['orders_kept']} orders, {wr['total_units']} units ({load_pct:.1f}%)\n"
                                        validation_context += f"  - Early delivery: {len(wr['early'])} orders\n"
                                        validation_context += f"  - Reschedule: {len(wr['reschedule'])} orders\n"
                                        validation_context += f"  - Cancel: {len(wr['cancel'])} orders\n"

                                validation_context += "\nOVERFLOW ORDERS:\n"
                                if allocation_result.reschedule:
                                    validation_context += f"- {len(allocation_result.reschedule)} orders recommended for reschedule\n"
                                    for resc in allocation_result.reschedule[:3]:  # Sample
                                        count = resc.order.get('priorRescheduleCount', 0) or 0
                                        validation_context += f"  • Order {resc.order['order_id']}: {resc.order['units']} units, reschedule count: {count}\n"

                                if allocation_result.cancel:
                                    validation_context += f"- {len(allocation_result.cancel)} orders recommended for cancel\n"
                                    for canc in allocation_result.cancel[:3]:  # Sample
                                        count = canc.order.get('priorRescheduleCount', 0) or 0
                                        validation_context += f"  • Order {canc.order['order_id']}: {canc.order['units']} units, reschedule count: {count}\n"

                                # Call AI for validation
                                from chat_assistant import call_claude_api

                                ai_prompt = f"""You are analyzing a full-day multi-window route optimization result. Review the allocation logic and per-window routes for correctness.

{validation_context}

BUSINESS RULES TO VALIDATE:
1. Priority customers (power/vip tag) should NEVER be moved from their original window
2. Orders moved early should be within 6 hours of original window start
3. Orders with reschedule_count < 2 should be marked RESCHEDULE
4. Orders with reschedule_count >= 2 should be marked CANCEL
5. Per-window routes should respect capacity constraints
6. Load factors should be reasonable (70-100% is good, <50% is inefficient, >100% is impossible)

Please provide:
1. ✅ Validation: Confirm all business rules are followed (or flag violations)
2. 📊 Efficiency Analysis: Comment on capacity utilization across windows
3. ⚠️ Concerns: Flag any unusual patterns or potential issues
4. 💡 Recommendations: Suggest improvements to capacity settings or allocation if needed

Be concise but thorough. Focus on actionable insights."""

                                validation_result = call_claude_api(ai_prompt)

                                st.markdown("#### 🤖 AI Analysis")
                                st.markdown(validation_result)

                            except Exception as ai_error:
                                st.warning(f"⚠️ AI validation skipped: {ai_error}")
                    else:
                        st.info("💡 Enable AI (via ANTHROPIC_API_KEY in .env) to get intelligent validation of full day allocation")

        except Exception as e:
            st.error(f"❌ Error processing file: {e}")
            import traceback
            with st.expander("Error details"):
                st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
