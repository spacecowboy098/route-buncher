# Route Buncher — Developer Guide

Complete reference for working on The Buncher route optimizer codebase.

---

## Running the App

```bash
python3 -m streamlit run app.py
```

Runs at `http://localhost:8501`. No build step required.

**Environment setup** — create a `.env` file in the project root:
```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx   # optional, enables AI features
GOOGLE_MAPS_API_KEY=AIzaSy...                   # optional, enables real geocoding
DEPOT_ADDRESS=3710 Dix Hwy Lincoln Park, MI 48146
DEFAULT_VEHICLE_CAPACITY=300
REQUIRE_AUTH=false                              # disable password for local dev
TEST_MODE=true                                  # skip API calls during development
```

When `TEST_MODE=true` (the default), all Google Maps and Anthropic API calls are skipped and mock data is used instead — zero cost during development.

---

## File Structure

| File | Purpose |
|------|---------|
| `app.py` | Main Streamlit UI (~3,483 lines) |
| `allocator.py` | Cross-window order allocation (multi-pass logic) |
| `optimizer.py` | OR-Tools CVRPTW solver |
| `disposition.py` | Order classification (KEEP / EARLY_DELIVERY / RESCHEDULE / CANCEL) |
| `parser.py` | CSV ingestion and validation |
| `geocoder.py` | Google Maps geocoding + distance matrix |
| `chat_assistant.py` | Claude AI chat, validation, and order explanations |
| `config.py` | Environment variable / Streamlit secrets access |
| `utils.py` | Shared constants and helper functions |

---

## Architecture

### Two Optimization Modes

**One Window** — single-window CVRPTW:
1. `parser.py` parses CSV → order list
2. `geocoder.py` geocodes addresses + builds time matrix
3. `optimizer.py` runs OR-Tools solver → `(kept, dropped_nodes)`
4. `disposition.py` classifies dropped orders (KEEP/EARLY/RESCHEDULE/CANCEL)
5. `chat_assistant.py` generates explanations and validates results (if AI enabled)
6. Results stored in `st.session_state.optimization_results`

**Multiple Windows** — allocator + per-window optimizer:
1. `parser.py` parses CSV → order list
2. `allocator.py` runs multi-pass allocation across windows → `AllocationResult`
3. Per window: `geocoder.py` + `optimizer.py` + `disposition.py`
4. `chat_assistant.py` validates per window (if AI enabled)
5. Results stored in `st.session_state.full_day_results`

After results are stored, `st.rerun()` is called and the cached section renders on the next run.

### Session State Keys
- `st.session_state.optimization_results` — One Window results dict
- `st.session_state.full_day_results` — Multiple Windows results dict
- `st.session_state.window_capacities_config` — per-window capacity overrides
- `st.session_state.optimization_complete` — bool, controls sidebar collapse

---

## Key Modules

### `utils.py` — Shared Foundation

Constants used across modules:
```python
UNREACHABLE_TIME = 9999          # sentinel for unreachable routes
EARTH_RADIUS_KM = 6371.0
MOCK_BASE_LAT, MOCK_BASE_LNG    # Minneapolis area for mock geocoding
DISTANCE_MATRIX_BATCH_SIZE = 10  # Google API batch limit
TRUTHY_VALUES = {"yes", "y", "true", "1"}
EARLY_DELIVERY_THRESHOLD_MINUTES = 10
RESCHEDULE_THRESHOLD_MINUTES = 20
```

Helpers:
- `parse_reschedule_count(order)` — safely parses `priorRescheduleCount` field
- `parse_boolean(value)` — handles None/NaN/string booleans from CSV
- `create_classified_order(order, category, reason, score, **extras)` — builds disposition dict
- `create_numbered_marker_html(stop_number, color, size=30)` — Folium DivIcon HTML

### `config.py` — Configuration

Key exports:
- `DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5-20250929"` — single source of truth for AI model
- `get_secret(key, default)` — reads from Streamlit secrets (cloud) or `.env` (local)
- `is_test_mode()` — checks runtime override first, then `TEST_MODE` env var
- `set_test_mode(enabled)` — runtime override from UI checkbox
- `is_ai_enabled()` — False if test mode or no API key

### `allocator.py` — Multi-Window Allocation

`allocate_orders_across_windows(orders, windows, window_capacities, ...)` runs 6 sequential passes:
- Pre-pass: filter oversized orders
- Pass 1: lock priority customers to original window
- Pass 2: move early-eligible orders to earlier windows
- Pass 3: assign orders to original window
- Pass 4: handle overflow (large orders above reschedule threshold)
- Pass 5: rescue overflow into later windows
- Pass 6: place deferred large orders

Returns `AllocationResult` dataclass with `kept_in_window`, `moved_early`, `moved_later`, `reschedule`, `cancel`, `orders_by_window`.

Key helpers: `window_label(start, end)`, `window_duration_minutes(start, end)` — also used by `app.py`.

### `optimizer.py` — OR-Tools Solver

`solve_route(time_matrix, demands, vehicle_capacity, max_route_time, service_times, drop_penalty)` → `(kept_orders, dropped_nodes)`

Constants (tunable):
```python
SERVICE_TIME_BASE = 1.6
SERVICE_TIME_EXPONENT = 1.3
SERVICE_TIME_COEFFICIENT = 0.045
SERVICE_TIME_CAP = 7              # max minutes per stop
DEFAULT_SLACK_MINUTES = 30
SOLVER_TIME_LIMIT_SECONDS = 5
```

`service_time_for_units(units)` — smart service time calculation used when `SERVICE_TIME_METHOD=smart`.

### `disposition.py` — Order Classification

`classify_orders(all_orders, kept, dropped_nodes, time_matrix)` → `(keep, early, reschedule, cancel)`

Classification thresholds (from `utils.py`):
- `< EARLY_DELIVERY_THRESHOLD_MINUTES (10)` and `early_ok=True` → EARLY_DELIVERY
- `< RESCHEDULE_THRESHOLD_MINUTES (20)` → RESCHEDULE
- `>= 20 min` → CANCEL

Uses `create_classified_order()` from `utils.py` for all output dicts.

### `chat_assistant.py` — AI Integration

Model is controlled by `DEFAULT_CLAUDE_MODEL` from `config.py` — **do not hardcode model strings here**.

Token limits:
```python
MAX_TOKENS_CHAT = 1500
MAX_TOKENS_VALIDATION = 800
MAX_TOKENS_EXPLANATION = 2000
```

Key functions:
- `create_context_for_ai(...)` — builds the system context string with full route details
- `chat_with_assistant(messages, context, api_key)` — sends chat to Claude API
- `validate_optimization_results(...)` — AI validates a completed route
- `generate_order_explanations(...)` — AI generates per-order disposition reasons
- `call_claude_api(prompt, api_key)` — simple single-prompt helper

In test mode, `generate_mock_validation()` and `generate_mock_order_explanations()` are used instead of API calls. Mock explanations use the `MOCK_EXPLANATIONS` dict.

Internal helpers:
- `_sort_kept_orders(keep)` — sort by `sequence_index`
- `_calculate_total_route_time(keep, time_matrix)` — depot → stops → depot drive time

### `parser.py` — CSV Ingestion

Supports two formats detected automatically:
- **New format**: `externalOrderId`, `customerID`, `address`, `numberOfUnits`, `earlyEligible`, `deliveryWindow`
- **Legacy format**: `orderID`, `customer_name`, `delivery_address`, `number_of_units`, `early_ok`, `delivery_window_start` + `delivery_window_end`

Optional fields stored verbatim from CSV are defined in `OPTIONAL_ORDER_FIELDS` (module-level constant).

Uses `parse_boolean()` from `utils.py` for `earlyEligible` field.

### `geocoder.py` — Geocoding & Distance Matrix

In test mode, uses deterministic mock functions:
- `_mock_geocode_addresses()` — uses `MOCK_BASE_LAT/LNG` + address hash seed
- `_mock_build_time_matrix()` — Haversine distances at 30 km/h
- `_mock_get_route_polylines()` — straight lines between waypoints

Real mode uses Google Maps APIs in batches of `DISTANCE_MATRIX_BATCH_SIZE = 10`.

---

## `app.py` — UI Structure

### Top-Level Imports
All imports are at module level — no inline imports inside functions. Key ones:
```python
from allocator import window_duration_minutes, window_label, allocate_orders_across_windows
from chat_assistant import call_claude_api
from utils import create_numbered_marker_html
import folium
from folium import plugins
```

### Module-Level Helpers (before `main()`)
- `format_time_minutes(minutes)` — formats int as "HH:MM"
- `extract_all_csv_fields(order)` — extracts displayable CSV fields (excludes internal fields)
- `create_standard_row(order)` — builds the 7-field standard row dict for dataframes
- `_initialize_folium_map(center_lat, center_lon, use_google_tiles)` — creates base map
- `_add_route_polylines(m, addresses, waypoint_order, ...)` — draws route line
- `_add_route_markers(m, keep, early, reschedule, cancel, ...)` — adds all stop markers
- `create_map_visualization(...)` — single-window map
- `create_multi_window_map(...)` — multi-window color-coded map; uses `ROUTE_COLORS` constant
- `generate_route_explanation(...)` — template-based route explanation (no AI)
- `display_optimization_results(...)` — renders KPIs, map, and order tables for one cut
- `_calculate_route_times(kept, time_matrix, service_times)` — returns `{drive_time, service_time, total_time}`
- `_get_explanation_field(order, show_ai, default_reason)` — returns `{"AI Explanation": ...}` or `{"Reason": ...}`
- `_reorder_reason(df)` — moves 'Reason' column after 'numberOfUnits' in a DataFrame
- `calc_route_metrics(kept_orders, kept_nodes_data, service_times, time_matrix, vehicle_capacity)` — returns metrics dict
- `check_password()` — Streamlit password gate
- `main()` — main app entry point (~2,600 lines, contains sidebar + both optimization modes)

### Constants
```python
ROUTE_COLORS = ['#FF0000', '#0000FF', '#00C800', '#FF00FF', '#FFA500', '#00FFFF', '#FF1493', '#8B4513']
```

### Brand Colors (Buncha palette)
```
Banana: #FFE475 | Sprout: #40D689 | Gumball: #5DA9E9
Eggplant: #100E3A | Tang: #F5A874 | Tart: #D4634C
```
CSS is injected at top of `main()` via `st.markdown(unsafe_allow_html=True)`.

---

## AI Features

AI features are **optional** — the optimizer works without them. When enabled (live mode + API key), Claude AI provides:

1. **Route Validation** — validates math and logic after optimization
2. **Order Explanations** — per-order reasons for disposition
3. **Interactive Chat** — dispatcher Q&A about any cut

### Changing the AI Model

Change `DEFAULT_CLAUDE_MODEL` in `config.py`:
```python
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5-20250929"   # current default
# DEFAULT_CLAUDE_MODEL = "claude-opus-4-6"            # more capable
# DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # fastest/cheapest
```
This propagates automatically to all `chat_assistant.py` API calls.

### Customizing AI Prompts

Prompts live in `chat_assistant.py`:
- `create_context_for_ai()` — system context (role, route data, capabilities)
- `validate_optimization_results()` — validation prompt
- `generate_order_explanations()` — per-order explanation prompt

---

## Test Mode

Toggled via the **🧪 Test Mode** checkbox in the sidebar (calls `config.set_test_mode()`), or via `TEST_MODE=true` in `.env`.

When enabled:
- `geocoder.py` → uses mock functions (deterministic, hash-seeded per address)
- `chat_assistant.py` → uses `generate_mock_*` functions (no API calls)
- All UI features and routing logic work identically
- **Cost: $0**

Default is `TEST_MODE=true` to prevent accidental API charges.

---

## Disposition Classification Thresholds

Defined in `utils.py`, used in `disposition.py`:

| Threshold | Value | Meaning |
|-----------|-------|---------|
| `EARLY_DELIVERY_THRESHOLD_MINUTES` | 10 min | Max cluster distance for early delivery eligibility |
| `RESCHEDULE_THRESHOLD_MINUTES` | 20 min | Below this → reschedule; at/above → cancel |

These are noted as "initial guesses" in comments — tune based on operational data.

---

## Troubleshooting

**App won't start**: Check `.env` exists; `REQUIRE_AUTH=false` for dev.

**"⚠️ Chat assistant is not configured"**: Add `ANTHROPIC_API_KEY` to `.env`.

**Maps not rendering**: Either `GOOGLE_MAPS_API_KEY` is missing (enable Test Mode) or geocoding failed for some addresses.

**Import errors after editing**: Run `python3 -c "import app"` to check for syntax errors without starting the full Streamlit server.

**AI responses seem wrong**: Re-run optimization. If persistent, enable Test Mode to isolate the routing algorithm from API issues.

---

## Security

- Never commit `.env` to version control (it's in `.gitignore`)
- `REQUIRE_AUTH=false` is for local dev only — always require auth in shared/production deployments
- API keys are read via `config.get_secret()` which tries Streamlit secrets first, then env vars

---

## Recent Changes (February 2026)

### Codebase Refactor

- **New `utils.py`**: shared constants (`UNREACHABLE_TIME`, thresholds, etc.) and helpers (`parse_reschedule_count`, `parse_boolean`, `create_classified_order`, `create_numbered_marker_html`)
- **`config.py`**: added `DEFAULT_CLAUDE_MODEL` and `_parse_bool()` helper
- **`chat_assistant.py`**: model name centralized via `DEFAULT_CLAUDE_MODEL`; extracted `_sort_kept_orders()` and `_calculate_total_route_time()` helpers; added `MOCK_EXPLANATIONS` dict and `MAX_TOKENS_*` constants
- **`allocator.py`**: `parse_reschedule_count()` replaces 3 duplicate parsing blocks
- **`optimizer.py`**: service time and solver parameters extracted to named constants
- **`disposition.py`**: uses `create_classified_order()` and threshold constants from `utils.py`
- **`parser.py`**: uses `parse_boolean()` from `utils.py`; `OPTIONAL_ORDER_FIELDS` is now a module-level constant
- **`geocoder.py`**: uses constants from `utils.py` for coordinates, Earth radius, batch size
- **`app.py`**: all imports moved to module level; `_reorder_reason()` and `calc_route_metrics()` moved from nested to module level; added `_calculate_route_times()` and `_get_explanation_field()` helpers; `ROUTE_COLORS` constant added; numbered marker HTML deduped via `create_numbered_marker_html()`
