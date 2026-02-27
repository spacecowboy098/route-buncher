"""
PostgreSQL database module for The Buncher.

Fetches stores and orders from a PostgreSQL database, returning data in the
same internal format that parser.parse_csv() produces so the rest of the app
works unchanged.

Expected table schema (flat orders table):
    orders (
        store_id                  VARCHAR  NOT NULL,
        store_name                VARCHAR  NOT NULL,
        external_order_id         VARCHAR,
        customer_id               VARCHAR,
        address                   TEXT,
        customer_tag              VARCHAR,
        number_of_units           INTEGER,
        early_eligible            BOOLEAN  DEFAULT FALSE,
        delivery_window_start     TIMESTAMP,
        delivery_window_end       TIMESTAMP,
        -- optional fields:
        order_status              VARCHAR,
        delivery_date             DATE,
        prior_reschedule_count    INTEGER  DEFAULT 0,
        fulfillment_location_address TEXT,
        run_id                    VARCHAR
    )
"""

from typing import List, Dict, Any

import psycopg2
import psycopg2.extras

import config


def _get_connection() -> psycopg2.extensions.connection:
    """Open and return a new psycopg2 connection using DATABASE_URL from config."""
    url = config.get_database_url()
    return psycopg2.connect(url)


def get_stores() -> List[Dict[str, str]]:
    """
    Return all distinct stores from the database, sorted by name.

    Returns:
        List of dicts: [{"id": "store-001", "name": "Meijer Plymouth MN"}, ...]

    Raises:
        Exception: If the database query fails
    """
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT DISTINCT store_id, store_name "
                "FROM orders "
                "ORDER BY store_name"
            )
            rows = cur.fetchall()
        return [{"id": row["store_id"], "name": row["store_name"]} for row in rows]
    finally:
        conn.close()


def get_orders_for_store(store_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all orders for the given store and return them in the same format
    that parser.parse_csv() uses internally.

    Args:
        store_id: The store_id value to filter by

    Returns:
        List of order dicts matching the internal app format:
        {
            'order_id':               str,       # externalOrderId
            'customer_name':          str,       # customerID
            'delivery_address':       str,       # address
            'units':                  int,       # numberOfUnits
            'early_delivery_ok':      bool,      # earlyEligible
            'delivery_window_start':  datetime,  # from delivery_window_start column
            'delivery_window_end':    datetime,  # from delivery_window_end column
            'customer_tag':           str,       # customerTag (may be empty)
            # optional fields (included only when present):
            'order_status':           str,
            'delivery_date':          date,
            'prior_reschedule_count': int,
            'fulfillment_location_address': str,
            'run_id':                 str,
        }

    Raises:
        Exception: If the database query fails
    """
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT * FROM orders WHERE store_id = %s",
                (store_id,)
            )
            rows = cur.fetchall()

        orders = []
        for row in rows:
            order: Dict[str, Any] = {
                "order_id":             _str(row, "external_order_id"),
                "customer_name":        _str(row, "customer_id"),
                "delivery_address":     _str(row, "address"),
                "units":                _int(row, "number_of_units", default=0),
                "early_delivery_ok":    _bool(row, "early_eligible", default=False),
                "delivery_window_start": row["delivery_window_start"],
                "delivery_window_end":   row["delivery_window_end"],
                "customer_tag":         _str(row, "customer_tag"),
            }

            # Optional fields — only include when the column exists and is non-null
            for db_col, app_key in [
                ("order_status",               "order_status"),
                ("delivery_date",              "delivery_date"),
                ("prior_reschedule_count",     "prior_reschedule_count"),
                ("fulfillment_location_address", "fulfillment_location_address"),
                ("run_id",                     "run_id"),
            ]:
                val = _safe_get(row, db_col)
                if val is not None:
                    order[app_key] = val

            orders.append(order)

        return orders
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_get(row: psycopg2.extras.DictRow, key: str):
    """Return row[key] or None if the column doesn't exist."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _str(row, key: str, default: str = "") -> str:
    val = _safe_get(row, key)
    return str(val) if val is not None else default


def _int(row, key: str, default: int = 0) -> int:
    val = _safe_get(row, key)
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _bool(row, key: str, default: bool = False) -> bool:
    val = _safe_get(row, key)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("true", "1", "yes", "t")
