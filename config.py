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
    return get_secret("DEPOT_ADDRESS", "Meijer Plymouth MN")


def get_default_capacity() -> int:
    """
    Get the default vehicle capacity in units (totes).

    Returns:
        int: Vehicle capacity in units
    """
    capacity_str = get_secret("DEFAULT_VEHICLE_CAPACITY", "80")
    try:
        return int(capacity_str)
    except ValueError:
        return 80


def get_anthropic_api_key() -> str:
    """
    Retrieve the Anthropic API key from Streamlit secrets or environment variables.

    Returns:
        str: Anthropic API key, or empty string if not set

    Note:
        This is optional - chat assistant won't work without it
    """
    return get_secret("ANTHROPIC_API_KEY", "")
