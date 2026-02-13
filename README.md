# buncher-optimizer

**Internal route optimization tool for Buncha delivery dispatchers.**

This Streamlit application ingests a CSV of delivery orders and optimizes which orders to keep in a delivery window based on vehicle capacity, time constraints, and geographic proximity. Orders that don't fit are classified as: EARLY DELIVERY, RESCHEDULE, or CANCEL.

## Features

- **Route Optimization**: Uses OR-Tools CVRPTW solver to find optimal delivery routes
- **Capacity Constraints**: Respects vehicle capacity limits (number of totes/units)
- **Time Windows**: Ensures routes fit within specified delivery windows
- **Geographic Clustering**: Analyzes travel times between orders using Google Maps Distance Matrix API
- **Smart Disposition**: Automatically categorizes dropped orders based on proximity to the optimized cluster
- **Interactive UI**: Easy-to-use Streamlit interface for internal dispatchers

## Setup

### Prerequisites

- Python 3.11 or higher
- Google Maps API key with the following APIs enabled:
  - Geocoding API
  - Distance Matrix API

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd buncher-optimizer
   ```

2. **Create a virtual environment** (recommended)
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**

   Create a `.env` file in the project root:
   ```
   GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
   DEPOT_ADDRESS=Meijer Plymouth MN
   DEFAULT_VEHICLE_CAPACITY=80
   ```

   - `GOOGLE_MAPS_API_KEY` (required): Your Google Maps API key
   - `DEPOT_ADDRESS` (optional): Default depot/starting location
   - `DEFAULT_VEHICLE_CAPACITY` (optional): Default vehicle capacity in units

## Running the App

Start the Streamlit app:

```bash
streamlit run app.py
```

The app will open in your default browser at `http://localhost:8501`.

## CSV Format

The app expects a CSV file with the following exact column names:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `orderID` | string/int | Unique order identifier | 70509 |
| `customer_name` | string | Customer name | Michael Tomaszewski |
| `delivery_address` | string | Full delivery address | 6178 Gulley St Taylor 48180 |
| `number_of_units` | integer | Number of totes/bags | 2 |
| `early_ok` | string | "Yes" or "No" - early delivery allowed | No |
| `delivery_window_start` | string | Window start time | 09:00 AM |
| `delivery_window_end` | string | Window end time | 11:00 AM |

### Example CSV

```csv
orderID,customer_name,delivery_address,number_of_units,early_ok,delivery_window_start,delivery_window_end
70509,"Michael Tomaszewski","6178 Gulley St Taylor 48180",2,No,09:00 AM,11:00 AM
70592,"gabriel carrion","3522 Linden Street Dearborn 48124",26,Yes,09:00 AM,11:00 AM
70610,"Kristy Richards","2740 Cicotte Detroit 48209",18,No,09:00 AM,11:00 AM
```

### Notes on CSV Format

- All orders must be for the same calendar date and delivery run
- Time format must be `HH:MM AM/PM` (e.g., "09:00 AM", "02:30 PM")
- `early_ok` accepts: "Yes", "yes", "Y", "y", "No", "no", "N", "n"
- Addresses should be complete and geocodable via Google Maps

## How It Works

### 1. Upload & Parse
- Upload CSV with order data
- App validates required columns and data types

### 2. Geocoding
- Geocodes depot and all delivery addresses using Google Maps Geocoding API
- Builds a distance/time matrix between all locations using Distance Matrix API

### 3. Optimization
- Runs OR-Tools CVRPTW (Capacitated Vehicle Routing Problem with Time Windows) solver
- Constraints:
  - Vehicle capacity (total units)
  - Maximum route time (delivery window duration)
  - Travel times between locations
- Uses Guided Local Search metaheuristic for 5 seconds
- Allows dropping orders that don't fit (uniform penalty since revenue is fixed)

### 4. Disposition
Orders are classified into four categories:

- **KEEP**: Orders included in the optimized route
- **EARLY DELIVERY**: Dropped orders that are:
  - Close to the cluster (< 10 min average travel time to kept orders)
  - AND marked `early_ok = Yes`
- **RESCHEDULE**: Dropped orders moderately close to cluster (< 20 min)
  - Better fit in a different delivery window
- **CANCEL**: Dropped orders geographically isolated (≥ 20 min from cluster)
  - Not economical to deliver

**Note**: The 10-minute and 20-minute thresholds are initial estimates and should be tuned based on operational data and dispatcher feedback.

### 5. Results
- View optimized route sequence
- See capacity utilization and total route time
- Export decisions for each order category

## Project Structure

```
buncher-optimizer/
├── app.py              # Streamlit UI
├── config.py           # Environment variables & settings
├── geocoder.py         # Geocoding + distance matrix
├── optimizer.py        # OR-Tools CVRPTW solver
├── disposition.py      # Order classification logic
├── parser.py           # CSV parsing and validation
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── .env               # Environment variables (not in git)
```

## Configuration

### Sidebar Settings

- **Depot Address**: Starting location for deliveries
- **Vehicle Capacity**: Maximum number of units (totes) the vehicle can carry

These can be adjusted per run in the UI or set as defaults in `.env`.

## Limitations & Assumptions

- **Single vehicle**: V1 supports only one vehicle per optimization run
- **Fixed revenue**: All orders have equal revenue; only costs (travel time) are optimized
- **Same-day deliveries**: All orders must be for the same date and run
- **No service time**: Assumes zero time spent at each delivery location
- **Google Maps API costs**: Each optimization uses Geocoding + Distance Matrix API calls
- **No authentication**: This is an internal tool; no user authentication implemented

## Troubleshooting

### Common Issues

**"GOOGLE_MAPS_API_KEY not found"**
- Ensure `.env` file exists in project root with valid API key

**"Failed to geocode addresses"**
- Check that addresses in CSV are complete and valid
- Verify Google Maps API key has Geocoding API enabled

**"No solution found" or all orders dropped**
- Vehicle capacity may be too small
- Delivery window may be too short
- Try increasing capacity or window duration

**Rate limit errors from Google Maps**
- The app batches requests (10x10) to stay within limits
- For very large CSVs (>100 orders), you may hit API quotas

## Future Enhancements

- Multi-vehicle support
- Service time at each location
- Priority scoring for orders
- Export results to CSV
- Route visualization on a map
- Historical analytics

## Support

For issues, questions, or feature requests, contact the Buncha engineering team.

## License

Internal use only - Buncha, Inc.
