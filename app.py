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


def create_standard_row(order: Dict) -> Dict:
    """
    Create a standardized row dictionary with the 7 key fields in order:
    1. externalOrderId
    2. customerID
    3. address
    4. customerTag
    5. numberOfUnits
    6. earlyEligible
    7. deliveryWindow
    """
    # Format delivery window
    delivery_window = ""
    if "delivery_window_start" in order and "delivery_window_end" in order:
        start = order["delivery_window_start"]
        end = order["delivery_window_end"]
        if hasattr(start, 'strftime') and hasattr(end, 'strftime'):
            delivery_window = f"{start.strftime('%I:%M %p')} {end.strftime('%I:%M %p')}"

    # Build row in exact order
    row = {
        "externalOrderId": order.get("order_id", ""),
        "customerID": order.get("customer_name", ""),
        "address": order.get("delivery_address", ""),
        "customerTag": order.get("customerTag", ""),
        "numberOfUnits": order.get("units", 0),
        "earlyEligible": "true" if order.get("early_delivery_ok", False) else "false",
        "deliveryWindow": delivery_window
    }

    return row


def _initialize_folium_map(center_lat, center_lon, use_google_tiles=True):
    """
    Initialize a Folium map with specified center and tile provider.

    Args:
        center_lat: Latitude of map center
        center_lon: Longitude of map center
        use_google_tiles: If True, use Google Maps tiles; otherwise use OpenStreetMap

    Returns:
        folium.Map object
    """
    import folium
    from folium import plugins

    if use_google_tiles:
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=12,
            tiles='https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}',
            attr='Google',
            name='Google Maps'
        )
    else:
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=12
        )

    # Add fullscreen button
    try:
        plugins.Fullscreen().add_to(m)
    except Exception as e:
        print(f"Error adding fullscreen button: {e}")

    return m


def _add_route_polylines(m, addresses, waypoint_order, color='#00C800', weight=4, opacity=0.8):
    """
    Add Google Maps route polylines to the map.

    Args:
        m: Folium map object
        addresses: List of addresses
        waypoint_order: Order of waypoints (node indices)
        color: Route line color (default: bright green)
        weight: Line weight
        opacity: Line opacity

    Returns:
        None (modifies map in place)
    """
    import folium

    try:
        route_coords = geocoder.get_route_polylines(addresses, waypoint_order)
        if route_coords:
            folium.PolyLine(
                locations=route_coords,
                color=color,
                weight=weight,
                opacity=opacity,
                tooltip="Delivery Route"
            ).add_to(m)
    except Exception as e:
        print(f"Error drawing route polyline: {e}")


def _add_route_markers(m, keep, early, reschedule, cancel, geocoded, valid_orders, service_times, depot_geo):
    """
    Add markers for depot and all order types to the map.

    Args:
        m: Folium map object
        keep: Orders kept in route
        early: Orders for early delivery
        reschedule: Orders to reschedule
        cancel: Orders to cancel
        geocoded: Geocoded address list
        valid_orders: All valid orders
        service_times: Service time per node
        depot_geo: Depot geocoded location

    Returns:
        None (modifies map in place)
    """
    import folium

    # Add fulfillment location marker (blue)
    try:
        folium.Marker(
            location=[depot_geo["lat"], depot_geo["lng"]],
            popup=folium.Popup(f"<b>Fulfillment Location</b><br/>Starting Point", max_width=200),
            tooltip="🏠 Fulfillment Location",
            icon=folium.Icon(color='blue', icon='home', prefix='fa')
        ).add_to(m)
    except Exception as e:
        print(f"Error adding depot marker: {e}")

    # Add KEEP order markers (green numbered circles)
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

                order_id = str(order.get('order_id', ''))
                customer_name = str(order.get('customer_name', ''))
                units = int(order.get('units', 0))
                sequence_index = int(order.get('sequence_index', 0))
            except (ValueError, TypeError, IndexError, KeyError):
                continue

            tooltip_html = f"""
                <div style="font-family: Arial; font-size: 12px;">
                    <b>✅ Order #{order_id}</b><br/>
                    <b>customerID:</b> {customer_name}<br/>
                    <b>numberOfUnits:</b> {units}<br/>
                    <b>Est. Service Time:</b> {service_time} min<br/>
                    <b>Sequence:</b> Stop #{sequence_index + 1}
                </div>
            """

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

    # Add EARLY/RESCHEDULE order markers (orange)
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


def create_map_visualization(keep, cancel, early, reschedule, geocoded, depot_address, valid_orders, addresses, service_times):
    """Create an interactive Google Maps-style map using Folium (single route)."""
    try:
        # Get depot coordinates
        depot_geo = geocoded[0]
        if depot_geo["lat"] is None:
            return None

        # Calculate center point for map
        all_lats = [depot_geo["lat"]]
        all_lons = [depot_geo["lng"]]

        # Collect all coordinates from kept orders
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

        # Initialize map with Google Maps tiles
        m = _initialize_folium_map(center_lat, center_lon, use_google_tiles=True)

        # Add route polyline (under markers)
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
            _add_route_polylines(m, addresses, waypoint_order)

        # Add all markers (depot, keep, early, reschedule, cancel)
        _add_route_markers(m, keep, early, reschedule, cancel, geocoded, valid_orders, service_times, depot_geo)

        return m

    except Exception as e:
        print(f"Error creating map: {e}")
        return None


def create_multi_window_map(window_results, depot_address, addresses_by_window, geocoded_by_window, window_labels_list):
    """
    Create an interactive map showing all delivery windows with color-coded routes.

    Args:
        window_results: Dict mapping window index to results
                       {0: {'keep': [...], 'early': [...], ...}, 1: {...}, ...}
        depot_address: Depot location address
        addresses_by_window: Dict mapping window index to address list
        geocoded_by_window: Dict mapping window index to geocoded data
        window_labels_list: List of window label strings (e.g., ["9:00 AM - 11:00 AM", ...])

    Returns:
        folium.Map object with all routes
    """
    try:
        import folium

        # Color scheme for different windows (distinct colors)
        route_colors = ['#FF0000', '#0000FF', '#00C800', '#FF00FF', '#FFA500', '#00FFFF', '#FF1493', '#8B4513']

        # Collect all coordinates to calculate center
        all_lats = []
        all_lons = []

        for window_idx, geocoded in geocoded_by_window.items():
            if geocoded and len(geocoded) > 0:
                depot_geo = geocoded[0]
                if depot_geo["lat"] is not None:
                    all_lats.append(depot_geo["lat"])
                    all_lons.append(depot_geo["lng"])

                # Add coordinates from kept orders
                results = window_results.get(window_idx, {})
                for order in results.get('keep', []):
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

        if not all_lats:
            return None

        center_lat = sum(all_lats) / len(all_lats)
        center_lon = sum(all_lons) / len(all_lons)

        # Initialize map with Google Maps tiles
        m = _initialize_folium_map(center_lat, center_lon, use_google_tiles=True)

        # Add depot marker (single for all windows)
        first_geocoded = list(geocoded_by_window.values())[0]
        depot_geo = first_geocoded[0]
        if depot_geo["lat"] is not None:
            folium.Marker(
                location=[depot_geo["lat"], depot_geo["lng"]],
                popup=folium.Popup(f"<b>Fulfillment Location</b><br/>{depot_address}", max_width=200),
                tooltip="🏠 Fulfillment Location (All Routes Start Here)",
                icon=folium.Icon(color='blue', icon='home', prefix='fa')
            ).add_to(m)

        # Add routes and markers for each window
        for window_idx in sorted(window_results.keys()):
            results = window_results[window_idx]
            geocoded = geocoded_by_window.get(window_idx, [])
            addresses = addresses_by_window.get(window_idx, [])
            keep = results.get('keep', [])

            if not keep or not geocoded:
                continue

            # Get color for this window
            color = route_colors[window_idx % len(route_colors)]
            window_label = window_labels_list[window_idx] if window_idx < len(window_labels_list) else f"Window {window_idx + 1}"

            # Build waypoint order
            sorted_keep = sorted(keep, key=lambda x: x.get("sequence_index", 0))
            waypoint_order = [0]
            for order in sorted_keep:
                if "node" in order and order["node"] is not None:
                    try:
                        waypoint_order.append(int(order["node"]))
                    except (ValueError, TypeError):
                        pass
            waypoint_order.append(0)

            # Add polylines for this route
            _add_route_polylines(m, addresses, waypoint_order, color=color, weight=3, opacity=0.7)

            # Add numbered markers for this window's stops
            for order in sorted_keep:
                if "node" not in order or order["node"] is None:
                    continue
                try:
                    node = int(order["node"])
                    if node < 0 or node >= len(geocoded):
                        continue
                    geo = geocoded[node]
                    if geo["lat"] is None:
                        continue

                    order_id = str(order.get('order_id', ''))
                    customer_name = str(order.get('customer_name', ''))
                    units = int(order.get('units', 0))
                    sequence_index = int(order.get('sequence_index', 0))
                except (ValueError, TypeError, IndexError, KeyError):
                    continue

                tooltip_html = f"""
                    <div style="font-family: Arial; font-size: 12px;">
                        <b>Order #{order_id}</b><br/>
                        <b>Window:</b> {window_label}<br/>
                        <b>Customer:</b> {customer_name}<br/>
                        <b>Units:</b> {units}<br/>
                        <b>Stop:</b> #{sequence_index + 1}
                    </div>
                """

                stop_number = sequence_index + 1
                folium.Marker(
                    location=[geo["lat"], geo["lng"]],
                    tooltip=folium.Tooltip(tooltip_html, sticky=True),
                    icon=folium.DivIcon(html=f'''
                            <div style="
                                background-color: {color};
                                border: 2px solid white;
                                border-radius: 50%;
                                width: 28px;
                                height: 28px;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 12px;
                                font-weight: bold;
                                color: white;
                                box-shadow: 0 2px 5px rgba(0,0,0,0.3);
                            ">{stop_number}</div>
                        ''')
                ).add_to(m)

        # Add legend
        legend_html = '''
        <div style="position: fixed;
                    bottom: 50px; right: 50px;
                    background-color: white;
                    padding: 10px;
                    border: 2px solid grey;
                    border-radius: 5px;
                    box-shadow: 0 2px 5px rgba(0,0,0,0.3);
                    z-index: 9999;
                    font-family: Arial;
                    font-size: 12px;">
            <b>Routes by Window</b><br>
        '''
        for window_idx in sorted(window_results.keys()):
            color = route_colors[window_idx % len(route_colors)]
            window_label = window_labels_list[window_idx] if window_idx < len(window_labels_list) else f"Window {window_idx + 1}"
            keep_count = len(window_results[window_idx].get('keep', []))
            legend_html += f'<span style="color: {color};">●</span> {window_label} ({keep_count} orders)<br>'
        legend_html += '</div>'

        m.get_root().html.add_child(folium.Element(legend_html))

        return m

    except Exception as e:
        print(f"Error creating multi-window map: {e}")
        import traceback
        traceback.print_exc()
        return None


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
        explanation.append(f"**⏰ Deliver Early ({len(early)} orders)**")
        explanation.append(f"Customer approved early delivery. These are <10 min from route cluster - move to earlier window for efficiency.\n")

    # Reschedule rationale
    if reschedule:
        explanation.append(f"**📅 Reschedule ({len(reschedule)} orders)**")
        explanation.append(f"Within 10-20 min of cluster but won't fit due to capacity/time. Move to adjacent window where they can group with other nearby orders.\n")

    # Cancel rationale
    if cancel:
        explanation.append(f"**❌ Cancel ({len(cancel)} orders)**")
        explanation.append(f"≥20 min from cluster - geographically isolated. Cost to serve exceeds revenue. Including them would force dropping multiple better-positioned orders.\n")

    explanation.append("**Why This Route**: Algorithm maximizes orders delivered within constraints. Uses real Google Maps drive times, not straight-line distance.")

    return "\n".join(explanation)


def display_optimization_results(keep, early, reschedule, cancel, kept, service_times, geocoded,
                                 depot_address, valid_orders, addresses, time_matrix,
                                 vehicle_capacity, window_minutes, strategy_desc, show_ai_explanations=True):
    """Display results for one optimization strategy."""

    # Route KPIs first (per user preference)
    st.subheader("📊 Route KPIs")
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

    st.markdown("---")

    # Movement Summary Table (after KPIs, per user preference)
    st.subheader("📊 Movement Summary")

    original_total = len(valid_orders)
    on_route_count = len(keep)
    early_count = len(early)
    reschedule_count = len(reschedule)
    cancel_count = len(cancel)

    movement_data = [{
        "Original Total": original_total,
        "🚛 On Route": on_route_count,
        "⏰ Deliver Early": early_count,
        "📅 Reschedule": reschedule_count,
        "❌ Cancel": cancel_count
    }]

    movement_df = pd.DataFrame(movement_data)
    st.dataframe(movement_df, use_container_width=True)
    st.caption(f"All {original_total} orders classified after optimization.")

    st.markdown("---")

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
                st.markdown("❌ **Red X**: Orders to Cancel (too far)")
            with col4:
                st.markdown("🏠 **Blue home**: Fulfillment Location")
        else:
            st.warning("❌ Error creating map: bad argument type for built-in operation")
            st.info("💡 Try loading a different cut or re-running the optimization.")
    except Exception as e:
        st.warning(f"❌ Error creating map: {str(e)}")
        st.info("💡 Try loading a different cut or re-running the optimization.")

    # Display On Route orders
    st.subheader("🚛 On Route")
    if keep:
        keep_data = []
        for k in sorted(keep, key=lambda x: x["sequence_index"]):
            # Create row with standard 7 fields
            row = {"Seq": k["sequence_index"] + 1}
            row.update(create_standard_row(k))

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

    # Deliver Early expander (matches Multiple Windows UX)
    if early:
        with st.expander(f"⏰ Deliver Early ({len(early)} orders)", expanded=False):
            early_data = []
            for e in early:
                # Create row with standard 7 fields
                row = create_standard_row(e)

                # Add optimizer-computed fields at the end
                row["Score"] = f"{e.get('optimal_score', 0)}/100"

                if show_ai_explanations:
                    row["AI Explanation"] = e.get("ai_explanation", e.get("reason", ""))
                else:
                    row["Reason"] = e.get("reason", "Close to route and early OK")
                early_data.append(row)

            early_df = pd.DataFrame(early_data)
            st.dataframe(early_df, use_container_width=True)

    # Reschedule expander (matches Multiple Windows UX)
    if reschedule:
        with st.expander(f"📅 Reschedule ({len(reschedule)} orders)", expanded=False):
            reschedule_data = []
            for r in reschedule:
                # Create row with standard 7 fields
                row = create_standard_row(r)

                # Add optimizer-computed fields at the end
                row["Score"] = f"{r.get('optimal_score', 0)}/100"

                if show_ai_explanations:
                    row["AI Explanation"] = r.get("ai_explanation", r.get("reason", ""))
                else:
                    row["Reason"] = r.get("reason", "Better fit in different window")
                reschedule_data.append(row)

            reschedule_df = pd.DataFrame(reschedule_data)
            st.dataframe(reschedule_df, use_container_width=True)

    # Cancel expander (matches Multiple Windows UX)
    if cancel:
        with st.expander(f"❌ Cancel ({len(cancel)} orders)", expanded=False):
            cancel_data = []
            for c in cancel:
                # Create row with standard 7 fields
                row = create_standard_row(c)

                # Add optimizer-computed fields at the end
                row["Score"] = f"{c.get('optimal_score', 0)}/100"

                if show_ai_explanations:
                    row["AI Explanation"] = c.get("ai_explanation", c.get("reason", ""))
                else:
                    row["Reason"] = c.get("reason", "Too far from cluster")
                cancel_data.append(row)

            cancel_df = pd.DataFrame(cancel_data)
            st.dataframe(cancel_df, use_container_width=True)


def check_password() -> bool:
    """
    Password protection for the app.

    Returns:
        bool: True if user is authenticated, False otherwise
    """
    # Check if authentication is required
    if not config.is_auth_required():
        return True

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
        submit = st.form_submit_button("Login", type="primary", width='stretch')

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
    st.title("🚚 The Buncher")

    # ============================================================================
    # SIDEBAR: Progressive Reveal Workflow
    # ============================================================================
    st.sidebar.header("🚐 Buncher Workflow")

    # -------------------------------------------------------------------------
    # STEP 1: Upload Orders (Always Visible)
    # -------------------------------------------------------------------------
    st.sidebar.markdown("### 📤 Step 1: Upload Orders")
    uploaded_file = st.sidebar.file_uploader(
        "Upload CSV file",
        type=["csv"],
        help="Upload CSV with order data in the expected format"
    )

    # Initialize variables for progressive reveal
    orders = None
    window_minutes = None
    depot_address = None
    location_verified = False
    mode = None

    # Parse CSV if uploaded
    if uploaded_file:
        try:
            # Check if this is a new file upload - reset states if so
            current_filename = uploaded_file.name if hasattr(uploaded_file, 'name') else None
            if current_filename and st.session_state.get('last_uploaded_filename') != current_filename:
                # New file uploaded - reset configuration
                st.session_state.window_capacities_config = {}
                st.session_state.optimization_complete = False  # Re-enable editing
                st.session_state.last_uploaded_filename = current_filename

            orders, window_minutes = parser.parse_csv(uploaded_file)
        except Exception as e:
            st.sidebar.error(f"❌ Error parsing CSV: {str(e)}")
            orders = None
            window_minutes = None

    # -------------------------------------------------------------------------
    # STEP 2: Verify Location (Hidden Until CSV Uploaded)
    # -------------------------------------------------------------------------
    if uploaded_file and orders:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 📍 Step 2: Verify Location")

        # Auto-detect from CSV
        depot_address_from_csv = None
        if orders and 'fulfillmentLocationAddress' in orders[0]:
            depot_address_from_csv = orders[0]['fulfillmentLocationAddress']

        if depot_address_from_csv and depot_address_from_csv.strip():
            depot_address = depot_address_from_csv.strip()
            st.sidebar.success(f"✅ Auto-detected: {depot_address}")
            location_verified = True
        else:
            # Manual input if not in CSV
            depot_address = st.sidebar.text_input(
                "Fulfillment Location",
                value=config.get_default_depot(),
                help="Enter depot address or it will be auto-detected from CSV",
                key="depot_address_input"
            )
            location_verified = bool(depot_address and depot_address.strip())

    # -------------------------------------------------------------------------
    # STEP 3: Select Mode (Hidden Until Location Verified)
    # -------------------------------------------------------------------------
    if location_verified:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### ⚙️ Step 3: Select Optimization Mode")

        mode = st.sidebar.radio(
            "Choose mode:",
            ["One Window", "Multiple Windows"],
            index=1,  # Default to Multiple Windows
            help="One Window: optimize a single delivery window. Multiple Windows: allocate orders across multiple windows.",
            key="mode_selector"
        )

    # -------------------------------------------------------------------------
    # STEP 4: Mode-Specific Configuration (Under Mode Selector)
    # -------------------------------------------------------------------------
    selected_window = None
    window_capacities = {}
    vehicle_capacity = config.get_default_capacity()
    enable_cut2 = False
    enable_cut3 = False
    honor_priority = False
    cancel_threshold = 80
    reschedule_threshold = 40

    if mode == "One Window" and orders:
        st.sidebar.markdown("#### One Window Settings")

        # Detect unique delivery windows
        unique_windows = set()
        for o in orders:
            unique_windows.add((o['delivery_window_start'], o['delivery_window_end']))
        sorted_windows = sorted(list(unique_windows))

        # Create window labels
        window_labels_list = []
        for win_start, win_end in sorted_windows:
            label = f"{win_start.strftime('%I:%M %p')} - {win_end.strftime('%I:%M %p')}"
            window_labels_list.append(label)

        # Delivery window selector
        if window_labels_list:
            selected_window_label = st.sidebar.selectbox(
                "Delivery window:",
                window_labels_list,
                help="Select the delivery window to optimize",
                key="window_selector"
            )

            # Find the corresponding window tuple
            selected_window_index = window_labels_list.index(selected_window_label)
            selected_window = sorted_windows[selected_window_index]

        # Vehicle capacity
        vehicle_capacity = st.sidebar.number_input(
            "Vehicle capacity (units):",
            min_value=50,
            max_value=500,
            value=config.get_default_capacity(),
            step=10,
            help="Maximum units this vehicle can carry",
            key="vehicle_capacity_input"
        )

        # Cut selection
        st.sidebar.markdown("**Optimization Scenarios:**")
        st.sidebar.checkbox(
            "✅ Cut 1: Max Orders",
            value=True,
            disabled=True,
            key="enable_cut1",
            help="Always enabled - maximizes number of orders served"
        )
        enable_cut2 = st.sidebar.checkbox(
            "Cut 2: Shortest Route",
            value=False,
            key="enable_cut2",
            help="Optional - optimizes for shortest total distance"
        )
        enable_cut3 = st.sidebar.checkbox(
            "Cut 3: High Density",
            value=False,
            key="enable_cut3",
            help="Optional - maximizes deliveries per hour in dense clusters"
        )

    elif mode == "Multiple Windows" and orders:
        st.sidebar.markdown("#### Multi-Window Settings")

        # Allocation controls
        honor_priority = st.sidebar.checkbox(
            "Lock priority customers to preferred windows",
            value=False,
            key="honor_priority",
            help="If enabled, priority customers stay in their requested windows"
        )

        col1, col2 = st.sidebar.columns(2)
        with col1:
            cancel_threshold = st.number_input(
                "Auto-cancel threshold (units):",
                min_value=0,
                value=80,
                help="Orders with > X units are auto-cancelled if they don't fit",
                key="cancel_threshold"
            )
        with col2:
            reschedule_threshold = st.number_input(
                "Auto-reschedule threshold (units):",
                min_value=0,
                value=40,
                help="Orders with > X units can be rescheduled to adjacent windows",
                key="reschedule_threshold"
            )

        # Note: Capacity configuration will happen in main window
        # as it requires a data_editor which is too large for sidebar
        st.sidebar.info("💡 Configure capacity per window in the main area below")

    # -------------------------------------------------------------------------
    # STEP 5: Advanced Configuration (Bottom of Sidebar)
    # -------------------------------------------------------------------------
    fixed_service_time = None
    test_mode = False

    if location_verified and mode:
        st.sidebar.markdown("---")

        with st.sidebar.expander("🔧 Advanced Configuration", expanded=False):
            # Service time method
            default_method = config.get_default_service_time_method()
            default_index = 0 if default_method == "smart" else 1

            service_time_method = st.radio(
                "Service time method:",
                ["Smart (Variable by Units)", "Fixed (Same for All Stops)"],
                index=default_index,
                help="Smart adjusts time based on order size. Fixed uses same time for all stops.",
                key="service_time_method"
            )

            if service_time_method == "Fixed (Same for All Stops)":
                fixed_service_time = st.number_input(
                    "Service time per stop (minutes):",
                    min_value=1,
                    max_value=20,
                    value=config.get_default_fixed_service_time(),
                    step=1,
                    key="fixed_service_time_input"
                )

            # Test mode toggle
            test_mode = st.checkbox(
                "🧪 Test Mode (Skip APIs)",
                value=config.is_test_mode(),
                key="test_mode_toggle",
                help="Enable to use mock data and skip API calls (zero cost)"
            )
            config.set_test_mode(test_mode)

            if test_mode:
                st.warning("⚠️ Test Mode: Using mock data")

    # -------------------------------------------------------------------------
    # RUN OPTIMIZATION BUTTON (Always Visible, Conditionally Enabled)
    # -------------------------------------------------------------------------
    st.sidebar.markdown("---")

    # AI status indicator
    use_ai = config.is_ai_enabled()
    if use_ai:
        st.sidebar.success("✅ **AI Features Enabled**")
    elif not test_mode:
        st.sidebar.info("ℹ️ **AI Disabled** (No API key)")

    # Check if all requirements met
    can_run = bool(uploaded_file and orders and location_verified and mode)

    if not can_run:
        # Show specific blocking reason
        if not uploaded_file:
            helper_text = "⚠️ Upload a CSV to continue"
        elif not orders:
            helper_text = "⚠️ Error parsing CSV"
        elif not location_verified:
            helper_text = "⚠️ Verify fulfillment location to continue"
        elif not mode:
            helper_text = "⚠️ Select optimization mode to continue"
        else:
            helper_text = ""

        st.sidebar.button(
            "🚀 Run Optimization",
            type="primary",
            width='stretch',
            disabled=True,
            key="run_disabled"
        )
        if helper_text:
            st.sidebar.caption(helper_text)

        run_optimization = False
    else:
        run_optimization = st.sidebar.button(
            "🚀 Run Optimization",
            type="primary",
            width='stretch',
            key="run_enabled"
        )

    # Clear old results when starting new optimization
    if run_optimization:
        st.session_state.optimization_results = None
        st.session_state.full_day_results = None
        st.session_state.optimization_context = None
        st.session_state.chat_messages = []
        st.session_state.optimization_complete = True  # Set flag for order preview editability
        use_ai = config.is_ai_enabled()
        st.session_state.use_ai = use_ai

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
                generate_btn = st.form_submit_button("✅ Generate", type="primary", width='stretch')
            with col2:
                cancel_btn = st.form_submit_button("❌ Cancel", width='stretch')

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

    # ============================================================================
    # MAIN WINDOW: Display Sample Data or Results
    # ============================================================================

    # BEFORE CSV UPLOAD: Show sample data and template
    if not uploaded_file:
        st.markdown("Upload a CSV file in the sidebar to begin optimizing delivery routes.")

        st.markdown("---")
        st.subheader("📋 Sample CSV Format")
        st.markdown("Your CSV should include these columns (new format):")

        # Show sample data matching actual new format from parser.py
        sample_df = pd.DataFrame({
            'externalOrderId': ['ORD-70592', 'ORD-70593', 'ORD-70594'],
            'customerID': ['CUST-001', 'CUST-002', 'CUST-003'],
            'address': [
                '123 Main St, Detroit, MI 48201',
                '456 Oak Ave, Detroit, MI 48202',
                '789 Elm St, Detroit, MI 48203'
            ],
            'customerTag': ['priority', 'regular', 'regular'],
            'numberOfUnits': [25, 30, 15],
            'earlyEligible': [True, False, True],
            'deliveryWindow': [
                '09:00 AM 11:00 AM',
                '09:00 AM 11:00 AM',
                '01:00 PM 03:00 PM'
            ]
        })
        st.dataframe(sample_df, width='stretch')

        st.markdown("""
        **Required columns:**
        - `externalOrderId` - Unique order identifier
        - `customerID` - Customer identifier
        - `address` - Full delivery address
        - `customerTag`
        - `numberOfUnits` - Number of units/totes
        - `earlyEligible` - Can deliver early? (True/False)
        - `deliveryWindow` - Time window (format: "HH:MM AM HH:MM PM")

        **Optional columns:**
        - `orderId`, `runId`, `orderStatus`, `deliveryDate`,
          `priorRescheduleCount`, `fulfillmentLocation`, `fulfillmentGeo`,
          `fulfillmentLocationAddress`, `extendedCutOffTime`
        """)

        st.markdown("---")
        st.markdown("### 📥 Export Orders from Database")
        st.markdown("Dispatchers can export orders directly:")
        st.markdown("[🔗 Buncher Exporter (Metabase)](https://metabase.prod.gobuncha.com/question/12227-buncher-exporter?date=2026-02-13&Delivery_window=&Fulfillment_Geo=)")
        st.info("💡 This exporter generates CSV files in the correct format for bulk upload.")

    # AFTER CSV UPLOAD: Show order preview and results
    elif uploaded_file and orders:
        # Show upload summary
        st.success(f"✅ Loaded {len(orders)} orders with {window_minutes}-minute delivery window")

        # Validate orders
        valid_orders, errors = parser.validate_orders(orders)

        if errors:
            st.error(f"❌ Found {len(errors)} validation errors:")
            for error in errors:
                st.write(f"- {error}")

        # BEFORE optimization runs: editable order preview
        if not st.session_state.get('optimization_complete', False):
            with st.expander("📦 Order Preview & Management", expanded=True):
                st.markdown("Review and edit orders before optimization. Add/remove rows as needed.")

                # Build preview dataframe
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

                    # Add optional fields if present
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
                    num_rows="dynamic",  # Allow adding/deleting rows
                    width='stretch',
                    height=400,
                    key="order_editor"
                )

                st.caption("💡 You can add/remove orders and edit values. Changes apply to this session only.")

        # AFTER optimization runs: read-only order preview (show ALL imported data)
        else:
            with st.expander("📦 Order Preview", expanded=False):
                preview_rows = []
                for o in orders:
                    # Start with core fields
                    row = {
                        "externalOrderId": o["order_id"],
                        "customerID": o["customer_name"],
                        "address": o["delivery_address"],
                        "numberOfUnits": o["units"],
                        "earlyEligible": "true" if o["early_delivery_ok"] else "false",
                        "deliveryWindow": f"{o['delivery_window_start'].strftime('%I:%M %p')} {o['delivery_window_end'].strftime('%I:%M %p')}"
                    }

                    # Add ALL optional fields if present (to show complete imported data)
                    optional_fields = ["orderId", "runId", "orderStatus", "customerTag",
                                     "deliveryDate", "priorRescheduleCount", "fulfillmentLocation",
                                     "fulfillmentGeo", "fulfillmentLocationAddress", "extendedCutOffTime"]

                    for field in optional_fields:
                        if field in o and o[field] is not None:
                            row[field] = o[field]

                    preview_rows.append(row)

                preview_df = pd.DataFrame(preview_rows)

                st.dataframe(
                    preview_df,
                    width='stretch',
                    height=400
                )
                st.caption("📌 Orders are locked after optimization. Re-upload CSV to make changes.")

        # Multiple Windows capacity configuration (shown in main window)
        if mode == "Multiple Windows" and valid_orders:
            # Detect unique delivery windows
            unique_windows = set()
            for order in valid_orders:
                window_start = order['delivery_window_start']
                window_end = order['delivery_window_end']
                unique_windows.add((window_start, window_end))

            # Sort windows by start time
            sorted_windows = sorted(list(unique_windows), key=lambda w: w[0])

            # Create window labels
            from allocator import window_label
            window_labels_list = [window_label(start, end) for start, end in sorted_windows]

            # Capacity Configuration - Collapsible like Order Preview
            optimization_complete = st.session_state.get('optimization_complete', False)

            from datetime import datetime, time as dt_time
            capacity_data = []
            window_times_map = {}  # Store original window times for matching orders later

            # Initialize session state for capacities if not exists
            if 'window_capacities_config' not in st.session_state:
                st.session_state.window_capacities_config = {}

            for i, (win_start, win_end) in enumerate(sorted_windows):
                label = window_labels_list[i]
                window_orders = [o for o in valid_orders if
                               o['delivery_window_start'] == win_start and
                               o['delivery_window_end'] == win_end]
                total_units = sum(o['units'] for o in window_orders)

                # Use updated times from editor if available (persisted across reruns)
                if 'updated_window_times' in st.session_state and label in st.session_state.updated_window_times:
                    display_start, display_end = st.session_state.updated_window_times[label]
                else:
                    display_start, display_end = win_start, win_end

                # Calculate window length from display times (reflects any edits)
                start_minutes = display_start.hour * 60 + display_start.minute
                end_minutes = display_end.hour * 60 + display_end.minute
                window_length = end_minutes - start_minutes

                # Get capacity from session state or use default
                capacity = st.session_state.window_capacities_config.get(label, 300)

                # Calculate utilization and status based on current capacity (reactive)
                utilization = round((total_units / capacity) * 100, 1) if capacity > 0 else 0
                if total_units <= capacity * 0.85:
                    status = "🟢"
                elif total_units <= capacity:
                    status = "🟡"
                else:
                    status = "🔴"

                capacity_data.append({
                    "Window": label,  # Keep for internal use but hide in display
                    "Start": display_start,
                    "End": display_end,
                    "Length (min)": window_length,
                    "Orders": len(window_orders),
                    "Units": total_units,
                    "Capacity": capacity,
                    "Utilization %": utilization,
                    "Status": status
                })

                # Store mapping for later
                window_times_map[label] = (win_start, win_end)

            # Create dataframe
            capacity_df = pd.DataFrame(capacity_data)

            # BEFORE optimization: editable capacity configuration
            if not optimization_complete:
                with st.expander("🚛 Configure Window Times & Capacity", expanded=True):
                    st.markdown("Edit **Start** and **End** to adjust window length, or **Capacity** to set max units per window. Hit **Save Changes** when done — Utilization and Length will recalculate.")

                    # Show editable capacity table
                    edited_df = st.data_editor(
                        capacity_df,
                        width='stretch',
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
                                help="Recalculates after Save Changes"
                            ),
                            "Orders": st.column_config.NumberColumn(
                                "Orders",
                                disabled=True,
                                width="small"
                            ),
                            "Units": st.column_config.NumberColumn(
                                "Units",
                                disabled=True,
                                width="small"
                            ),
                            "Capacity": st.column_config.NumberColumn(
                                "Capacity",
                                min_value=50,
                                max_value=500,
                                step=10,
                                width="small",
                                help="Set capacity for this window"
                            ),
                            "Utilization %": st.column_config.NumberColumn(
                                "Utilization %",
                                disabled=True,
                                width="small",
                                help="Recalculates after Save Changes"
                            ),
                            "Status": st.column_config.TextColumn(
                                "Status",
                                disabled=True,
                                width="small"
                            )
                        },
                        key="capacity_editor"
                    )

                    # Save Changes button — only commits edits when explicitly clicked
                    if st.button("💾 Save Changes", type="primary"):
                        if 'updated_window_times' not in st.session_state:
                            st.session_state.updated_window_times = {}
                        for _, row in edited_df.iterrows():
                            label = row["Window"]
                            # Save capacity
                            st.session_state.window_capacities_config[label] = int(row["Capacity"])
                            # Save updated start/end times
                            start_val = row["Start"]
                            end_val = row["End"]
                            if start_val is not None and end_val is not None:
                                st.session_state.updated_window_times[label] = (start_val, end_val)
                        # Force immediate rerun so capacity_df rebuilds with new values right away
                        st.rerun()

            # AFTER optimization: collapsed read-only view
            else:
                with st.expander("🚛 Window Times & Capacity (locked)", expanded=False):
                    st.markdown("📌 Configuration locked after optimization. Re-upload CSV or refresh to make changes.")
                    st.dataframe(capacity_df, use_container_width=True)

            # Build window_capacities from session state (source of truth for optimization)
            window_capacities = {}
            for label in window_labels_list:
                window_capacities[label] = st.session_state.window_capacities_config.get(label, 300)

            # Add horizontal line after configuration sections
            st.markdown("---")

        # Run optimization execution starts here
        try:
            if valid_orders and run_optimization:
                # Progress updates (no visual bar, just status messages)
                progress_text = st.empty()

                def update_progress(percent, step_name):
                    """Update progress status message"""
                    progress_text.markdown(f"🚐 **{step_name}** ({percent}%)")

                # MODE-SPECIFIC OPTIMIZATION
                if mode == "One Window":
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
                            all_orders=orders_to_optimize,
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

                        # CUT 2: SHORTEST ROUTE (OPTIONAL)
                        # Only run if dispatcher enabled Cut 2
                        if st.session_state.get('enable_cut2', False):
                            # NEW APPROACH: Pre-filter by efficiency (units/distance), select most efficient orders
                            update_progress(55, "Running Cut 2: Shortest Route (Efficiency-Based)...")

                            # Step 1: Calculate efficiency score for each order (units per minute from depot)
                            order_efficiency = []
                            for idx, order in enumerate(orders_to_optimize):
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
                                all_orders=orders_to_optimize,
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

                        # CUT 3: HIGH DENSITY (OPTIONAL)
                        # Only run if dispatcher enabled Cut 3
                        if st.session_state.get('enable_cut3', False):
                            # maximize stops per minute within cluster, ignore depot distance
                            update_progress(75, "Running Cut 3: High Density (tight cluster)...")

                            # Step 1: For each order, calculate average distance to all OTHER orders (cluster cohesion)
                            order_cluster_scores = []
                            for idx, order in enumerate(orders_to_optimize):
                                node = idx + 1
                                # Calculate average distance to all other orders
                                distances_to_others = []
                                for other_idx in range(len(orders_to_optimize)):
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
                                all_orders=orders_to_optimize,
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
                        if st.session_state.get('enable_cut2', False) and 'shortest' in optimizations:
                            st.write(f"   Cut 2 (Shortest): {len(keep_short)} orders, {metrics_short['total_units']} units, {metrics_short['total_time']} min, {metrics_short['stops_per_mile']:.1f} stops/mi")
                        if st.session_state.get('enable_cut3', False) and 'high_density' in optimizations:
                            st.write(f"   Cut 3 (High Density): {len(keep_dense)} orders, {metrics_dense['total_units']} units, {metrics_dense['total_time']} min, {cluster_density:.2f} cluster stops/min")

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
                                'optimizations': optimizations,  # Dict with 'max_orders', 'shortest' (optional), 'high_density' (optional)
                                'geocoded': geocoded,
                                'depot_address': depot_address,
                                'valid_orders': orders_to_optimize,
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
                                keep_rec, early_rec, reschedule_rec, cancel_rec, orders_to_optimize,
                                time_matrix, service_times, vehicle_capacity, window_minutes, api_key
                            )

                            if validation:
                                st.session_state.chat_messages.append({
                                    "role": "assistant",
                                    "content": f"**🔍 AI Route Validation (Cut 1: Max Orders)**\n\n{validation}"
                                })

                            # Store optimization context for chat (using MAX ORDERS)
                            st.session_state.optimization_context = chat_assistant.create_context_for_ai(
                                keep_rec, early_rec, reschedule_rec, cancel_rec, orders_to_optimize,
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

                        # Build tab options dynamically based on which cuts were run
                        max_orders_count = optimizations['max_orders']['orders_kept']
                        tab_options = [f"✅ Cut 1: Max Orders ({max_orders_count} Orders) - RECOMMENDED"]

                        if 'shortest' in optimizations:
                            shortest_orders_count = optimizations['shortest']['orders_kept']
                            tab_options.append(f"⚡ Cut 2: Shortest Route ({shortest_orders_count} Orders)")
                        if 'high_density' in optimizations:
                            density_orders_count = optimizations['high_density']['orders_kept']
                            tab_options.append(f"🎯 Cut 3: High Density ({density_orders_count} Orders)")

                        st.markdown("---")
                        st.markdown("## 🖥️ One Window Optimization")

                        # Cut selector with integrated help text
                        selected_tab = st.selectbox(
                            "Select Optimization Strategy:",
                            options=tab_options,
                            index=st.session_state.active_tab,
                            key="tab_selector",
                            help="Cut 1: Maximizes orders delivered within constraints (RECOMMENDED) | Cut 2: Optimizes for shortest route with 80-90% capacity | Cut 3: Maximizes delivery density in tight clusters"
                        )

                        # Update active tab in session state
                        st.session_state.active_tab = tab_options.index(selected_tab)

                        # TAB 1: MAX ORDERS (RECOMMENDED - default view)
                        if st.session_state.active_tab == 0:
                            opt = optimizations['max_orders']

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

                        # TAB 2: SHORTEST ROUTE (only if Cut 2 was run)
                        elif st.session_state.active_tab == 1 and 'shortest' in optimizations:
                            opt = optimizations['shortest']

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

                        # TAB 3: HIGH DENSITY (only if Cut 3 was run)
                        # Dynamic tab index: 1 if only Cut 2, 2 if both Cut 2 and Cut 3
                        elif st.session_state.active_tab >= 1 and 'high_density' in optimizations:
                            # If Cut 2 wasn't run, this is tab 1, otherwise tab 2
                            expected_tab_index = 1 if 'shortest' not in optimizations else 2
                            if st.session_state.active_tab == expected_tab_index:
                                opt = optimizations['high_density']

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

                elif mode == "Multiple Windows":
                    # MULTIPLE WINDOWS MODE: Allocate orders across windows, then optimize each window
                    st.markdown("## 🌅 Multiple Windows Optimization")

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


                    # Note: Movement Summary with per-window breakdown will be added after window_results are populated
                    # This placeholder reminds us where it will appear in the final display

                    # Now optimize each window separately
                    st.markdown("### 🚛 Per-Window Optimization Results")

                    # Create a status placeholder for progress updates (won't cause reruns)
                    progress_placeholder = st.empty()

                    window_results = {}

                    # PHASE 1: Collect all optimization data (NO display widgets)
                    for i, (win_start, win_end) in enumerate(allocation_windows):
                        win_label = window_labels_list[i]
                        win_orders = allocation_result.orders_by_window.get(win_label, [])

                        # Update progress (safe - just updates text in placeholder)
                        progress_placeholder.info(f"⏳ Optimizing window {i+1}/{len(allocation_windows)}: {win_label} ({len(win_orders)} orders)...")

                        if not win_orders:
                            window_results[win_label] = {'empty': True}
                            continue

                        # Compute window duration (using edited times if available)
                        from allocator import window_duration_minutes
                        win_duration = window_duration_minutes(win_start, win_end)

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

                        # Calculate route time for this window
                        route_time = 0
                        if keep:
                            sorted_keep_temp = sorted(keep, key=lambda x: x.get('sequence_index', 0))
                            kept_nodes = [k['node'] for k in sorted_keep_temp]
                            route_time = win_time_matrix[0][kept_nodes[0]]
                            for idx in range(len(kept_nodes) - 1):
                                route_time += win_time_matrix[kept_nodes[idx]][kept_nodes[idx + 1]]
                            route_time += win_time_matrix[kept_nodes[-1]][0]

                        # Enrich drop reasons: distinguish time constraint vs geographic isolation
                        if dropped and keep:
                            # Build order_id → node index lookup
                            _oid_to_node = {o.get('order_id'): i + 1 for i, o in enumerate(win_orders)}

                            def _cheapest_insertion(node, k_nodes, tm, svc):
                                """Min extra route time to insert node via cheapest-insertion heuristic."""
                                best = tm[0][node] + svc + tm[node][k_nodes[0]] - tm[0][k_nodes[0]]
                                for j in range(len(k_nodes) - 1):
                                    a, b = k_nodes[j], k_nodes[j + 1]
                                    best = min(best, tm[a][node] + svc + tm[node][b] - tm[a][b])
                                best = min(best, tm[k_nodes[-1]][node] + svc + tm[node][0] - tm[k_nodes[-1]][0])
                                return max(0, best)

                            for drop_list in [reschedule, cancel, early]:
                                for order in drop_list:
                                    node = _oid_to_node.get(order.get('order_id'))
                                    if node is None or node >= len(win_time_matrix):
                                        continue
                                    svc = win_service_times[node] if node < len(win_service_times) else 0
                                    extra = _cheapest_insertion(node, kept_nodes, win_time_matrix, svc)
                                    if route_time + extra > win_duration:
                                        over = route_time + extra - win_duration
                                        order['reason'] = (
                                            f"Route time constraint — adding this stop would take ~{extra} min "
                                            f"(route at {route_time}/{win_duration} min, ~{over} min over window limit)"
                                        )
                                    # else: geographic isolation reason from disposition.py stands

                        # Store ALL results for later display
                        window_results[win_label] = {
                            'keep': keep,
                            'early': early,
                            'reschedule': reschedule,
                            'cancel': cancel,
                            'orders_kept': len(keep),
                            'total_units': sum(o['units'] for o in keep),
                            'geocoded': win_geocoded,
                            'addresses': win_addresses,
                            'time_matrix': win_time_matrix,
                            'service_times': win_service_times,
                            'capacity': win_capacity,
                            'duration': win_duration,
                            'route_time': route_time,
                            'orders': win_orders,
                            'empty': False
                        }

                    # Clear progress message
                    progress_placeholder.success(f"✅ All {len(allocation_windows)} windows optimized successfully!")

                    # POST-OPTIMIZATION RECONCILIATION: Check if moved_later orders were kept or dropped
                    # The optimizer serves as the geographic check — if it dropped the order it wasn't a good fit
                    window_kept_ids = {}
                    window_dropped_ids = {}
                    for wl in window_labels_list:
                        r = window_results.get(wl, {})
                        window_kept_ids[wl] = {o.get('order_id') for o in r.get('keep', [])}
                        window_dropped_ids[wl] = (
                            {o.get('order_id') for o in r.get('reschedule', [])} |
                            {o.get('order_id') for o in r.get('cancel', [])}
                        )

                    moved_later_outcome = {}  # order_id → 'kept' | 'dropped' | 'unknown'
                    for alloc in allocation_result.moved_later:
                        oid = alloc.order.get('order_id')
                        tw = alloc.assigned_window
                        if oid in window_kept_ids.get(tw, set()):
                            moved_later_outcome[oid] = 'kept'
                            alloc.reason = f"Capacity overflow at allocation time — {alloc.original_window} was full; placed in {tw} ✓"
                        elif oid in window_dropped_ids.get(tw, set()):
                            moved_later_outcome[oid] = 'dropped'
                            alloc.reason = f"Capacity overflow at allocation — {alloc.original_window} was full; tried {tw} but optimizer dropped it (time constraint or geographic isolation)"
                        else:
                            moved_later_outcome[oid] = 'unknown'

                    # Store to session state IMMEDIATELY (before any display)
                    st.session_state.full_day_results = {
                        'window_results': window_results,
                        'allocation_result': allocation_result,
                        'moved_later_outcome': moved_later_outcome,
                        'window_labels_list': window_labels_list,
                        'window_capacities': window_capacities,
                        'allocation_windows': allocation_windows,
                        'depot_address': depot_address,
                        'mode': 'Multiple Windows',
                        'ai_validation': None,
                        'use_ai': st.session_state.get('use_ai', False)
                    }

                    st.rerun()


                    # Movement by Window Table
                    st.markdown("### 📊 Movement by Window")

                    # Calculate global totals first
                    global_original_total = len(valid_orders)  # All orders from CSV

                    global_kept_temp = 0
                    global_received_early = len(allocation_result.moved_early)
                    global_deliver_early = len(allocation_result.moved_early)
                    global_moved_later = len(allocation_result.moved_later)
                    global_reschedule = len(allocation_result.reschedule)
                    global_cancel = len(allocation_result.cancel)

                    moved_later_by_id = {a.order.get('order_id'): a for a in allocation_result.moved_later}

                    for win_label in window_labels_list:
                        result = window_results.get(win_label)
                        if result and not result.get('empty', False):
                            received_early_ids = {a.order.get('order_id') for a in allocation_result.moved_early if a.assigned_window == win_label}
                            received_later_ids = {a.order.get('order_id') for a in allocation_result.moved_later if a.assigned_window == win_label}
                            all_received_ids = received_early_ids | received_later_ids
                            global_kept_temp += len([k for k in result.get('keep', []) if k.get('order_id') not in all_received_ids])
                            opt_resc = [o for o in result.get('reschedule', []) if o.get('order_id') not in moved_later_by_id]
                            opt_cancel = [o for o in result.get('cancel', []) if o.get('order_id') not in moved_later_by_id]
                            global_reschedule += len(opt_resc)
                            global_cancel += len(opt_cancel)

                    global_kept = global_kept_temp
                    global_received_later_kept = len([oid for oid, status in moved_later_outcome.items() if status == 'kept'])
                    global_on_route = global_kept + global_received_early + global_received_later_kept

                    # Build per-window breakdown
                    window_breakdown = []
                    for win_label in window_labels_list:
                        result = window_results.get(win_label)
                        if not result or result.get('empty', False):
                            continue

                        idx = window_labels_list.index(win_label)
                        win_start, win_end = sorted_windows[idx]
                        original_orders_for_window = [o for o in valid_orders if
                                                     o['delivery_window_start'] == win_start and
                                                     o['delivery_window_end'] == win_end]
                        original_total = len(original_orders_for_window)

                        received_early_orders = [a for a in allocation_result.moved_early if a.assigned_window == win_label]
                        received_early_ids = {a.order.get('order_id') for a in received_early_orders}
                        received_later_orders = [a for a in allocation_result.moved_later if a.assigned_window == win_label]
                        received_later_ids = {a.order.get('order_id') for a in received_later_orders}
                        all_received_ids = received_early_ids | received_later_ids
                        received_count = len(received_early_orders) + len([
                            a for a in received_later_orders
                            if moved_later_outcome.get(a.order.get('order_id')) == 'kept'
                        ])

                        kept_count = len([k for k in result.get('keep', []) if k.get('order_id') not in all_received_ids])
                        on_route_count = kept_count + received_count

                        deliver_early_count = len([a for a in allocation_result.moved_early if a.original_window == win_label])
                        moved_later_out_count = len([a for a in allocation_result.moved_later if a.original_window == win_label])

                        allocator_reschedule = len([a for a in allocation_result.reschedule if a.original_window == win_label])
                        optimizer_reschedule = len([o for o in result.get('reschedule', []) if o.get('order_id') not in moved_later_by_id])
                        reschedule_count = allocator_reschedule + optimizer_reschedule

                        allocator_cancel = len([a for a in allocation_result.cancel if a.original_window == win_label])
                        optimizer_cancel = len([o for o in result.get('cancel', []) if o.get('order_id') not in moved_later_by_id])
                        cancel_count = allocator_cancel + optimizer_cancel

                        window_breakdown.append({
                            "Window": win_label,
                            f"Original Total ({global_original_total})": original_total,
                            f"🚛 On Route ({global_on_route})": on_route_count,
                            f"✅ Kept ({global_kept})": kept_count,
                            f"📥 Received ({global_received_early + global_received_later_kept})": received_count,
                            f"⏰ Deliver Early ({global_deliver_early})": deliver_early_count,
                            f"⏩ Reschedule Today ({global_moved_later})": moved_later_out_count,
                            f"📅 Reschedule ({global_reschedule})": reschedule_count,
                            f"❌ Cancel ({global_cancel})": cancel_count
                        })

                    if window_breakdown:
                        with st.expander("ℹ️ How are these values calculated?", expanded=False):
                            st.markdown("""
| Column | How it's calculated |
|--------|-------------------|
| **Original Total** | Orders from the CSV whose delivery window matches this time slot |
| **🚛 On Route** | Orders actually being delivered in this window = Kept + Received |
| **✅ Kept** | Orders originally in this window that the optimizer included on the route |
| **📥 Received** | Orders moved *into* this window — from Deliver Early (pulled forward) or Reschedule Today (pushed back from an overflowed earlier window) |
| **⏰ Deliver Early** | Orders moved *out* of this window to an earlier window (customer approved early delivery) |
| **⏩ Reschedule Today** | Orders moved *out* of this window because it was full — attempted in a later window same day |
| **📅 Reschedule** | Orders that couldn't fit any window today — need a new delivery date |
| **❌ Cancel** | Orders recommended for cancellation (too large, too far, or rescheduled too many times) |

Numbers in parentheses in each column header are the **day total** across all windows.
""")
                        breakdown_df = pd.DataFrame(window_breakdown)
                        st.dataframe(breakdown_df, use_container_width=True)

                        if global_original_total != len(valid_orders):
                            st.warning(f"⚠️ Count mismatch: Movement table shows {global_original_total} orders but CSV contained {len(valid_orders)} orders.")

                    # Global Movement Breakdowns
                    # Deliver Early breakdown
                    if allocation_result.moved_early:
                        with st.expander(f"⏰ Deliver Early ({len(allocation_result.moved_early)} orders)", expanded=False):
                            deliver_early_data = []
                            for a in allocation_result.moved_early:
                                row = create_standard_row(a.order)
                                row["From Window"] = a.original_window
                                row["To Window"] = a.assigned_window
                                row["Reason"] = a.reason
                                deliver_early_data.append(row)
                            deliver_early_df = pd.DataFrame(deliver_early_data)
                            st.dataframe(deliver_early_df, use_container_width=True)

                    # Rescheduled orders breakdown (Pass 5 rescue — within today or to new day)
                    if allocation_result.moved_later:
                        kept_count_later = len([a for a in allocation_result.moved_later if moved_later_outcome.get(a.order.get('order_id')) == 'kept'])
                        dropped_count_later = len([a for a in allocation_result.moved_later if moved_later_outcome.get(a.order.get('order_id')) == 'dropped'])
                        with st.expander(f"⏩ Reschedule for Today ({len(allocation_result.moved_later)} orders)", expanded=False):
                            moved_later_data = []
                            for a in allocation_result.moved_later:
                                oid = a.order.get('order_id')
                                outcome = moved_later_outcome.get(oid, 'unknown')
                                row = create_standard_row(a.order)
                                row["Received From"] = a.original_window
                                if outcome == 'kept':
                                    row["Disposition"] = f"Rescheduled → {a.assigned_window}"
                                elif outcome == 'dropped':
                                    row["Disposition"] = f"Reschedule to New Day (tried {a.assigned_window}, poor geographic fit)"
                                else:
                                    row["Disposition"] = "Reschedule to New Day"
                                row["Reason"] = a.reason
                                moved_later_data.append(row)
                            moved_later_df = pd.DataFrame(moved_later_data)
                            st.dataframe(moved_later_df, use_container_width=True)
                            st.caption("Original window was full — these orders were attempted in a later window. 'Reschedule to New Day' means the later window's route cluster was too far geographically.")

                    # Reschedule breakdown (allocator + optimizer, excluding moved_later orders)
                    all_reschedule_data = []

                    # Add allocator reschedules (these had no later window available)
                    for a in allocation_result.reschedule:
                        row = create_standard_row(a.order)
                        row["Original Window"] = a.original_window
                        row["Assigned Window"] = "Reschedule to new day"
                        row["Reschedule Count"] = a.order.get("priorRescheduleCount", 0) or 0
                        row["Reason"] = a.reason
                        row["Source"] = "Allocator"
                        all_reschedule_data.append(row)

                    # Add optimizer reschedules (exclude orders that were moved_later — shown in that section)
                    for win_label in window_labels_list:
                        result = window_results.get(win_label)
                        if result and not result.get('empty', False):
                            for order in result.get('reschedule', []):
                                if order.get('order_id') in moved_later_by_id:
                                    continue  # shown in Moved Later section
                                row = create_standard_row(order)
                                row["Original Window"] = win_label
                                row["Assigned Window"] = "Reschedule to new day"
                                row["Reschedule Count"] = order.get("priorRescheduleCount", 0) or 0
                                row["Reason"] = order.get("reason", "Better fit in a different window")
                                row["Source"] = "Optimizer"
                                all_reschedule_data.append(row)

                    if all_reschedule_data:
                        with st.expander(f"📅 Reschedule for New Day ({len(all_reschedule_data)} orders)", expanded=False):
                            reschedule_df = pd.DataFrame(all_reschedule_data)
                            st.dataframe(reschedule_df, use_container_width=True)

                    # Cancel breakdown (allocator + optimizer cancellations)
                    all_cancel_data = []

                    for a in allocation_result.cancel:
                        row = create_standard_row(a.order)
                        row["Original Window"] = a.original_window
                        row["Reschedule Count"] = a.order.get("priorRescheduleCount", 0) or 0
                        row["Reason"] = a.reason
                        row["Source"] = "Allocator"
                        all_cancel_data.append(row)

                    for win_label in window_labels_list:
                        result = window_results.get(win_label)
                        if result and not result.get('empty', False):
                            for order in result.get('cancel', []):
                                if order.get('order_id') in moved_later_by_id:
                                    continue  # shown in Moved Later section
                                row = create_standard_row(order)
                                row["Original Window"] = win_label
                                row["Reschedule Count"] = order.get("priorRescheduleCount", 0) or 0
                                row["Reason"] = order.get("reason", "Geographically isolated from route cluster")
                                row["Source"] = "Optimizer"
                                all_cancel_data.append(row)

                    if all_cancel_data:
                        with st.expander(f"❌ Cancel ({len(all_cancel_data)} orders)", expanded=False):
                            cancel_df = pd.DataFrame(all_cancel_data)
                            st.dataframe(cancel_df, use_container_width=True)

                    # AI VALIDATION FOR FULL DAY MODE
                    st.markdown("---")
                    st.markdown("### 🤖 AI Validation & Analysis")

                    # Check if AI is available
                    anthropic_key = config.get_anthropic_api_key()
                    ai_available = anthropic_key and anthropic_key != "YOUR_ANTHROPIC_API_KEY_HERE"

                    # Initialize validation result
                    validation_result = None

                    # Use stored AI preference from session state (not button state, which resets after rerun)
                    should_use_ai = st.session_state.get('use_ai', False)

                    if ai_available and should_use_ai:
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

                                st.success(f"✅ AI VALIDATION COMPLETED! Result length: {len(validation_result) if validation_result else 0} chars")
                                st.markdown("#### 🤖 AI Analysis")
                                st.markdown(validation_result)

                            except Exception as ai_error:
                                st.error(f"❌ AI validation error: {ai_error}")
                                import traceback
                                st.code(traceback.format_exc())
                    else:
                        st.info("💡 Enable AI (via ANTHROPIC_API_KEY in .env) to get intelligent validation of full day allocation")


                    # Update session state with AI validation result
                    # (Full data was already stored early, we're just adding the AI result now)
                    try:
                        if 'full_day_results' in st.session_state and st.session_state.full_day_results:
                            st.session_state.full_day_results['ai_validation'] = validation_result
                            result_preview = validation_result[:100] if validation_result else "None"
                            st.success(f"✅ AI VALIDATION ADDED TO SESSION STATE! Preview: {result_preview}...")
                        else:
                            st.warning("⚠️ Session state not found - AI result not saved")
                    except Exception as update_error:
                        st.error(f"❌ ERROR UPDATING AI IN SESSION STATE: {update_error}")


            # Display stored One Window results (when not running optimization but results exist in session state)
            if valid_orders and not run_optimization and mode == "One Window" and "optimization_results" in st.session_state and st.session_state.optimization_results:
                # Extract common data from session state
                results = st.session_state.optimization_results
                optimizations = results['optimizations']
                geocoded = results['geocoded']
                depot_address = results['depot_address']
                valid_orders_display = results['valid_orders']
                addresses = results['addresses']
                time_matrix = results['time_matrix']
                vehicle_capacity = results['vehicle_capacity']
                window_minutes = results['window_minutes']
                service_times = results.get('service_times', [])

                # Initialize active tab in session state (defaults to Cut 1)
                if "active_tab" not in st.session_state:
                    st.session_state.active_tab = 0

                # Build tab options dynamically based on which cuts were run
                max_orders_count = optimizations['max_orders']['orders_kept']
                tab_options = [f"✅ Cut 1: Max Orders ({max_orders_count} Orders) - RECOMMENDED"]

                if 'shortest' in optimizations:
                    shortest_orders_count = optimizations['shortest']['orders_kept']
                    tab_options.append(f"⚡ Cut 2: Shortest Route ({shortest_orders_count} Orders)")
                if 'high_density' in optimizations:
                    density_orders_count = optimizations['high_density']['orders_kept']
                    tab_options.append(f"🎯 Cut 3: High Density ({density_orders_count} Orders)")

                st.markdown("---")
                st.markdown("## 🖥️ One Window Optimization")

                # Cut selector with integrated help text
                selected_tab = st.selectbox(
                    "Select Optimization Strategy:",
                    options=tab_options,
                    index=st.session_state.active_tab,
                    key="cached_tab_selector",
                    help="Cut 1: Maximizes orders delivered within constraints (RECOMMENDED) | Cut 2: Optimizes for shortest route with 80-90% capacity | Cut 3: Maximizes delivery density in tight clusters"
                )

                # Update active tab in session state
                st.session_state.active_tab = tab_options.index(selected_tab)

                # TAB 1: MAX ORDERS (RECOMMENDED - default view)
                if st.session_state.active_tab == 0:
                    opt = optimizations['max_orders']

                    display_optimization_results(
                        keep=opt['keep'],
                        early=opt['early'],
                        reschedule=opt['reschedule'],
                        cancel=opt['cancel'],
                        kept=opt['kept'],
                        service_times=service_times,
                        geocoded=geocoded,
                        depot_address=depot_address,
                        valid_orders=valid_orders_display,
                        addresses=addresses,
                        time_matrix=time_matrix,
                        vehicle_capacity=vehicle_capacity,
                        window_minutes=window_minutes,
                        strategy_desc=opt['strategy'],
                        show_ai_explanations=True
                    )

                # TAB 2: SHORTEST ROUTE (only if Cut 2 was run)
                elif st.session_state.active_tab == 1 and 'shortest' in optimizations:
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
                        valid_orders=valid_orders_display,
                        addresses=addresses,
                        time_matrix=time_matrix,
                        vehicle_capacity=vehicle_capacity,
                        window_minutes=window_minutes,
                        strategy_desc=opt['strategy'],
                        show_ai_explanations=False
                    )

                # TAB 3: HIGH DENSITY (only if Cut 3 was run)
                # Dynamic tab index: 1 if only Cut 2, 2 if both Cut 2 and Cut 3
                elif st.session_state.active_tab >= 1 and 'high_density' in optimizations:
                    # If Cut 2 wasn't run, this is tab 1, otherwise tab 2
                    expected_tab_index = 1 if 'shortest' not in optimizations else 2
                    if st.session_state.active_tab == expected_tab_index:
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
                            valid_orders=valid_orders_display,
                            addresses=addresses,
                            time_matrix=time_matrix,
                            vehicle_capacity=vehicle_capacity,
                            window_minutes=window_minutes,
                            strategy_desc=opt['strategy'],
                            show_ai_explanations=False
                        )
            # Display stored Multiple Windows results (when not running optimization but results exist in session state)
            if valid_orders and mode == "Multiple Windows" and 'full_day_results' in st.session_state and st.session_state.full_day_results:
                try:
                    st.markdown("## 🌅 Multiple Windows Optimization")

                    # Extract stored results
                    stored = st.session_state.full_day_results

                    # Extract all needed data from session state
                    window_results = stored['window_results']
                    allocation_result = stored['allocation_result']
                    moved_later_outcome = stored.get('moved_later_outcome', {})
                    window_labels_list = stored['window_labels_list']
                    window_capacities = stored['window_capacities']
                    allocation_windows = stored['allocation_windows']
                    depot_address = stored['depot_address']
                    validation_result = stored.get('ai_validation')

                    # ── 1. GLOBAL MAP ──────────────────────────────────────────
                    st.markdown("### 🗺️ Global Route Summary Map")
                    st.markdown("All routes displayed together with color-coded windows")

                    try:
                        import folium

                        if not window_results:
                            st.warning("No routes to display on map")
                        else:
                            try:
                                window_results_by_index = {}
                                geocoded_by_window = {}
                                addresses_by_window = {}

                                for idx, win_label in enumerate(window_results.keys()):
                                    result = window_results[win_label]
                                    window_results_by_index[idx] = result
                                    geocoded_by_window[idx] = result.get('geocoded', [])
                                    addresses_by_window[idx] = result.get('addresses', [])

                                global_map = create_multi_window_map(
                                    window_results=window_results_by_index,
                                    depot_address=depot_address,
                                    addresses_by_window=addresses_by_window,
                                    geocoded_by_window=geocoded_by_window,
                                    window_labels_list=list(window_results.keys())
                                )

                                if global_map:
                                    st_folium(global_map, width=None, height=600, key="global_map")
                                    st.caption("🎨 Each color represents a different delivery window route. Routes show actual Google Maps road paths with numbered stops.")
                                else:
                                    st.warning("⚠️ Could not create map. Check that geocoding completed successfully.")
                            except Exception as inner_map_error:
                                st.error(f"❌ Error creating map: {str(inner_map_error)}")
                                import traceback
                                with st.expander("Map error details"):
                                    st.code(traceback.format_exc())
                    except Exception as map_error:
                        st.error(f"❌ Error creating map: {str(map_error)}")

                    st.markdown("---")

                    # ── 2. AI VALIDATION PLACEHOLDER (position between map and movement) ──────────
                    # Appears here immediately; AI is computed AFTER movement/per-window render
                    anthropic_key = config.get_anthropic_api_key()
                    ai_available = anthropic_key and anthropic_key != "YOUR_ANTHROPIC_API_KEY_HERE"
                    should_use_ai = stored.get('use_ai', False)
                    validation_result = stored.get('ai_validation')

                    ai_placeholder = st.empty()
                    if validation_result is None and ai_available and should_use_ai:
                        # Will be computed later — show loading indicator now so section is visible
                        ai_placeholder.info("🤖 AI Validation & Analysis — analyzing route...")
                    else:
                        # Already cached or AI not available — show final state immediately
                        with ai_placeholder:
                            with st.expander("🤖 AI Validation & Analysis", expanded=False):
                                if validation_result:
                                    st.markdown(validation_result)
                                else:
                                    st.caption("AI validation not available for this run. Enable AI (via ANTHROPIC_API_KEY in .env) and disable Test Mode to activate.")

                    st.markdown("---")

                    # ── 3. MOVEMENT BY WINDOW ───────────────────────────────────
                    st.markdown("### 📊 Movement by Window")

                    # Calculate global totals first
                    global_original_total = len(valid_orders)  # All orders from CSV

                    global_kept_temp = 0
                    global_received_early = len(allocation_result.moved_early)
                    global_deliver_early = len(allocation_result.moved_early)
                    global_moved_later = len(allocation_result.moved_later)
                    global_reschedule = len(allocation_result.reschedule)
                    global_cancel = len(allocation_result.cancel)

                    moved_later_by_id = {a.order.get('order_id'): a for a in allocation_result.moved_later}

                    for win_label in window_labels_list:
                        result = window_results.get(win_label)
                        if result and not result.get('empty', False):
                            received_early_ids = {a.order.get('order_id') for a in allocation_result.moved_early if a.assigned_window == win_label}
                            received_later_ids = {a.order.get('order_id') for a in allocation_result.moved_later if a.assigned_window == win_label}
                            all_received_ids = received_early_ids | received_later_ids
                            global_kept_temp += len([k for k in result.get('keep', []) if k.get('order_id') not in all_received_ids])
                            opt_resc = [o for o in result.get('reschedule', []) if o.get('order_id') not in moved_later_by_id]
                            opt_cancel = [o for o in result.get('cancel', []) if o.get('order_id') not in moved_later_by_id]
                            global_reschedule += len(opt_resc)
                            global_cancel += len(opt_cancel)

                    global_kept = global_kept_temp
                    global_received_later_kept = len([oid for oid, status in moved_later_outcome.items() if status == 'kept'])
                    global_on_route = global_kept + global_received_early + global_received_later_kept

                    # Build per-window breakdown
                    window_breakdown = []
                    for win_label in window_labels_list:
                        result = window_results.get(win_label)
                        if not result or result.get('empty', False):
                            continue

                        idx = window_labels_list.index(win_label)
                        win_start, win_end = sorted_windows[idx]
                        original_orders_for_window = [o for o in valid_orders if
                                                     o['delivery_window_start'] == win_start and
                                                     o['delivery_window_end'] == win_end]
                        original_total = len(original_orders_for_window)

                        received_early_orders = [a for a in allocation_result.moved_early if a.assigned_window == win_label]
                        received_early_ids = {a.order.get('order_id') for a in received_early_orders}
                        received_later_orders = [a for a in allocation_result.moved_later if a.assigned_window == win_label]
                        received_later_ids = {a.order.get('order_id') for a in received_later_orders}
                        all_received_ids = received_early_ids | received_later_ids
                        received_count = len(received_early_orders) + len([
                            a for a in received_later_orders
                            if moved_later_outcome.get(a.order.get('order_id')) == 'kept'
                        ])

                        kept_count = len([k for k in result.get('keep', []) if k.get('order_id') not in all_received_ids])
                        on_route_count = kept_count + received_count

                        deliver_early_count = len([a for a in allocation_result.moved_early if a.original_window == win_label])
                        moved_later_out_count = len([a for a in allocation_result.moved_later if a.original_window == win_label])

                        allocator_reschedule = len([a for a in allocation_result.reschedule if a.original_window == win_label])
                        optimizer_reschedule = len([o for o in result.get('reschedule', []) if o.get('order_id') not in moved_later_by_id])
                        reschedule_count = allocator_reschedule + optimizer_reschedule

                        allocator_cancel = len([a for a in allocation_result.cancel if a.original_window == win_label])
                        optimizer_cancel = len([o for o in result.get('cancel', []) if o.get('order_id') not in moved_later_by_id])
                        cancel_count = allocator_cancel + optimizer_cancel

                        window_breakdown.append({
                            "Window": win_label,
                            f"Original Total ({global_original_total})": original_total,
                            f"🚛 On Route ({global_on_route})": on_route_count,
                            f"✅ Kept ({global_kept})": kept_count,
                            f"📥 Received ({global_received_early + global_received_later_kept})": received_count,
                            f"⏰ Deliver Early ({global_deliver_early})": deliver_early_count,
                            f"⏩ Reschedule Today ({global_moved_later})": moved_later_out_count,
                            f"📅 Reschedule ({global_reschedule})": reschedule_count,
                            f"❌ Cancel ({global_cancel})": cancel_count
                        })

                    if window_breakdown:
                        with st.expander("ℹ️ How are these values calculated?", expanded=False):
                            st.markdown("""
| Column | How it's calculated |
|--------|-------------------|
| **Original Total** | Orders from the CSV whose delivery window matches this time slot |
| **🚛 On Route** | Orders actually being delivered in this window = Kept + Received |
| **✅ Kept** | Orders originally in this window that the optimizer included on the route |
| **📥 Received** | Orders moved *into* this window — from Deliver Early (pulled forward) or Reschedule Today (pushed back from an overflowed earlier window) |
| **⏰ Deliver Early** | Orders moved *out* of this window to an earlier window (customer approved early delivery) |
| **⏩ Reschedule Today** | Orders moved *out* of this window because it was full — attempted in a later window same day |
| **📅 Reschedule** | Orders that couldn't fit any window today — need a new delivery date |
| **❌ Cancel** | Orders recommended for cancellation (too large, too far, or rescheduled too many times) |

Numbers in parentheses in each column header are the **day total** across all windows.
""")
                        breakdown_df = pd.DataFrame(window_breakdown)
                        st.dataframe(breakdown_df, use_container_width=True)

                        if global_original_total != len(valid_orders):
                            st.warning(f"⚠️ Count mismatch: Movement table shows {global_original_total} orders but CSV contained {len(valid_orders)} orders.")

                    # Global Movement Breakdowns
                    def _reorder_reason(df):
                        """Move 'Reason' column to appear right after 'numberOfUnits'."""
                        if 'Reason' in df.columns and 'numberOfUnits' in df.columns:
                            c = list(df.columns)
                            c.remove('Reason')
                            c.insert(c.index('numberOfUnits') + 1, 'Reason')
                            return df[c]
                        return df

                    # Deliver Early breakdown
                    if allocation_result.moved_early:
                        with st.expander(f"⏰ Deliver Early ({len(allocation_result.moved_early)} orders)", expanded=False):
                            deliver_early_data = []
                            for a in allocation_result.moved_early:
                                row = create_standard_row(a.order)
                                row["From Window"] = a.original_window
                                row["To Window"] = a.assigned_window
                                row["Reason"] = a.reason
                                deliver_early_data.append(row)
                            deliver_early_df = _reorder_reason(pd.DataFrame(deliver_early_data))
                            st.dataframe(deliver_early_df, use_container_width=True)

                    # Rescheduled orders breakdown (Pass 5 rescue — within today or to new day)
                    if allocation_result.moved_later:
                        kept_count_later = len([a for a in allocation_result.moved_later if moved_later_outcome.get(a.order.get('order_id')) == 'kept'])
                        dropped_count_later = len([a for a in allocation_result.moved_later if moved_later_outcome.get(a.order.get('order_id')) == 'dropped'])
                        with st.expander(f"⏩ Reschedule for Today ({len(allocation_result.moved_later)} orders)", expanded=False):
                            moved_later_data = []
                            for a in allocation_result.moved_later:
                                oid = a.order.get('order_id')
                                outcome = moved_later_outcome.get(oid, 'unknown')
                                row = create_standard_row(a.order)
                                row["Received From"] = a.original_window
                                if outcome == 'kept':
                                    row["Disposition"] = f"Rescheduled → {a.assigned_window}"
                                elif outcome == 'dropped':
                                    row["Disposition"] = f"Reschedule to New Day (tried {a.assigned_window}, poor geographic fit)"
                                else:
                                    row["Disposition"] = "Reschedule to New Day"
                                row["Reason"] = a.reason
                                moved_later_data.append(row)
                            moved_later_df = _reorder_reason(pd.DataFrame(moved_later_data))
                            st.dataframe(moved_later_df, use_container_width=True)
                            st.caption("Original window was full — these orders were attempted in a later window. 'Reschedule to New Day' means the later window's route cluster was too far geographically.")

                    # Reschedule breakdown (allocator + optimizer, excluding moved_later orders)
                    all_reschedule_data = []

                    for a in allocation_result.reschedule:
                        row = create_standard_row(a.order)
                        row["Original Window"] = a.original_window
                        row["Assigned Window"] = "Reschedule to new day"
                        row["Reschedule Count"] = a.order.get("priorRescheduleCount", 0) or 0
                        row["Reason"] = a.reason
                        row["Source"] = "Allocator"
                        all_reschedule_data.append(row)

                    for win_label in window_labels_list:
                        result = window_results.get(win_label)
                        if result and not result.get('empty', False):
                            for order in result.get('reschedule', []):
                                if order.get('order_id') in moved_later_by_id:
                                    continue  # shown in Moved Later section
                                row = create_standard_row(order)
                                row["Original Window"] = win_label
                                row["Assigned Window"] = "Reschedule to new day"
                                row["Reschedule Count"] = order.get("priorRescheduleCount", 0) or 0
                                row["Reason"] = order.get("reason", "Better fit in a different window")
                                row["Source"] = "Optimizer"
                                all_reschedule_data.append(row)

                    if all_reschedule_data:
                        with st.expander(f"📅 Reschedule for New Day ({len(all_reschedule_data)} orders)", expanded=False):
                            reschedule_df = _reorder_reason(pd.DataFrame(all_reschedule_data))
                            st.dataframe(reschedule_df, use_container_width=True)

                    # Cancel breakdown (allocator + optimizer cancellations)
                    all_cancel_data = []

                    for a in allocation_result.cancel:
                        row = create_standard_row(a.order)
                        row["Original Window"] = a.original_window
                        row["Reschedule Count"] = a.order.get("priorRescheduleCount", 0) or 0
                        row["Reason"] = a.reason
                        row["Source"] = "Allocator"
                        all_cancel_data.append(row)

                    for win_label in window_labels_list:
                        result = window_results.get(win_label)
                        if result and not result.get('empty', False):
                            for order in result.get('cancel', []):
                                if order.get('order_id') in moved_later_by_id:
                                    continue  # shown in Moved Later section
                                row = create_standard_row(order)
                                row["Original Window"] = win_label
                                row["Reschedule Count"] = order.get("priorRescheduleCount", 0) or 0
                                row["Reason"] = order.get("reason", "Geographically isolated from route cluster")
                                row["Source"] = "Optimizer"
                                all_cancel_data.append(row)

                    if all_cancel_data:
                        with st.expander(f"❌ Cancel ({len(all_cancel_data)} orders)", expanded=False):
                            cancel_df = _reorder_reason(pd.DataFrame(all_cancel_data))
                            st.dataframe(cancel_df, use_container_width=True)

                    st.markdown("---")

                    # Show per-window results
                    st.markdown("### 🚛 Per-Window Optimization Results")

                    for i, (win_start, win_end) in enumerate(allocation_windows):
                        win_label = window_labels_list[i]
                        result = window_results.get(win_label)

                        if not result:
                            with st.expander(f"**{win_label}** — No orders assigned", expanded=False):
                                st.info("No orders were assigned to this window after allocation.")
                            continue

                        # Pre-compute metrics for header and info bar
                        from allocator import window_duration_minutes
                        win_duration = window_duration_minutes(win_start, win_end)
                        win_capacity = window_capacities.get(win_label, 0)
                        kept_units = result['total_units']
                        route_time = result.get('route_time', 0)
                        capacity_pct = (kept_units / win_capacity * 100) if win_capacity > 0 else 0

                        moved_early_into_window = [a for a in allocation_result.moved_early if a.assigned_window == win_label]
                        moved_later_into_window = [a for a in allocation_result.moved_later if a.assigned_window == win_label]
                        moved_early_ids = {a.order.get('order_id') for a in moved_early_into_window}
                        moved_later_ids = {a.order.get('order_id') for a in moved_later_into_window}
                        all_received_ids = moved_early_ids | moved_later_ids

                        orders_kept_stayed = sum(1 for k in result['keep'] if k.get('order_id') not in all_received_ids)
                        orders_added_received = sum(1 for k in result['keep'] if k.get('order_id') in all_received_ids)
                        total_on_route = orders_kept_stayed + orders_added_received
                        efficiency = (total_on_route / (route_time / 60)) if route_time > 0 else 0

                        win_service_times = result.get('service_times', [])
                        total_service_time = sum(
                            win_service_times[k['node']] for k in result['keep']
                            if k.get('node', 0) < len(win_service_times)
                        )
                        drive_time = max(0, route_time - total_service_time)

                        # Dead leg = depot→first stop + last stop→depot
                        win_time_matrix = result.get('time_matrix', [])
                        dead_leg_time = 0
                        if result['keep'] and win_time_matrix:
                            sorted_keep_nodes = [k['node'] for k in sorted(result['keep'], key=lambda x: x.get('sequence_index', 0))]
                            dead_leg_time = win_time_matrix[0][sorted_keep_nodes[0]] + win_time_matrix[sorted_keep_nodes[-1]][0]

                        _header = (
                            f"**{win_label}**  —  {total_on_route} orders"
                            f"  ·  {kept_units}/{win_capacity} units ({capacity_pct:.0f}%)"
                            f"  ·  {route_time} min ({drive_time} drive + {total_service_time} service)"
                            f"  ·  {dead_leg_time} min dead leg"
                            f"  ·  {efficiency:.1f} orders/hr"
                        )

                        with st.expander(_header, expanded=True):

                            # On Route table — columns: Seq | Order ID | Customer | Address | Est Arrival | Service Time | Origin | Reason | Tag | Units | Early | Window
                            if result['keep']:
                                st.markdown(f"#### 🚛 On Route ({len(result['keep'])} orders)")

                                # Build reason lookup for kept/received orders
                                _kept_reason = {a.order.get('order_id'): a.reason for a in allocation_result.kept_in_window}
                                _received_reason = {a.order.get('order_id'): a.reason for a in moved_early_into_window}
                                _received_reason.update({a.order.get('order_id'): a.reason for a in moved_later_into_window})

                                keep_data = []
                                for k in sorted(result['keep'], key=lambda x: x.get("sequence_index", 0)):
                                    order_data = create_standard_row(k)
                                    node = k.get('node', 0)
                                    service_time = win_service_times[node] if 0 < node < len(win_service_times) else 0
                                    arrival_min = k.get('estimated_arrival', 0)

                                    oid = k.get('order_id')
                                    if oid in moved_early_ids:
                                        origin = "⏰ Moved Early"
                                        reason = _received_reason.get(oid, "")
                                    elif oid in moved_later_ids:
                                        origin = "⏩ Pushed Later"
                                        reason = _received_reason.get(oid, "")
                                    else:
                                        origin = "🏠 Original"
                                        reason = _kept_reason.get(oid, "Fits in original window")

                                    row = {
                                        "Seq": k.get("sequence_index", 0) + 1,
                                        "externalOrderId": order_data.get("externalOrderId", ""),
                                        "customerID": order_data.get("customerID", ""),
                                        "address": order_data.get("address", ""),
                                        "Est Arrival": f"+{arrival_min} min",
                                        "Service Time": f"{service_time} min",
                                        "Origin": origin,
                                        "Reason": reason,
                                        "customerTag": order_data.get("customerTag", ""),
                                        "numberOfUnits": order_data.get("numberOfUnits", 0),
                                        "earlyEligible": order_data.get("earlyEligible", "false"),
                                        "deliveryWindow": order_data.get("deliveryWindow", ""),
                                    }
                                    keep_data.append(row)
                                keep_df = pd.DataFrame(keep_data)
                                st.dataframe(keep_df, use_container_width=True)

                            # Show combined movement details for orders that MOVED OUT of this window
                            delivered_early_from_window = [a for a in allocation_result.moved_early if a.original_window == win_label]
                            rescheduled_from_window = [a for a in allocation_result.reschedule if a.original_window == win_label]
                            cancelled_from_window = [a for a in allocation_result.cancel if a.original_window == win_label]

                            total_moved_out = len(delivered_early_from_window) + len(rescheduled_from_window) + len(cancelled_from_window)

                            if total_moved_out > 0:
                                with st.expander(f"📤 Moved Out of Window ({total_moved_out} orders)", expanded=False):
                                    moved_out_data = []

                                    # Add deliver early orders
                                    for a in delivered_early_from_window:
                                        row = create_standard_row(a.order)
                                        row["Action"] = "⏰ Deliver Early"
                                        row["Moved To"] = a.assigned_window
                                        row["Reason"] = a.reason
                                        moved_out_data.append(row)

                                    # Add reschedule orders
                                    for a in rescheduled_from_window:
                                        row = create_standard_row(a.order)
                                        row["Action"] = "📅 Reschedule"
                                        row["Moved To"] = "Later window/date"
                                        row["Reschedule Count"] = a.order.get("priorRescheduleCount", 0) or 0
                                        row["Reason"] = a.reason
                                        moved_out_data.append(row)

                                    # Add cancel orders
                                    for a in cancelled_from_window:
                                        row = create_standard_row(a.order)
                                        row["Action"] = "❌ Cancel"
                                        row["Moved To"] = "N/A"
                                        row["Reschedule Count"] = a.order.get("priorRescheduleCount", 0) or 0
                                        row["Reason"] = a.reason
                                        moved_out_data.append(row)

                                    moved_out_df = _reorder_reason(pd.DataFrame(moved_out_data))
                                    st.dataframe(moved_out_df, use_container_width=True)

                    # ── 5. AI COMPUTATION (runs after movement/per-window — updates placeholder at position 2) ──
                    if validation_result is None and ai_available and should_use_ai:
                        try:
                            validation_context = f"""FULL DAY OPTIMIZATION ANALYSIS

Total Orders: {len(valid_orders)}
Windows: {len(allocation_windows)}

ALLOCATION SUMMARY:
- Kept in original window: {len(allocation_result.kept_in_window)}
- Moved to earlier window: {len(allocation_result.moved_early)}
- Recommended for reschedule: {len(allocation_result.reschedule)}
- Recommended for cancel: {len(allocation_result.cancel)}

PRIORITY CUSTOMER HANDLING:
"""
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
                                for move in allocation_result.moved_early[:5]:
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
                                for resc in allocation_result.reschedule[:3]:
                                    count = resc.order.get('priorRescheduleCount', 0) or 0
                                    validation_context += f"  • Order {resc.order['order_id']}: {resc.order['units']} units, reschedule count: {count}\n"

                            if allocation_result.cancel:
                                validation_context += f"- {len(allocation_result.cancel)} orders recommended for cancel\n"
                                for canc in allocation_result.cancel[:3]:
                                    count = canc.order.get('priorRescheduleCount', 0) or 0
                                    validation_context += f"  • Order {canc.order['order_id']}: {canc.order['units']} units, reschedule count: {count}\n"

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
                            st.session_state.full_day_results['ai_validation'] = validation_result
                        except Exception as ai_error:
                            st.error(f"❌ AI validation error: {ai_error}")
                            import traceback
                            st.code(traceback.format_exc())

                        # Replace the loading indicator at position 2 with the actual result
                        with ai_placeholder:
                            with st.expander("🤖 AI Validation & Analysis", expanded=True):
                                if validation_result:
                                    st.markdown(validation_result)
                                else:
                                    st.caption("AI validation encountered an error during analysis.")

                except Exception as cache_error:
                    st.error(f"❌ Error displaying cached Multiple Windows results: {cache_error}")
                    import traceback
                    st.code(traceback.format_exc())

        except Exception as e:
            st.error(f"❌ Error processing file: {e}")
            import traceback
            with st.expander("Error details"):
                st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
