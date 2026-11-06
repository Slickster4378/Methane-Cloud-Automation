"""
Check New Data v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/05/2026

This script checks Copernicus for Sentinel-2 scenes acquired since the last processed scene of each AOI,
builds the day's B11/B12 ratio image, flags plumes against the baseline, saves the image locally and to GitHub,
and records the results in the pipeline database.
"""

import os, sys, base64, requests, numpy, rioxarray, rasterio # type: ignore
import config_util as cutil
import update_db as udb
from datetime import datetime, timedelta, timezone
from pystac.item import Item # type: ignore
from scipy import ndimage # type: ignore
from rioxarray.exceptions import NoDataInBounds # type: ignore

config = {}

AWS_KEY = os.environ.get('CDSE_S3_ACCESS_KEY')
AWS_SECRET = os.environ.get('CDSE_S3_SECRET_KEY')
GITHUB_TOKEN = os.environ.get('GITHUB_PAT')

# Search and detection settings (starting values, tune against real scenes)
LOOKBACK_DAYS = 10                  # only used the first time an AOI is checked
MAX_CLOUD = 30                      # max scene-level cloud cover (%)
MIN_COVERAGE = 0.5                  # min fraction of the AOI that must be clear, valid pixels
ANOMALY_SIGMA = 5.0                 # robust z-score a pixel must exceed
MIN_PLUME_PIXELS = 20               # smallest connected cluster that counts as a plume
BAD_SCL = [0, 1, 3, 8, 9, 10, 11]   # no data, saturated, cloud shadow, cloud (med/high), cirrus, snow

def configure_gdal() -> None:
    """Points GDAL at the Copernicus S3 endpoint using the Copernicus-issued S3 keys."""
    if not AWS_KEY or not AWS_SECRET:
        sys.exit('CRITICAL: USER_AWS_ACCESS_KEY_ID and USER_AWS_SECRET_ACCESS_KEY must be set as environment variables.')
    os.environ.update({
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RE_BUFS": "YES",
        "GDAL_HTTP_MAX_RETRY": "5",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".jp2,.tif",
        "AWS_S3_ENDPOINT": "eodata.dataspace.copernicus.eu",
        "AWS_VIRTUAL_HOSTING": "FALSE",
        "AWS_ACCESS_KEY_ID": AWS_KEY,
        "AWS_SECRET_ACCESS_KEY": AWS_SECRET,
    })

def github_enabled() -> bool:
    """Returns True only if both the github block in config.json and the GITHUB_PAT variable exist."""
    return bool(config.get('github')) and bool(GITHUB_TOKEN)

def to_s3(href: str) -> str:
    """Converts a CDSE https asset link into a GDAL /vsis3 path."""
    return href.replace('https://eodata.dataspace.copernicus.eu', '/vsis3/eodata')

def default_start() -> str:
    """Returns the search start used the first time an AOI is checked."""
    start = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    return start.strftime('%Y-%m-%dT%H:%M:%SZ')

def fetch_new_scenes(aoi: dict, start: str) -> list[Item]:
    """
    Fetches only the scenes acquired at or after the AOI watermark via STAC.

    Args:
        aoi (dict): Parsed json dictionary file with aoi info
        start (str): ISO timestamp to search from

    Returns:
        list[pystac.Item]: New scenes, oldest first
    """
    catalog = cutil.stagger_results('https://stac.dataspace.copernicus.eu/v1')
    if not catalog:
        raise ConnectionError('Could not open the Copernicus STAC catalog.')
    search = catalog.search(
        collections=['sentinel-2-l2a'],
        bbox=cutil.get_bbox(aoi),
        datetime=f'{start}/..',
        query={"eo:cloud_cover": {"lt": MAX_CLOUD}}
    )
    items = list(search.items())
    items.sort(key=lambda item: item.properties['datetime'])
    return items

def read_band(href: str, bbox: list, like=None):
    """
    Streams one band clipped to the AOI.

    Args:
        href (str): /vsis3 path to the band
        bbox (list): [lon_min, lat_min, lon_max, lat_max]
        like (DataArray): If given and the grid differs, the band is reprojected to match it

    Returns:
        DataArray: Loaded, clipped band
    """
    with rioxarray.open_rasterio(href) as src:
        data = src.rio.clip_box(*bbox, crs="EPSG:4326").load()
    if like is not None and data.shape != like.shape:
        data = data.rio.reproject_match(like)
    return data

def build_ratio(item: Item, bbox: list, baseline):
    """
    Builds the day's B11/B12 ratio (same formula as the baseline), masks clouds with SCL,
    and aligns the result to the baseline grid so every daily image has the same shape.

    Args:
        item (pystac.Item): Scene to process
        bbox (list): [lon_min, lat_min, lon_max, lat_max]
        baseline (DataArray): Loaded baseline raster

    Returns:
        DataArray | None: Ratio on the baseline grid, or None if the scene has no data inside the AOI
    """
    try:
        b11 = read_band(to_s3(item.assets['B11_20m'].href), bbox)
        b12 = read_band(to_s3(item.assets['B12_20m'].href), bbox, like=b11)
        scl_asset = item.assets.get('SCL_20m')
        scl = read_band(to_s3(scl_asset.href), bbox, like=b11) if scl_asset else None
    except NoDataInBounds:
        return None
    b11f = b11.astype('float32')
    b12f = b12.astype('float32')
    ratio = (b11f / b12f.where(b12f > 0)).where(b11f > 0)
    if scl is not None:
        ratio.values[numpy.isin(scl.values, BAD_SCL)] = numpy.nan
    ratio.rio.write_crs(b11.rio.crs, inplace=True)
    ratio.rio.write_nodata(numpy.nan, inplace=True)
    return ratio.rio.reproject_match(baseline)

def detect_plume(ratio, baseline) -> dict:
    """
    Compares the daily ratio to the baseline and looks for a connected cluster of anomalous pixels.
    Uses a robust z-score (median/MAD) so a scene-wide offset cancels out and the plume itself
    does not inflate the noise estimate.

    Args:
        ratio (DataArray): Daily ratio on the baseline grid
        baseline (DataArray): Loaded baseline raster

    Returns:
        dict: coverage, detected, max_anomaly, plume_pixels, anomaly (2D array)
    """
    anomaly = ratio.values[0] - baseline.values[0]
    valid = numpy.isfinite(anomaly)
    result = {
        'coverage': float(valid.mean()), 'detected': False,
        'max_anomaly': 0.0, 'plume_pixels': 0, 'anomaly': anomaly
    }
    if result['coverage'] < MIN_COVERAGE:
        return result
    center = numpy.median(anomaly[valid])
    sigma = 1.4826 * numpy.median(numpy.abs(anomaly[valid] - center))
    if sigma == 0:
        return result
    with numpy.errstate(invalid='ignore'):
        mask = ((anomaly - center) / sigma) > ANOMALY_SIGMA
    labels, count = ndimage.label(mask)
    if count == 0:
        return result
    sizes = numpy.bincount(labels.ravel())[1:]
    largest = int(sizes.argmax()) + 1
    if sizes[largest - 1] < MIN_PLUME_PIXELS:
        return result
    cluster = labels == largest
    result.update(
        detected=True,
        max_anomaly=float(anomaly[cluster].max()),
        plume_pixels=int(sizes[largest - 1])
    )
    return result

def save_raster(data, path: str) -> None:
    """
    Saves a raster as a compressed GeoTIFF.

    Args:
        data (DataArray): Raster to save
        path (str): Destination file path
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data.rio.to_raster(path, driver='GTiff', dtype='float32', compress='deflate', predictor=3, tiled=True)

def upload_to_github(local_path: str, repo_path: str) -> None:
    """
    Commits a file to the GitHub repository through the REST contents API.
    Raises on failure so the scene is retried on the next run.

    Args:
        local_path (str): File on disk
        repo_path (str): Destination path inside the repository
    """
    gh = config['github']
    url = f"https://api.github.com/repos/{gh['repo']}/contents/{repo_path}"
    with open(local_path, 'rb') as f:
        content = base64.b64encode(f.read()).decode('ascii')
    response = requests.put(
        url,
        headers={
            'Authorization': f'Bearer {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        },
        json={
            'message': f'Add methane ratio image {repo_path}',
            'content': content,
            'branch': gh.get('branch', 'main')
        },
        timeout=120
    )
    if response.status_code in (200, 201):
        print(f'-> Uploaded to GitHub: {repo_path}')
    elif response.status_code == 422 and 'sha' in response.text:
        print(f'-> Already on GitHub: {repo_path}')
    else:
        raise RuntimeError(f'GitHub upload failed ({response.status_code}): {response.text[:200]}')

def process_aoi(conn, aoi: dict) -> int:
    """
    Processes every new scene for one AOI.

    Args:
        conn (sqlite3.Connection): Open database connection
        aoi (dict): Parsed json dictionary file with aoi info

    Returns:
        int: Number of scenes that failed
    """
    name = aoi['name']
    bbox = aoi['coords']
    baseline_path = os.path.join(cutil.clean_path(aoi['paths']['baseline']), 'base.tif')
    if not os.path.exists(baseline_path):
        print(f'[SKIP] {name} has no baseline yet.\n')
        return 0

    start = udb.get_watermark(conn, name) or default_start()
    try:
        scenes = fetch_new_scenes(aoi, start)
    except Exception as e:
        print(f'FAILED to search for new scenes for {name}: {e}', file=sys.stderr)
        return 1
    print(f'{name}: {len(scenes)} scene(s) at or after {start}')
    if not scenes:
        return 0

    baseline = rioxarray.open_rasterio(baseline_path).load()   # loaded once per AOI, not per scene
    cache_dir = cutil.clean_path(aoi['paths']['cache'])
    detect_dir = cutil.clean_path(aoi['paths']['detections'])
    gh_folder = config.get('github', {}).get('image_folder', 'images')

    mark = ''
    blocked = False
    failures = 0
    for item in scenes:
        image_id = item.id
        acquired = item.properties['datetime'][:19] + 'Z'
        date = acquired[:10]

        # Already handled on a previous run (primary key lookup)
        if udb.get_status(conn, name, image_id) in (1, 2):
            if not blocked:
                mark = acquired
            continue

        scene = {
            'image_id': image_id,
            'acquisition_date': date,
            'cloud_cover': item.properties.get('eo:cloud_cover'),
            'processed': 1,
            'plume_detected': 0,
            'cache_directory': ''
        }
        try:
            ratio = build_ratio(item, bbox, baseline)
            result = detect_plume(ratio, baseline) if ratio is not None else None
            if result is None or result['coverage'] < MIN_COVERAGE:
                scene['processed'] = 2
                udb.record_scene(conn, name, scene)
                print(f'-> Skipped {image_id}: too little clear coverage of the AOI.')
            else:
                ratio_file = f'{date}_{image_id}.tif'
                ratio_path = os.path.join(cache_dir, ratio_file)
                save_raster(ratio, ratio_path)
                if github_enabled():
                    upload_to_github(ratio_path, f'{gh_folder}/{name}/{ratio_file}')
                detection = None
                if result['detected']:
                    detect_path = os.path.join(detect_dir, ratio_file.replace('.tif', '_anomaly.tif'))
                    save_raster(ratio.copy(data=result['anomaly'][numpy.newaxis, :, :]), detect_path)
                    detection = {
                        'max_anomaly': result['max_anomaly'],
                        'plume_pixels': result['plume_pixels'],
                        'raster_directory': detect_path
                    }
                scene['plume_detected'] = int(result['detected'])
                scene['cache_directory'] = ratio_path
                udb.record_scene(conn, name, scene, detection)
                status = 'PLUME DETECTED' if result['detected'] else 'no plume'
                print(f'-> Processed {image_id} ({date}): {status}')
        except Exception as e:
            print(f'FAILED scene {image_id} for {name}: {e}', file=sys.stderr)
            blocked = True   # watermark stops here so this scene is retried next run
            failures += 1
            continue
        if not blocked:
            mark = acquired

    if mark:
        udb.set_watermark(conn, name, mark)
    print()
    return failures

def main():
    global config
    if len(sys.argv) < 2:
        sys.exit("Usage: python check_new_data.py <path_to_config.json>")
    config = cutil.load_json(sys.argv[1])
    configure_gdal()
    if not github_enabled():
        print('WARNING: GitHub upload disabled (missing github block in config.json or GITHUB_PAT variable).\n')
    conn = udb.connect(config)
    failures = 0
    try:
        with rasterio.Env(AWS_S3_ENDPOINT='eodata.dataspace.copernicus.eu', AWS_VIRTUAL_HOSTING='FALSE'):
            for aoi in config['aois']:
                failures += process_aoi(conn, aoi)
    finally:
        conn.close()
    if failures:
        sys.exit(f'{failures} scene(s) failed. They will be retried on the next run.')
    print('Daily data check complete!')

if __name__ == "__main__":
    main()