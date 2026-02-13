"""
CSV parsing and validation for order data.
"""

from typing import List, Dict, Tuple
from datetime import datetime
import pandas as pd


def parse_csv(file) -> Tuple[List[Dict], int]:
    """
    Parse uploaded CSV file and extract order data.

    Expected CSV columns (new format):
    - externalOrderId (or orderID for legacy format)
    - customerID (or customer_name for legacy format)
    - address (or delivery_address for legacy format)
    - numberOfUnits (or number_of_units for legacy format)
    - earlyEligible (or early_ok for legacy format)
    - deliveryWindow (combined, e.g., "09:00 AM 11:00 AM") or delivery_window_start + delivery_window_end
    - Additional optional fields: orderId, runId, orderStatus, customerTag, deliveryDate,
      priorRescheduleCount, fulfillmentLocation, fulfillmentGeo, fulfillmentLocationAddress, extendedCutOffTime

    Args:
        file: File object from Streamlit file uploader

    Returns:
        Tuple of (orders, window_minutes) where:
        - orders: List of order dicts with fields:
            - order_id: str
            - customer_name: str
            - delivery_address: str
            - units: int
            - early_delivery_ok: bool
            - delivery_window_start: datetime.time
            - delivery_window_end: datetime.time
            - Plus all additional fields from the CSV
        - window_minutes: int (length of delivery window)

    Raises:
        ValueError: If CSV is missing required columns
    """
    # Read CSV
    df = pd.read_csv(file)

    # Detect format (new vs legacy)
    is_new_format = "externalOrderId" in df.columns
    is_legacy_format = "orderID" in df.columns

    if not is_new_format and not is_legacy_format:
        raise ValueError("CSV must contain either 'externalOrderId' (new format) or 'orderID' (legacy format)")

    # Define column mappings
    if is_new_format:
        required_columns = {
            "order_id": "externalOrderId",
            "customer_name": "customerID",
            "delivery_address": "address",
            "units": "numberOfUnits",
            "early_ok": "earlyEligible",
            "delivery_window": "deliveryWindow"
        }
    else:
        required_columns = {
            "order_id": "orderID",
            "customer_name": "customer_name",
            "delivery_address": "delivery_address",
            "units": "number_of_units",
            "early_ok": "early_ok",
            "delivery_window_start": "delivery_window_start",
            "delivery_window_end": "delivery_window_end"
        }

    # Check required columns exist in CSV
    missing_columns = [csv_col for csv_col in required_columns.values() if csv_col not in df.columns]
    if missing_columns:
        raise ValueError(f"CSV missing required columns: {', '.join(missing_columns)}")

    # Parse orders
    orders = []
    window_minutes = None

    for _, row in df.iterrows():
        # Parse early_ok as boolean
        early_col = required_columns["early_ok"]
        if pd.isna(row[early_col]) or str(row[early_col]).strip() == "":
            early_delivery_ok = False
        else:
            early_ok_str = str(row[early_col]).strip().lower()
            early_delivery_ok = early_ok_str in ["yes", "y", "true", "1", "true"]

        # Parse time windows
        order_id_col = required_columns["order_id"]
        try:
            if is_new_format:
                # Parse combined deliveryWindow field (e.g., "09:00 AM 11:00 AM")
                window_str = str(row["deliveryWindow"]).strip()
                window_parts = window_str.split()
                if len(window_parts) == 4:
                    # Format: "HH:MM AM HH:MM PM"
                    start_str = f"{window_parts[0]} {window_parts[1]}"
                    end_str = f"{window_parts[2]} {window_parts[3]}"
                    window_start = datetime.strptime(start_str, "%I:%M %p").time()
                    window_end = datetime.strptime(end_str, "%I:%M %p").time()
                else:
                    raise ValueError(f"deliveryWindow format invalid: '{window_str}'. Expected 'HH:MM AM HH:MM PM'")
            else:
                # Parse separate start/end fields (legacy format)
                window_start = datetime.strptime(str(row["delivery_window_start"]).strip(), "%I:%M %p").time()
                window_end = datetime.strptime(str(row["delivery_window_end"]).strip(), "%I:%M %p").time()
        except ValueError as e:
            raise ValueError(
                f"Error parsing time for order {row[order_id_col]}: {e}. "
                "Expected format: 'HH:MM AM/PM' (e.g., '09:00 AM')"
            )

        # Calculate window duration in minutes
        # Convert times to minutes since midnight
        start_minutes = window_start.hour * 60 + window_start.minute
        end_minutes = window_end.hour * 60 + window_end.minute
        order_window_minutes = end_minutes - start_minutes

        # Set window_minutes from first order (assume all orders have same window)
        if window_minutes is None:
            window_minutes = order_window_minutes
        elif window_minutes != order_window_minutes:
            # Warn if windows differ, but continue
            print(f"Warning: Order {row[order_id_col]} has different window duration ({order_window_minutes} min vs {window_minutes} min)")

        # Create order dict with core fields
        order = {
            "order_id": str(row[required_columns["order_id"]]),
            "customer_name": str(row[required_columns["customer_name"]]),
            "delivery_address": str(row[required_columns["delivery_address"]]),
            "units": int(row[required_columns["units"]]),
            "early_delivery_ok": early_delivery_ok,
            "delivery_window_start": window_start,
            "delivery_window_end": window_end
        }

        # Add all additional fields from the CSV for future use
        if is_new_format:
            # Store all extra fields from new format
            optional_fields = [
                "orderId", "runId", "orderStatus", "customerTag", "customerID",
                "deliveryDate", "priorRescheduleCount", "fulfillmentLocation",
                "fulfillmentGeo", "fulfillmentLocationAddress", "extendedCutOffTime"
            ]
            for field in optional_fields:
                if field in df.columns:
                    order[field] = row[field] if not pd.isna(row[field]) else None

        orders.append(order)

    return orders, window_minutes


def validate_orders(orders: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """
    Validate order data and return valid orders and error messages.

    Args:
        orders: List of order dicts from parse_csv()

    Returns:
        Tuple of (valid_orders, errors) where:
        - valid_orders: List of orders that passed validation
        - errors: List of human-readable error messages

    Validation rules:
    - delivery_address must be non-empty
    - units must be a positive integer
    """
    valid_orders = []
    errors = []

    for order in orders:
        order_id = order.get("order_id", "Unknown")
        is_valid = True
        order_errors = []

        # Check delivery address
        if not order.get("delivery_address") or str(order["delivery_address"]).strip() == "":
            order_errors.append("delivery_address is empty")
            is_valid = False

        # Check units
        units = order.get("units")
        if units is None or not isinstance(units, int) or units <= 0:
            order_errors.append(f"units must be a positive integer (got: {units})")
            is_valid = False

        if is_valid:
            valid_orders.append(order)
        else:
            error_msg = f"Order {order_id}: {'; '.join(order_errors)}"
            errors.append(error_msg)

    return valid_orders, errors
