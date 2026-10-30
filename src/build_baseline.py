"""
Baseline Builder v1.0.0
Crude Accountability
Created by: Andrew Zitnik

This script streams a baseline image mosaic of the AOI, creating it first if it does not already exist.
"""

import os, sys, rioxarray, xarray, rasterio, boto3 # type: ignore
import config_util as cutil
from pystac.item import Item # type: ignore
from botocore.exceptions import ClientError # type: ignore
from rasterio.session import AWSSession # type: ignore

config = ''

S3_BUCKET_NAME = os.environ.get("USER_CLOUD_BUCKET_NAME", "crude-accountability-baselines")
AWS_KEY = os.environ.get("USER_AWS_ACCESS_KEY_ID")
AWS_SECRET = os.environ.get("USER_AWS_SECRET_ACCESS_KEY")

def get_s3_client():
    """Initializes a secure connection to your private cloud storage vault."""
    return boto3.client(
        's3',
        aws_access_key_id=AWS_KEY,
        aws_secret_access_key=AWS_SECRET
    )

def check_cloud_copy(aoi_name: str) -> str | None:
    """
    Checks cloud bucket to see if a baseline has already been built.
    Returns the S3 Key if found, otherwise returns None.
    """
    s3 = get_s3_client()
    s3_key = f"baselines/{aoi_name}_base.tif"
    try:
        s3.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        print(f"[CLOUD MATCH] Found an existing baseline in the cloud for {aoi_name}.")
        return s3_key
    except ClientError as e:
        if e.response['Error']['Code'] == "404":
            print(f"[CLOUD MISS] No baseline found in cloud storage for {aoi_name}. Will build fresh.")
            return None
        raise e

def cloud_download(s3_key: str, local_path: str) -> None:
    """Downloads a pre-built baseline directly from  cloud storage."""
    s3 = get_s3_client()
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    print(f"Downloading baseline from cloud vault -> {local_path}")
    s3.download_file(S3_BUCKET_NAME, s3_key, local_path)
    print("Cloud download complete.")

def cloud_upload(local_path: str, aoi_name: str) -> None:
    """Uploads a newly generated baseline file up to the cloud storage vault."""
    s3 = get_s3_client()
    s3_key = f"baselines/{aoi_name}_base.tif"
    print(f"Uploading fresh baseline copy to cloud storage -> {s3_key}")
    s3.upload_file(local_path, S3_BUCKET_NAME, s3_key)
    print("Cloud backup successful.")

def fetch_candidates(aoi: dict) -> list[Item]:
    """
    Automatically fetches a list of cloudless image items within the AOI via STAC
    
    Args:
        aoi (dict): Parsed json dictionary file with aoi info

    Returns:
        candidates (list[pystac.item]): A list containing  STAC items
    """
    print(f'Creating Baseline: {aoi['name']}')
    print('Connecting to Copernicus STAC to fetch candidates for Cloudless Mosaic Baseline...')
    catalog = cutil.stagger_results('https://stac.dataspace.copernicus.eu/v1')
    if catalog: search = catalog.search(
        collections=['sentinel-2-l2a'],
        bbox=aoi['coords'],
        datetime='2020-01-01/2025-12-31',
        query={"eo:cloud_cover": {"lt": 10}} 
    )
    items = list(search.items())
    if len(items) == 0:
        raise Exception(f'No cloudless items found for the AOI {aoi['name']}.')
    print(f'Found {len(items)} candidate images.')
    return items

def generate_baseline(aoi: dict, candidates: list[Item], baseline_path: str) -> None:
    """
    Extract the  geotiff  for Band 11 and Band 12 from the STAC, generate the baseline ratio.
    Optimized for CDSE JP2 data streaming over S3 to generate a methane flaring baseline.

    Args:
        aoi (dict): Parsed json dictionary file with aoi info
        baseline (list[pystac.Item]): STAC item containing core metadata
        baseline_path (str): path to baseline file
    """

    # Force GDAL to use S3 streaming optimized for JPEG2000 layers
    os.environ.update({
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RE_BUFS": "YES",
        "GDAL_HTTP_MAX_RETRY": "5",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".jp2,.tif",
        "AWS_S3_ENDPOINT": "eodata.dataspace.copernicus.eu",
        "AWS_VIRTUAL_HOSTING": "FALSE",
        "AWS_ACCESS_KEY_ID": "6N7LG8TCCCGGRQW95I32",
        "AWS_SECRET_ACCESS_KEY": "TBC2QSpuOcvHWSVVzzrb7CNrXeR2lCRHSzeyx5mu",
    })

    bbox = aoi['coords']
    ratio_maps = []

    print(f"Generating methane-free baseline for: {aoi['name']}")

    # Open single AWSSession context targeting the CDSE infrastructure
    processed = 0
    max_img = 30
    master_coords = None
    with rasterio.Env(AWSSession(endpoint_url="https://eodata.dataspace.copernicus.eu")):
        for item in candidates:
            if processed >= max_img:
                break
            date_str = item.properties.get('datetime', 'unknown')[:10]
            b11_url = item.assets['B11_20m'].href
            b12_url = item.assets['B12_20m'].href
            if b11_url.startswith("https://eodata.dataspace.copernicus.eu"):
                b11_url = b11_url.replace("https://eodata.dataspace.copernicus.eu", "/vsis3/eodata")
                b12_url = b12_url.replace("https://eodata.dataspace.copernicus.eu", "/vsis3/eodata")
            try:
                # --- PROCESS BANDS ---
                print('Streaming B11 (Continuum proxy via S3)...')
                with rioxarray.open_rasterio(b11_url, chunks={'x': 512, 'y': 512}) as b11_src:
                    b11_clipped = b11_src.rio.clip_box(*bbox, crs="EPSG:4326")
                    b11_data = b11_clipped.load()
                print('Streaming B12 (Methane absorption proxy via S3)...')
                with rioxarray.open_rasterio(b12_url, chunks={'x': 512, 'y': 512}) as b12_src:
                    b12_clipped = b12_src.rio.clip_box(*bbox, crs="EPSG:4326")
                    if master_coords is not None and b12_clipped.shape == master_coords['shape']:
                        b12_data = b12_clipped.load()
                    else:
                        b12_data = b12_clipped.rio.reproject_match(b11_data).load()
                # Calculate ratio for this specific day
                b12_data.values[b12_data.values == 0] = 1
                day_ratio = b11_data / b12_data
                if processed == 0:
                    master_coords = {'shape': day_ratio.shape, 'crs': day_ratio.rio.crs}
                day_ratio = day_ratio.expand_dims(time=[date_str])
                ratio_maps.append(day_ratio)
                print(f"-> Processed scene from date: {date_str}")
                processed += 1
            except Exception as e:
                print(f"Skipping date {date_str} due to streaming error: {e}")
                continue
    if not ratio_maps:
        raise ValueError("Failed to process any candidate images.")

    # Combine all images along the new time dimension
    print('Calculating absorption ratio...')
    stacked_ratios = xarray.concat(ratio_maps, dim='time')
    print("Calculating temporal median to erase active plumes...")
    baseline_ratio = stacked_ratios.quantile(0.25, dim='time', skipna=True)
    if 'quantile' in baseline_ratio.coords:
        baseline_ratio = baseline_ratio.drop_vars('quantile')
    # Restore GeoTIFF information and save baseline
    baseline_ratio.rio.write_crs(master_coords['crs'], inplace=True)
    out_path = baseline_path.replace('\\', '/')
    os.makedirs(os.path.dirname(out_path),exist_ok=True)
    print(f"Saving emission-free baseline -> {out_path}")
    baseline_ratio.rio.to_raster(
        out_path,
        driver='GTiff',
        dtype='float32',
    )
    print("Baseline generation complete!\n")

def main():
    global config
    if len(sys.argv) < 2:
        sys.exit("Failure importing config.json")
    config = cutil.load_json(sys.argv[1])
    for aoi in config['aois']:
        baseline_path = os.path.join(aoi['paths']['baseline'], 'base.tif').replace('\\', '/')
        if not os.path.exists(baseline_path):
            cloud_s3_key = check_cloud_copy(aoi['name'])
            if cloud_s3_key:
                cloud_download(cloud_s3_key, baseline_path)
            else:
                candidates = fetch_candidates(aoi)
                generate_baseline(aoi, candidates, baseline_path)
                cloud_upload(baseline_path, aoi['name'])
        else:
            print(f'AOI {aoi['name']} already has a baseline mosaic. Skipping...\n')

if __name__ == "__main__":
    main()
