"""
Config Utility v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/10/2026

This file contains utility functions for a config.json file that are shared by multiple scripts.
"""

import os, json, sys
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

def clean_path(raw_path: str) -> str:
    """
    Normalizes a path from config.json (mixed slashes) into an absolute OS path.

    Args:
        raw_path (str): Path string from config.json.

    Returns:
        str: Absolute, normalized path.
    """
    return os.path.abspath(raw_path.replace('\\', '/'))

def get_db_path(config: dict) -> str:
    """
    Builds the path to the single pipeline database shared by every AOI.

    Args:
        config (dict): Parsed configuration.

    Returns:
        str: Path to methane.db inside the project folder.
    """
    return os.path.join(get_project_folder(config), 'methane.db')

def get_bbox(aoi: dict) -> list[float]:
    """
    Simple helper to extract the bounding box from an AOI dictionary.

    Args:
        aoi (dict): Parsed json dictionary with aoi info.

    Returns:
        list[float]: Bounding box in lon/lat order.
    """

    return aoi['coords']

def get_project_folder(config: dict) -> str:
    """
    Builds the absolute path to the local project folder chosen in the folder picker.

    Args:
        config (dict): Parsed configuration.

    Returns:
        str: Absolute, normalized path to the project folder.
    """
    return clean_path(config['project_folder'])

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python config_util.py <path_to_config.json>")
    print(get_project_folder(load_json(sys.argv[1])))

if __name__ == '__main__':
    main()