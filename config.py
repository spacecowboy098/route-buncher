"""
Configuration module for buncher-optimizer.
Handles environment variables and default settings.
"""

import os
from dotenv import load_dotenv
import googlemaps

# Load environment variables from .env file
load_dotenv()


def get_google_maps_api_key() -> str:
    """
    Retrieve the Google Maps API key from environment variables.

    Returns:
        str: Google Maps API key

    Raises:
        ValueError: If API key is not set
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_MAPS_API_KEY not found in environment variables. "
            "Please set it in your .env file."
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
    Get the default depot address from environment or use fallback.

    Returns:
        str: Depot address
    """
    return os.getenv("DEPOT_ADDRESS", "Meijer Plymouth MN")


def get_default_capacity() -> int:
    """
    Get the default vehicle capacity in units (totes).

    Returns:
        int: Vehicle capacity in units
    """
    capacity_str = os.getenv("DEFAULT_VEHICLE_CAPACITY", "80")
    try:
        return int(capacity_str)
    except ValueError:
        return 80


def get_anthropic_api_key() -> str:
    """
    Retrieve the Anthropic API key from environment variables.

    Returns:
        str: Anthropic API key, or empty string if not set

    Note:
        This is optional - chat assistant won't work without it
    """
    return os.getenv("ANTHROPIC_API_KEY", "")
