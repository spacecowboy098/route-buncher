# The Buncher - Setup Instructions

Complete guide to get The Buncher route optimizer running on your machine.

---

## Prerequisites

Before you begin, ensure you have the following installed:

1. **Python 3.9 or higher**
   - Check your version: `python3 --version`
   - Download from: https://www.python.org/downloads/

2. **Git** (to clone the repository)
   - Check if installed: `git --version`
   - Download from: https://git-scm.com/downloads

3. **API Keys** (required)
   - **Google Maps API Key** (required for geocoding and routing)
   - **Anthropic API Key** (optional, only for AI chat features)

---

## Step 1: Get the Source Code

### Option A: Clone from GitHub
```bash
git clone <your-repository-url>
cd route-buncher
```

### Option B: Download ZIP
1. Download the source folder as a ZIP file
2. Extract it to your desired location
3. Open terminal/command prompt and navigate to the folder:
   ```bash
   cd path/to/route-buncher
   ```

---

## Step 2: Set Up Python Environment

### Create a virtual environment (recommended)
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

You should see `(venv)` in your terminal prompt when activated.

---

## Step 3: Install Dependencies

Install all required Python packages:

```bash
pip install -r requirements.txt
```

This installs:
- `streamlit` - Web framework for the app
- `ortools` - Google's optimization solver
- `googlemaps` - Google Maps API client
- `anthropic` - Claude AI API client (for chat)
- `pandas` - Data manipulation
- `folium` - Interactive maps
- Other supporting libraries

**Note:** Installation may take 2-5 minutes depending on your internet speed.

---

## Step 4: Get Your API Keys

### Google Maps API Key (Required)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable these APIs:
   - **Geocoding API**
   - **Directions API**
   - **Distance Matrix API**
4. Go to **Credentials** → **Create Credentials** → **API Key**
5. Copy your API key
6. **Optional but recommended:** Restrict the key to only the APIs listed above

**Cost:** Google Maps offers $200/month free credit. Typical usage:
- ~100 orders/day = ~$5-10/month
- Stay well within free tier for most use cases

### Anthropic API Key (Optional)

Only needed if you want AI chat assistant features:

1. Go to [Anthropic Console](https://console.anthropic.com/)
2. Sign up or log in
3. Go to **API Keys** → **Create Key**
4. Copy your API key

**Cost:** Pay-as-you-go. ~$0.01-0.05 per optimization with AI chat.

---

## Step 5: Configure Environment Variables

Create a `.env` file in the project root directory:

```bash
# From the route-buncher directory
touch .env
```

Open `.env` in a text editor and add:

```env
# Required: Google Maps API Key
GOOGLE_MAPS_API_KEY=your_google_maps_key_here

# Optional: Anthropic API Key (for AI chat features)
ANTHROPIC_API_KEY=your_anthropic_key_here

# Optional: Default settings
DEPOT_ADDRESS=Meijer Plymouth MN
DEFAULT_VEHICLE_CAPACITY=80
```

**Replace** `your_google_maps_key_here` with your actual API key.

**Important:** Never commit `.env` to version control! It's already in `.gitignore`.

---

## Step 6: Verify Installation

Test that everything is set up correctly:

```bash
python3 -c "import streamlit, ortools, googlemaps; print('✅ All dependencies installed!')"
```

If you see `✅ All dependencies installed!`, you're ready!

---

## Step 7: Launch The App

Start the Streamlit app:

```bash
streamlit run app.py
```

You should see:
```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.x.x:8501
```

The app will automatically open in your default browser. If not, manually open: **http://localhost:8501**

---

## Using The App

### Quick Start

1. **Upload CSV** - Click "Browse files" and select your order CSV
2. **Review Orders** - Check the order preview table
3. **Run Optimization** - Click "🚀 Run (with AI)" or "⚡ Run (no AI)"
4. **Review Results** - Explore the 4 optimization strategies:
   - **Cut 1:** Max Orders (recommended)
   - **Cut 2:** Shortest Route
   - **Cut 3:** High Density
   - **Cut 4:** Dispatcher Sandbox (manual editing)

### CSV Format

The Buncher supports two CSV formats:

#### **New Format** (Recommended)

The new format includes comprehensive order data for enhanced analytics and audit capabilities:

**Required columns:**
- `externalOrderId` - External order identifier (e.g., 1298738902)
- `customerID` - Customer UUID or identifier
- `address` - Full delivery address
- `numberOfUnits` - Number of units to deliver
- `earlyEligible` - `true` or `false` (early delivery allowed?)
- `deliveryWindow` - Combined time window (e.g., "09:00 AM 11:00 AM")

**Optional columns** (stored for future features):
- `orderId` - Internal UUID
- `runId` - Run/route identifier
- `orderStatus` - Order status (e.g., "delivered", "cancelled")
- `customerTag` - Customer segment (e.g., "new", "power", "unsatisfied")
- `deliveryDate` - Delivery date
- `priorRescheduleCount` - Number of times order was rescheduled
- `fulfillmentLocation` - Fulfillment center name
- `fulfillmentGeo` - Geographic region
- `fulfillmentLocationAddress` - Fulfillment center address
- `extendedCutOffTime` - Extended cutoff time

**Order Status Filter:**
When using the new format with `orderStatus`, you can filter which orders to include using the sidebar filter. This is useful for audit purposes to verify if cancelled orders should have been included in the route.

#### **Legacy Format** (Still Supported)

Your CSV can also use the original format:
- `orderID` - Unique order identifier
- `customer_name` - Customer name
- `delivery_address` - Full delivery address
- `number_of_units` - Number of units to deliver
- `early_ok` - "Yes" or "No" (early delivery allowed?)
- `delivery_window_start` - Start time (e.g., "09:00 AM")
- `delivery_window_end` - End time (e.g., "11:00 AM")

**Format Detection:**
The parser automatically detects which format you're using based on column names. Both formats work identically for optimization.

---

## Troubleshooting

### "GOOGLE_MAPS_API_KEY not found"
- Make sure `.env` file exists in the project root
- Check that the API key is correctly set in `.env`
- Restart the app after adding the key

### "Module not found" errors
```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### Port 8501 already in use
```bash
# Kill existing Streamlit processes
pkill -f streamlit

# Or run on a different port
streamlit run app.py --server.port 8502
```

### Virtual environment issues
```bash
# Deactivate and recreate
deactivate
rm -rf venv
python3 -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### AI Chat not working
- Check that `ANTHROPIC_API_KEY` is set in `.env`
- AI features are optional - optimizer works without it
- Try "⚡ Run (no AI)" button for faster debugging

---

## Stopping The App

Press **Ctrl+C** in the terminal where Streamlit is running.

To deactivate the virtual environment:
```bash
deactivate
```

---

## Updating The App

To get the latest version:

```bash
git pull origin main
pip install -r requirements.txt  # Update dependencies if changed
streamlit run app.py
```

---

## System Requirements

**Minimum:**
- Python 3.9+
- 2 GB RAM
- Internet connection (for Google Maps API)

**Recommended:**
- Python 3.10+
- 4 GB RAM
- Modern browser (Chrome, Firefox, Safari, Edge)

**Operating Systems:**
- ✅ macOS (10.14+)
- ✅ Windows (10+)
- ✅ Linux (Ubuntu 20.04+)

---

## Security Notes

1. **Never share your `.env` file** - It contains your API keys
2. **Restrict API keys** - Use Google Cloud Console to limit key usage
3. **Monitor API usage** - Check Google Cloud Console for unexpected charges
4. **Rotate keys regularly** - Generate new keys every 3-6 months

---

## Getting Help

If you encounter issues:

1. Check the **Troubleshooting** section above
2. Review error messages carefully
3. Check API quotas in Google Cloud Console
4. Ensure all prerequisites are installed

---

## File Structure

```
route-buncher/
├── app.py                  # Main Streamlit application
├── optimizer.py            # OR-Tools routing optimizer
├── geocoder.py            # Google Maps integration
├── parser.py              # CSV parsing logic
├── disposition.py         # Order classification logic
├── chat_assistant.py      # AI chat features
├── config.py              # Configuration management
├── requirements.txt       # Python dependencies
├── .env                   # API keys (create this)
├── README.md              # Project overview
└── SETUP.md               # This file
```

---

## Next Steps

Once the app is running:

1. Try the example CSV (if provided)
2. Experiment with different optimization strategies
3. Use the Dispatcher Sandbox to manually adjust routes
4. Check the AI chat assistant for route insights

**Happy optimizing! 🚐**
