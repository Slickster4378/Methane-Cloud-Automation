"""
Baseline Builder v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/04/2026

This script streams a baseline image mosaic of the AOI, creating it first if it does not already exist.
"""

import os, sys, rioxarray, xarray, rasterio # type: ignore
import config_util as cutil
from pystac.item import Item # type: ignore
from pydrive2.auth import GoogleAuth  # type: ignore
from pydrive2.drive import GoogleDrive  # type: ignore
from rasterio.session import AWSSession # type: ignore

config = ''

AWS_KEY = os.environ.get("USER_AWS_ACCESS_KEY_ID")
AWS_SECRET = os.environ.get("USER_AWS_SECRET_ACCESS_KEY")

def get_gdrive():
    """Initializes and authenticates the Google Drive connection."""
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth() 
    return GoogleDrive(gauth)

def download_base(aoi_name: str, local_dest_path: str) -> bool:
    """
    Searches Google Drive for an existing baseline file.
    Downloads it directly to the local project path if found.
    """
    drive = get_gdrive()
    filename = f"{aoi_name}_base.tif"
    # Query Google Drive for the specific file name
    file_list = drive.ListFile({'q': f"title = '{filename}' and trashed = false"}).GetList()
    if file_list:
        print(f"[GDRIVE MATCH] Found baseline for {aoi_name} on cloud drive. Downloading locally...")
        os.makedirs(os.path.dirname(local_dest_path), exist_ok=True)
        file_list[0].GetContentFile(local_dest_path)
        print(f"-> Successfully downloaded to: {local_dest_path}")
        return True
    print(f"[GDRIVE MISS] No existing baseline found on Google Drive for {aoi_name}.")
    return False

def upload_base(aoi_name: str, local_path: str):
    """Uploads a newly computed baseline file from local disk up to Google Drive."""
    drive = get_gdrive()
    filename = f"{aoi_name}_base.tif"
    print(f"Uploading fresh baseline copy to Google Drive: {filename}")
    gdrive_file = drive.CreateFile({'title': filename})
    gdrive_file.SetContentFile(local_path)
    gdrive_file.Upload()
    print("Upload to Google Drive complete!")

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
        "AWS_ACCESS_KEY_ID": AWS_KEY,
        "AWS_SECRET_ACCESS_KEY": AWS_SECRET,
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
        if os.path.exists(baseline_path):
            print(f'AOI {aoi['name']} already has a baseline mosaic. Skipping...\n')
            continue
        success = download_base(aoi['name'], baseline_path)
        if success:
            print('Successfully configured baseline from Google Drive')
        else:
            candidates = fetch_candidates(aoi)
            generate_baseline(aoi, candidates, baseline_path)
            upload_base(aoi['name'], baseline_path)

if __name__ == "__main__":
    main()
