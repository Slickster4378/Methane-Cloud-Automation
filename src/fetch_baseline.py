"""
Fetch Baseline v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/05/2026

This script downloads each AOI's baseline mosaic from the GitHub release store, triggering a cloud build first for any AOI that has not been published yet.
"""

import os, sys, time
import requests
from datetime import datetime, timedelta, timezone
import config_util as cutil

API = 'https://api.github.com'
RELEASE_TAG = 'baselines'
WORKFLOW_FILE = 'run_pipeline.yml'
POLL_SECONDS = 30
TIMEOUT_SECONDS = 4 * 60 * 60

def get_headers(accept: str = 'application/vnd.github+json') -> dict:
    """
    Builds GitHub API headers, attaching the user's token if one is set.

    Args:
        accept (str): Accept header value.

    Returns:
        dict: Request headers.
    """
    headers = {'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28'}
    token = os.environ.get('GITHUB_PAT')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers

def get_asset_index() -> dict:
    """
    Fetches the baseline release once and indexes its assets by file name for O(1) lookups.

    Returns:
        dict: {asset file name: asset json}. Empty if the release does not exist yet.
    """
    response = requests.get(
        f'{API}/repos/{cutil.GITHUB_REPO}/releases/tags/{RELEASE_TAG}',
        headers=get_headers(),
        timeout=30
    )
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    return {asset['name']: asset for asset in response.json()['assets']}

def download_asset(asset: dict, local_dest_path: str) -> None:
    """
    Streams a release asset to disk, writing to a temp file first so a partial download is never mistaken for a baseline.

    Args:
        asset (dict): Release asset json from the asset index.
        local_dest_path (str): Final path for the baseline file.
    """
    os.makedirs(os.path.dirname(local_dest_path), exist_ok=True)
    temp_path = f'{local_dest_path}.part'
    with requests.get(asset['url'], headers=get_headers('application/octet-stream'), stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    os.replace(temp_path, local_dest_path)
    print(f'-> Successfully downloaded to: {local_dest_path}')

def dispatch_build(missing: list[dict]) -> None:
    """
    Triggers one cloud baseline build covering every AOI that has no published baseline.

    Args:
        missing (list[dict]): AOI dictionaries from config.json that need a baseline.
    """
    if not os.environ.get('GITHUB_PAT'):
        sys.exit('CRITICAL: GITHUB_PAT is not set. A GitHub token is required to trigger a cloud baseline build.')
    payload = {
        'event_type': 'trigger_baseline_build',
        'client_payload': {
            'aois': [{'name': aoi['name'], 'coords': aoi['coords']} for aoi in missing]
        }
    }
    response = requests.post(
        f'{API}/repos/{cutil.GITHUB_REPO}/dispatches',
        headers=get_headers(),
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    print(f"Triggered cloud build for: {', '.join(aoi['name'] for aoi in missing)}")

def latest_run(started: datetime) -> dict | None:
    """
    Gets the most recent dispatched workflow run since a start time, used to detect a failed cloud build.

    Args:
        started (datetime): UTC time the build was triggered, minus a small clock-skew buffer.

    Returns:
        dict | None: Workflow run json, or None if the run has not appeared yet.
    """
    response = requests.get(
        f'{API}/repos/{cutil.GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/runs',
        headers=get_headers(),
        params={
            'event': 'repository_dispatch',
            'per_page': 1,
            'created': f">={started.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        },
        timeout=30
    )
    response.raise_for_status()
    runs = response.json()['workflow_runs']
    return runs[0] if runs else None

def wait_for_build(names: list[str], started: datetime) -> dict:
    """
    Polls the release until every requested baseline is published, or the cloud run fails.

    Args:
        names (list[str]): AOI names being built.
        started (datetime): UTC time the build was triggered.

    Returns:
        dict: Fresh asset index containing the new baselines.
    """
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        assets = get_asset_index()
        if all(f'{name}_base.tif' in assets for name in names):
            return assets
        run = latest_run(started)
        if run and run['status'] == 'completed' and run['conclusion'] != 'success':
            sys.exit(f"CRITICAL: Cloud baseline build {run['conclusion']}. See: {run['html_url']}")
        print('Cloud build still running...')
    sys.exit('CRITICAL: Timed out waiting for the cloud baseline build.')

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python fetch_baseline.py <path_to_config.json>")
    config = cutil.load_json(sys.argv[1])
    needed = []
    for aoi in config['aois']:
        baseline_path = os.path.join(aoi['paths']['baseline'], 'base.tif').replace('\\', '/')
        if os.path.exists(baseline_path):
            print(f"AOI {aoi['name']} already has a baseline mosaic. Skipping...\n")
            continue
        needed.append((aoi, baseline_path))
    if not needed:
        return
    assets = get_asset_index()
    to_build = []
    for aoi, baseline_path in needed:
        asset = assets.get(f"{aoi['name']}_base.tif")
        if asset:
            print(f"[RELEASE MATCH] Found baseline for {aoi['name']}. Downloading locally...")
            download_asset(asset, baseline_path)
        else:
            print(f"[RELEASE MISS] No published baseline for {aoi['name']}.")
            to_build.append((aoi, baseline_path))
    if to_build:
        started = datetime.now(timezone.utc) - timedelta(minutes=2)
        dispatch_build([aoi for aoi, _ in to_build])
        assets = wait_for_build([aoi['name'] for aoi, _ in to_build], started)
        for aoi, baseline_path in to_build:
            download_asset(assets[f"{aoi['name']}_base.tif"], baseline_path)
    print('Baselines configured!')

if __name__ == '__main__':
    main()