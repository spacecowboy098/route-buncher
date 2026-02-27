"""
PostgreSQL database fetcher for order data.

Fetches orders from configured databases using a static store configuration.
Store config is defined via the STORES_CONFIG environment variable as a JSON array.

Expected STORES_CONFIG format:
[
  {
    "id": "store_208",
    "name": "Lincoln Park - 208",
    "db": 1,
    "runs_table": "runs",
    "orders_table": "orders",
    "filter": {"fulfillmentLocation": "208"},

    --- Fields required for fetch_run_orders() ---
    "db_store_id": 208,          integer storeId in the runs table
    "orders_db": 2,              DB number that holds the orders (default: same as db)
    "store_table": "store",      store table in the runs DB (default: "store")
    "orders_schema": "meijer_schema"  schema prefix for order tables (default: "meijer_schema")
  },
  ...
]

Environment variables required:
  DB_1_URL - PostgreSQL connection URL for database 1 (e.g. postgresql://user:pass@host:5432/dbname)
  DB_2_URL - PostgreSQL connection URL for database 2
  DB_3_URL - PostgreSQL connection URL for database 3 (if orders live in a third DB)
  STORES_CONFIG - JSON array of store configuration objects
"""

import json
from typing import List, Dict, Tuple, Optional
from datetime import date, datetime, time as time_type

import psycopg2
import psycopg2.extras
import pytz

import config


def get_db_connection(db_num: int):
    """
    Create a PostgreSQL connection for the specified database number.

    Args:
        db_num: Database number (1 or 2)

    Returns:
        psycopg2 connection object

    Raises:
        ValueError: If the DB URL is not configured
    """
    db_url = config.get_db_url(db_num)
    if not db_url:
        raise ValueError(
            f"DB_{db_num}_URL is not configured. "
            f"Add DB_{db_num}_URL=postgresql://user:pass@host:5432/dbname to your .env file."
        )
    print(f"Connecting to DB_{db_num} with URL: {db_url}")
    return psycopg2.connect(db_url)


def get_stores_config() -> List[Dict]:
    """
    Load the static store configuration from the STORES_CONFIG environment variable.

    Returns:
        List of store config dicts. Each dict has:
          - id (str): unique store identifier
          - name (str): display name shown in the dropdown
          - db (int): which database to connect to (1 or 2)
          - runs_table (str): table that holds run/timeslot records
          - orders_table (str): table that holds order records
          - filter (dict): column→value pairs to filter the runs table query

    Raises:
        ValueError: If STORES_CONFIG is missing or contains invalid JSON
    """
    stores_json = config.get_secret("STORES_CONFIG", "[]")
    try:
        stores = json.loads(stores_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"STORES_CONFIG is not valid JSON: {e}")

    if not isinstance(stores, list):
        raise ValueError("STORES_CONFIG must be a JSON array of store objects.")

    return stores


def _query_timeslots(cur, store_ids: List[str], utc_start: datetime, utc_end: datetime) -> List[Dict]:
    """Fetch active run timeslots for the given stores and UTC date range (DB1)."""
    placeholders = ", ".join(["%s"] * len(store_ids))
    cur.execute(
        f"""
        SELECT
            r.id,
            r."deliveryDate",
            r."storeId",
            s."address",
            s.name AS "storeName",
            r."extendedCutOffTime",
            r."dropOffStartTime" AS "delivery_window_start",
            r."dropOffEndTime"   AS "delivery_window_end",
            ST_Y(s.location)    AS "storeLat",
            ST_X(s.location)    AS "storeLon"
        FROM "runs" r
        JOIN stores s ON r."storeId" = s.id
        WHERE r."deliveryDate" >= %s
          AND r."deliveryDate" <  %s
          AND r."storeId" IN ({placeholders})
          AND r."runStatus" IN ('notStarted', 'atLocation')
        """,
        (utc_start, utc_end) + tuple(store_ids),
    )
    return cur.fetchall()


def _query_orders(meijer_cur, timeslot_ids: List[str]) -> List[Dict]:
    """Fetch non-cancelled orders for the given timeslot IDs (DB2)."""
    placeholders = ", ".join(["%s"] * len(timeslot_ids))
    meijer_cur.execute(
        f"""
        SELECT
            o.id                                                          AS "orderId",
            o."externalOrderId",
            o."timeSlotId",
            o."status"                                                    AS "orderStatus",
            uoi."customerTag",
            CONCAT_WS(' ', da.line1, da.city, da.state, da.zip)          AS "customerAddress",
            da."addressId",
            o."preferEarlyDelivery"                                       AS "earlyEligible",
            uoi."organizationId"                                          AS "customerID",
            COALESCE((o."extraInfo" -> 'reschedule' ->> 'count')::integer, 0) AS "priorRescheduleCount"
        FROM "order" o
        JOIN "delivery_address" da       ON da."id" = o."deliveryAddressId"
        JOIN "user_organization_info" uoi ON uoi."id" = o."userOrganizationInfoId"
        WHERE o."timeSlotId" IN ({placeholders})
          AND o."status" != 'cancelled'
        ORDER BY o."createdAt" DESC
        """,
        timeslot_ids,
    )
    return meijer_cur.fetchall()


def _query_quantity_map(meijer_cur, order_ids: List) -> Dict[str, int]:
    """Return a map of orderId → total active units (DB2)."""
    meijer_cur.execute(
        """
        SELECT di."orderId", SUM(di.quantity) AS "totalQuantity"
        FROM delivery_item di
        WHERE di.active = true
          AND di."orderId" = ANY(%s::uuid[])
        GROUP BY di."orderId"
        """,
        (order_ids,),
    )
    return {str(row["orderId"]): row["totalQuantity"] for row in meijer_cur.fetchall()}


def _query_store_map(meijer_cur, store_ids: List[str]) -> Dict[str, Dict]:
    """Return a map of bunchaStoreId → store row (DB2)."""
    meijer_cur.execute(
        'SELECT * FROM stores s WHERE s."bunchaStoreId" = ANY(%s)',
        (store_ids,),
    )
    return {str(row["bunchaStoreId"]): row for row in meijer_cur.fetchall()}


def _query_address_geo_map(cur, address_ids: List[int]) -> Dict[str, Dict]:
    """Return a map of addressId → {lat, lng} from external_addresses (DB1)."""
    if not address_ids:
        return {}
    cur.execute(
        """
        SELECT id, ST_Y(location) AS lat, ST_X(location) AS lng
        FROM external_addresses
        WHERE id = ANY(%s)
        """,
        (address_ids,),
    )
    return {
        str(row["id"]): {
            "lat": float(row["lat"]) if row["lat"] is not None else None,
            "lng": float(row["lng"]) if row["lng"] is not None else None,
        }
        for row in cur.fetchall()
    }


def fetch_orders_for_stores(
    store_ids: List[str],
    utc_start: Optional[datetime] = None,
    utc_end: Optional[datetime] = None,
    tz_name: str = "UTC",
) -> Tuple[List[Dict], Optional[int]]:
    """
    Fetch orders from PostgreSQL for the selected stores and delivery date range.

    Args:
        store_ids:  List of store IDs to fetch (must match ids in STORES_CONFIG)
        utc_start:  Start of the delivery window in UTC (inclusive)
        utc_end:    End of the delivery window in UTC (exclusive)
        tz_name:    Timezone name for localising display strings

    Returns:
        Tuple of (orders, window_minutes) matching the format of parser.parse_csv()

    Raises:
        ValueError: If utc_start / utc_end are missing
        Exception:  If a database connection or query fails
    """
    if utc_start is None or utc_end is None:
        raise ValueError("utc_start and utc_end must be provided for fetch_orders_for_stores")

    runerra_conn = get_db_connection(1)
    meijer_conn = get_db_connection(2)
    try:
        with (
            runerra_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
            meijer_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as meijer_cur,
        ):
            # 1. Timeslots (runs + store geo) — DB1
            timeslot_rows = _query_timeslots(cur, store_ids, utc_start, utc_end)
            if not timeslot_rows:
                return [], None
            timeslot_map = {str(row["id"]): row for row in timeslot_rows}
            timeslot_ids = [str(row["id"]) for row in timeslot_rows]

            # 2. Orders — DB2
            order_rows = _query_orders(meijer_cur, timeslot_ids)
            order_ids = [row["orderId"] for row in order_rows]

            # 3. Quantities, store info, customer geo — DB2 / DB1
            quantity_map    = _query_quantity_map(meijer_cur, order_ids)
            store_map       = _query_store_map(meijer_cur, store_ids)
            address_ids     = [int(row["addressId"]) for row in order_rows if row.get("addressId") is not None]
            address_geo_map = _query_address_geo_map(cur, address_ids)

            # 4. Map rows → standard order dicts
            all_orders: List[Dict] = []
            window_minutes: Optional[int] = None
            for row in order_rows:
                order, order_window = _map_row_to_order(
                    dict(row), store_map, quantity_map, timeslot_map, tz_name, address_geo_map
                )
                if order is None:
                    continue
                if window_minutes is None and order_window is not None:
                    window_minutes = order_window
                all_orders.append(order)
    finally:
        runerra_conn.close()
        meijer_conn.close()

    return all_orders, window_minutes


def _to_time(val) -> Optional[time_type]:
    """Normalize a DB value (datetime, time, or str) to datetime.time.
    Matches the type that parser.parse_csv() produces."""
    if val is None:
        return None
    if isinstance(val, time_type):
        return val
    if isinstance(val, datetime):
        return val.time()
    for fmt in ("%H:%M:%S", "%I:%M %p", "%H:%M"):
        try:
            return datetime.strptime(str(val), fmt).time()
        except ValueError:
            continue
    return None


def _to_tz_str(val, tz_name: str, fmt: str) -> str:
    """Convert a UTC-aware (or naive-UTC) datetime to a localized string.
    Falls back to str() for date objects and plain strings."""
    if val is None:
        return ""
    if isinstance(val, datetime):
        tz = pytz.timezone(tz_name)
        if val.tzinfo is None:
            val = pytz.utc.localize(val)
        return val.astimezone(tz).strftime(fmt)
    return str(val)


def _map_row_to_order(row: Dict, store_map: Dict, quantity_map: Dict, timeslot_map: Dict, tz_name: str = "UTC", address_geo_map: Optional[Dict] = None) -> Tuple[Optional[Dict], Optional[int]]:
    """
    Map a database row (new CSV-format columns) to the standard order dict.

    Skips cancelled orders. Returns (None, None) for rows that cannot be parsed.

    Args:
        row: Database row as a plain dict
        store_map: Map of bunchaStoreId to store info dict
        quantity_map: Map of orderId to totalQuantity
        timeslot_map: Map of timeSlotId to timeslot info dict   
    Returns:
        Tuple of (order_dict, window_minutes) or (None, None) if the row is invalid
    """
    try:
        units_raw = quantity_map.get(str(row["orderId"]), 0)
        units = int(units_raw) if units_raw is not None else 0
    except (ValueError, TypeError):
        units = 0

    # Parse earlyEligible as boolean
    early_raw = row.get("earlyEligible", False)
    if isinstance(early_raw, bool):
        early_delivery_ok = early_raw
    else:
        early_str = str(early_raw).strip().lower()
        early_delivery_ok = early_str in ["yes", "y", "true", "1"]

    window_start = None
    window_end = None
    
    timeslot = timeslot_map.get(str(row.get("timeSlotId", "")), {})
    window_start = _to_time(timeslot.get("delivery_window_start"))
    window_end = _to_time(timeslot.get("delivery_window_end"))
    
    order: Dict = {
        "order_id": str(row.get("externalOrderId", "")),
        "orderId": str(row.get("orderId", "")),
        "customer_name": str(row.get("customerID", "")),
        "orderStatus": str(row.get("orderStatus", "")),
        "priorRescheduleCount": int(row.get("priorRescheduleCount", 0)),
        "fulfillmentLocation": store_map.get(str(timeslot.get("storeId", "")), {}).get("retailerStoreId", ""),
        "fulfillmentLocationAddress": str(timeslot.get("address", "")),
        "deliveryDate": _to_tz_str(timeslot.get("deliveryDate"), tz_name, "%Y-%m-%d"),
        "extendedCutOffTime": _to_tz_str(timeslot.get("extendedCutOffTime"), tz_name, "%Y-%m-%d %I:%M %p"),
        "runId": int(row.get("timeSlotId", "")),
        "delivery_address": str(row.get("customerAddress", "")),
        "units": units,
        "delivery_window_start": window_start,
        "delivery_window_end": window_end,
        "customerTag": str(row.get("customerTag", "")),
        "fulfillmentGeo": _get_store_category(store_map.get(str(timeslot.get("storeId", "")), {}), timeslot),
        "early_delivery_ok": early_delivery_ok
    }

    # Attach lat/lng from external_address table (avoids Geocoding API)
    if address_geo_map is not None:
        geo = address_geo_map.get(str(row.get("addressId", "")), {})
        order["lat"] = geo.get("lat")
        order["lng"] = geo.get("lng")

    # Attach depot lat/lng — prefer store's geohash-decoded location, fall back to run row
    order["depot_lat"] = timeslot.get("storeLat")
    order["depot_lng"] = timeslot.get("storeLon")

    # Carry through optional fields (mirrors parser.py behavior)
    optional_fields = [
        "orderId", "runId", "orderStatus", "customerTag", "customerID",
        "deliveryDate", "priorRescheduleCount", "fulfillmentLocation",
        "fulfillmentGeo", "fulfillmentLocationAddress", "extendedCutOffTime",
    ]
    print(order)
    for field in optional_fields:
        if field in row:
            order[field] = row[field]  # preserve None values intentionally

    # Calculate window duration in minutes (same logic as parser.parse_csv)
    if window_start and window_end:
        order_window_minutes = (window_end.hour * 60 + window_end.minute) - (window_start.hour * 60 + window_start.minute)
    else:
        order_window_minutes = None

    return order, order_window_minutes




def _get_store_category(store: Dict, run: Dict) -> str:
    """
    Derive the store category label from a run row.

    Mirrors the SQL CASE expression:
      WHEN rs."dropOffPoint" ilike '%test%'              -> 'Test_Run'
      WHEN rs."storeName" not ilike '%Meijer%'           -> 'Non_Meijer'
      WHEN s."retailerStoreId" in (20, 36, 311)          -> 'Grand Rapids'
      WHEN s."retailerStoreId" in (27,53,72,122,208,...)  -> 'Detroit'
      WHEN s."retailerStoreId" in (23, 52)               -> 'Lansing'
      ELSE                                               -> 'New_Store'

    Args:
        run: Run dict with optional keys: dropOffPoint, storeName, retailerStoreId

    Returns:
        Category string.
    """
    
    if "test" in str(run.get("dropOffPoint", "")).lower():
        return "Test_Run"

    if "meijer" not in str(run.get("storeName", "")).lower():
        return "Non_Meijer"
    print(store, run.get("storeName"))
    retailer_id = store.get("retailerStoreId")
    if retailer_id in {20, 36, 311}:
        return "Grand Rapids"
    if retailer_id in {27, 53, 72, 122, 208, 243, 268, 286, 306}:
        return "Detroit"
    if retailer_id in {23, 52}:
        return "Lansing"
    return "New_Store"
