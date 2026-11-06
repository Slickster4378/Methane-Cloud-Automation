# Sentinel-2 Methane Detection Pipeline
**Crude Accountability**

Created by: Andrew Zitnik

A Windows-based pipeline that monitors oil and gas areas of interest (AOIs) in Kazakhstan for large methane plumes using Sentinel-2 L2A shortwave infrared (SWIR) imagery from the Copernicus Data Space Ecosystem (CDSE). It builds a methane-free baseline for each AOI, compares new daily imagery against that baseline, and records candidate detections in a SQLite database alongside the daily methane ratio rasters.

Currently configured AOIs: **Tengiz** and **Kokzhide**.

## How It Works

Methane absorbs strongly in Sentinel-2 **Band 12** (about 2190 nm) and only weakly in **Band 11** (about 1610 nm). Dividing B11 by B12 gives a per-pixel ratio that rises where methane is present above a scene.

1. **Baseline.** For each AOI the pipeline streams up to 30 low-cloud (< 10%) Sentinel-2 L2A scenes from 2020 to 2025, computes the B11/B12 ratio for each, and takes the **25th percentile across time** per pixel. Plumes are transient, so they are suppressed in the composite, leaving a methane-free reference.
2. **Daily check.** New Sentinel-2 scenes are compared against the baseline. Pixels that deviate beyond a threshold are flagged as plume candidates.
3. **Record keeping.** Each processed scene and every detection is written to the SQLite database, and the day's methane ratio raster is stored locally and in the GitHub repository.

All imagery is streamed over the CDSE S3 endpoint with GDAL's `/vsis3/` driver and clipped to the AOI bounding box on read, so full scenes are never downloaded.

## Requirements

- Windows 10 or 11 (the launcher is a `.bat` file)
- Internet access
- A Copernicus Data Space Ecosystem account with **S3 access keys** (see [Credentials and Secrets](#credentials-and-secrets))
- A GitHub repository for this project with Actions enabled
- Python 3.13 or newer (the launcher installs Python 3.13 automatically if none is found)

Additional packages are needed by individual scripts and must also be present in `requirements.txt`

## License

License to be determined. Contact Crude Accountability before reusing or redistributing this code.

## Credits

Developed by Andrew Zitnik for **Crude Accountability**. Imagery courtesy of the European Union / ESA Copernicus programme, accessed through the Copernicus Data Space Ecosystem.
