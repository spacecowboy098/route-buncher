"""
Configuration module for buncher-optimizer.
Handles environment variables and default settings.
"""

import os
from dotenv import load_dotenv
import googlemaps

# Load environment variables from .env file
load_dotenv()

# Try to import streamlit for cloud deployment
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False


def get_secret(key: str, default: str = None) -> str:
    """
    Get a secret from Streamlit secrets (cloud) or environment variables (local).

    Args:
        key: Secret key name
        default: Default value if not found

    Returns:
        Secret value or default
    """
    # Try Streamlit secrets first (for cloud deployment)
    if HAS_STREAMLIT:
        try:
            return st.secrets.get(key, os.getenv(key, default))
        except (AttributeError, FileNotFoundError):
            # Streamlit secrets not configured, fall back to env vars
            pass

    # Fall back to environment variables (for local development)
    return os.getenv(key, default)


def get_google_maps_api_key() -> str:
    """
    Retrieve the Google Maps API key from Streamlit secrets or environment variables.

    Returns:
        str: Google Maps API key

    Raises:
        ValueError: If API key is not set
    """
    api_key = get_secret("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_MAPS_API_KEY not found. "
            "Please set it in .env file (local) or Streamlit secrets (cloud)."
        )
    return api_key


def get_google_maps_client() -> googlemaps.Client:
    """
    Create and return a configured Google Maps client.

    Returns:
        googlemaps.Client: Configured Google Maps client
    """
    api_key = get_google_maps_api_key()
    return googlemaps.Client(key=api_key)


def get_default_depot() -> str:
    """
    Get the default depot address from Streamlit secrets, environment, or use fallback.

    Returns:
        str: Depot address
    """
    return get_secret("DEPOT_ADDRESS", "3710 Dix Hwy Lincoln Park, MI 48146")


def get_default_capacity() -> int:
    """
    Get the default vehicle capacity in units (totes).

    Returns:
        int: Vehicle capacity in units
    """
    capacity_str = get_secret("DEFAULT_VEHICLE_CAPACITY", "300")
    try:
        return int(capacity_str)
    except ValueError:
        return 300


def get_anthropic_api_key() -> str:
    """
    Retrieve the Anthropic API key from Streamlit secrets or environment variables.

    Returns:
        str: Anthropic API key, or empty string if not set

    Note:
        This is optional - chat assistant won't work without it
    """
    return get_secret("ANTHROPIC_API_KEY", "")


def get_app_password() -> str:
    """
    Retrieve the app password from Streamlit secrets or environment variables.

    Returns:
        str: App password for authentication

    Note:
        If not set, defaults to "spaceCowboy"
    """
    return get_secret("APP_PASSWORD", "spaceCowboy")


def is_auth_required() -> bool:
    """
    Check if authentication is required for the app.

    Controlled by REQUIRE_AUTH environment variable.
    Set to 'false' in .env to disable authentication during local development.

    Returns:
        bool: True if authentication required (default), False to skip auth
    """
    require_auth = get_secret("REQUIRE_AUTH", "true")
    return require_auth.lower() not in ["false", "0", "no", "off"]


# Runtime test mode override (can be set from UI)
_test_mode_override = None


def set_test_mode(enabled: bool):
    """
    Set test mode at runtime (overrides environment variable).

    Args:
        enabled: True to enable test mode, False to disable
    """
    global _test_mode_override
    _test_mode_override = enabled


def get_default_service_time_method() -> str:
    """
    Get the default service time calculation method.

    Returns:
        str: "smart" for variable by units, "fixed" for fixed time per stop
    """
    method = get_secret("SERVICE_TIME_METHOD", "smart")
    return method.lower()


def get_default_fixed_service_time() -> int:
    """
    Get the default fixed service time in minutes.

    Returns:
        int: Fixed service time in minutes (default: 3)
    """
    time_str = get_secret("FIXED_SERVICE_TIME", "3")
    try:
        return int(time_str)
    except ValueError:
        return 3


def is_test_mode() -> bool:
    """
    Check if test mode is enabled (bypasses Google Maps API calls).

    Test mode uses mock geocoding and estimated distances instead of real API calls,
    which is useful for development and UX testing without incurring API costs.

    Returns:
        bool: True if test mode is enabled (default), False otherwise
    """
    global _test_mode_override

    # Check runtime override first (set from UI)
    if _test_mode_override is not None:
        return _test_mode_override

    # Fall back to environment variable
    test_mode = get_secret("TEST_MODE", "true")
    return test_mode.lower() in ["true", "1", "yes", "on"]


def get_db_url(db_num: int) -> str:
    """
    Retrieve the PostgreSQL connection URL for the specified database number.

    Args:
        db_num: Database number (1 or 2)

    Returns:
        str: Database connection URL, or empty string if not configured
    """
    return get_secret(f"DB_{db_num}_URL", "")


def get_default_timezone() -> str:
    """
    Get the default timezone for date calculations.

    Returns:
        str: IANA timezone name (e.g., "America/New_York")
    """
    return get_secret("DEFAULT_TIMEZONE", "America/New_York")


def is_ai_enabled() -> bool:
    """
    Check if AI features should be enabled.

    AI features are disabled in test mode (to avoid API costs during development)
    or when no Anthropic API key is configured.

    Returns:
        bool: True if AI should be enabled, False otherwise
    """
    # Disabled if in test mode (avoids API costs)
    if is_test_mode():
        return False

    # Disabled if no API key configured
    api_key = get_anthropic_api_key()
    return bool(api_key)
