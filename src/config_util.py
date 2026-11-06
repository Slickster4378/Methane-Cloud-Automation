"""
Config Utility v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/05/2026

This file contains utility functions for a config.json file that are shared by multiple scripts.
"""

import os, json
from urllib3 import Retry
from pystac_client import Client # type: ignore
from pystac_client.stac_api_io import StacApiIO # type: ignore

GITHUB_REPO = os.environ.get('METHANE_REPO', 'Slickster4378/Methane-Cloud-Automation')

def load_json(config_path: str) -> dict:
    """
    Load a pipeline configuration JSON file.

    Args:
        config_path (str): Path to config.json.

    Returns:
        dict: Parsed configuration.
    """
    config_path = os.path.abspath(config_path)
    if not os.path.isfile(config_path):
        raise FileNotFoundError(
            f'Configuration file not found:\n{config_path}'
        )
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config

def stagger_results(search: str) -> Client:
    """
    Slows retries for STAC pull to avoid Err 429.

    Args:
        search (str): Web API address being opened
    
    Returns:
        Client: STAC Client Object
    """
    retry = Retry(
        total=5,
        backoff_factor=8,  # waits 0, 16s, 32s, 64s, 128s between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET", "POST"},
        raise_on_status=False,
        respect_retry_after_header=True,
        retry_after_max=300  # cap retry to 5 minutes
    )
    try:
        cat = Client.open(search, stac_io=StacApiIO(max_retries=retry))
        return cat
    except:
        return []
    