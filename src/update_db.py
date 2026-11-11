"""
Update Database v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/10/2026

This script holds the database functions that check_new_data.py uses to read and write the single pipeline database.
"""

import os, sqlite3
from datetime import datetime
import config_util as cutil

def timestamp() -> str:
    """Returns the current local time as a database-friendly string."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def connect(config: dict) -> sqlite3.Connection:
    """
    Opens a connection to the pipeline database.
    Refuses to create a new file, because sqlite3 silently makes an empty one that has no tables.

    Args:
        config (dict): Parsed configuration.

    Returns:
        sqlite3.Connection: Open database connection.
    """
    db_path = cutil.get_db_path(config)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f'Pipeline database not found:\n{db_path}')
    return sqlite3.connect(db_path)

def get_watermark(conn: sqlite3.Connection, aoi_name: str) -> str:
    """
    Reads the acquisition time the pipeline is fully caught up through for an AOI.
    This is one keyed lookup, so its cost does not grow with the image history.

    Args:
        conn (sqlite3.Connection): Open database connection.
        aoi_name (str): Name of the AOI.

    Returns:
        str: ISO timestamp, or an empty string if the AOI has never been checked.
    """
    row = conn.execute(
        'SELECT value FROM metadata WHERE key = ?',
        (f'last_scene_{aoi_name}',)
    ).fetchone()
    return row[0] if row else ''

def set_watermark(conn: sqlite3.Connection, aoi_name: str, acquired: str) -> None:
    """
    Moves the AOI watermark forward.

    Args:
        conn (sqlite3.Connection): Open database connection.
        aoi_name (str): Name of the AOI.
        acquired (str): ISO acquisition timestamp of the newest scene we are caught up through.
    """
    with conn:
        conn.execute(
            'INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)',
            (f'last_scene_{aoi_name}', acquired)
        )

def get_status(conn: sqlite3.Connection, aoi_name: str, image_id: str) -> int:
    """
    Looks up a scene by its primary key.

    Args:
        conn (sqlite3.Connection): Open database connection.
        aoi_name (str): Name of the AOI.
        image_id (str): STAC item id.

    Returns:
        int: processed value (1 = processed, 2 = skipped), or -1 if the scene is not registered.
    """
    row = conn.execute(
        'SELECT processed FROM images WHERE aoi = ? AND image_id = ?',
        (aoi_name, image_id)
    ).fetchone()
    return row[0] if row else -1

def record_scene(conn: sqlite3.Connection, aoi_name: str, scene: dict, detection: dict | None = None) -> None:
    """
    Writes a scene (and its detection, if any) in a single transaction.

    Args:
        conn (sqlite3.Connection): Open database connection.
        aoi_name (str): Name of the AOI.
        scene (dict): image_id, acquisition_date, cloud_cover, processed, plume_detected, cache_directory.
        detection (dict | None): max_anomaly, plume_pixels, raster_directory.
    """
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO images
                (aoi, image_id, acquisition_date, processing_date, cloud_cover,
                 processed, plume_detected, cache_directory)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            aoi_name, scene['image_id'], scene['acquisition_date'], timestamp(),
            scene['cloud_cover'], scene['processed'], scene['plume_detected'],
            scene['cache_directory']
        ))
        if detection:
            conn.execute("""
                INSERT INTO detections
                    (aoi, image_id, detection_time, max_anomaly, plume_pixels, raster_directory)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                aoi_name, scene['image_id'], timestamp(), detection['max_anomaly'],
                detection['plume_pixels'], detection['raster_directory']
            ))