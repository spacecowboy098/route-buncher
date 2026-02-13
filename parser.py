"""
CSV parsing and validation for order data.
"""

from typing import List, Dict, Tuple
from datetime import datetime
import pandas as pd


def parse_csv(file) -> Tuple[List[Dict], int]:
    """
    Parse uploaded CSV file and extract order data.

    Expected CSV columns:
    - orderID
    - customer_name
    - delivery_address
    - number_of_units
    - early_ok
    - delivery_window_start
    - delivery_window_end

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
        - window_minutes: int (length of delivery window)

    Raises:
        ValueError: If CSV is missing required columns
    """
    # Read CSV
    df = pd.read_csv(file)

    # Check required columns
    required_columns = [
        "orderID",
        "customer_name",
        "delivery_address",
        "number_of_units",
        "early_ok",
        "delivery_window_start",
        "delivery_window_end"
    ]

    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"CSV missing required columns: {', '.join(missing_columns)}")

    # Parse orders
    orders = []
    window_minutes = None

    for _, row in df.iterrows():
        # Parse early_ok as boolean
        early_ok_str = str(row["early_ok"]).strip().lower()
        early_delivery_ok = early_ok_str in ["yes", "y", "true", "1"]

        # Parse time windows
        try:
            window_start = datetime.strptime(str(row["delivery_window_start"]).strip(), "%I:%M %p").time()
            window_end = datetime.strptime(str(row["delivery_window_end"]).strip(), "%I:%M %p").time()
        except ValueError as e:
            raise ValueError(
                f"Error parsing time for order {row['orderID']}: {e}. "
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
            print(f"Warning: Order {row['orderID']} has different window duration ({order_window_minutes} min vs {window_minutes} min)")

        # Create order dict
        order = {
            "order_id": str(row["orderID"]),
            "customer_name": str(row["customer_name"]),
            "delivery_address": str(row["delivery_address"]),
            "units": int(row["number_of_units"]),
            "early_delivery_ok": early_delivery_ok,
            "delivery_window_start": window_start,
            "delivery_window_end": window_end
        }

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
