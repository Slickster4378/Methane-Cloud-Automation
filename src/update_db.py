"""
Update Database v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/04/2026

This script is imported by check_new_data.py to write daily scene results and methane detections into the project database.
Run directly with a config.json path to print a summary of what the database currently holds.
"""

import os, sys, sqlite3
from datetime import datetime
import config_util as cutil

def connect(config: dict) -> sqlite3.Connection:
    """
    Opens the single project database with foreign key enforcement turned on.

    Args:
        config (dict): Parsed config.json dictionary.

    Returns:
        sqlite3.Connection: Open database connection. The caller is responsible for closing it.
    """
    database_path = os.path.abspath(config['database'].replace('\\', '/'))
    if not os.path.isfile(database_path):
        raise FileNotFoundError(
            f'Project database not found:\n{database_path}\n'
            'Delete bin\\.project_initialized and run the pipeline again.'
        )
    connection = sqlite3.connect(database_path)
    # SQLite ignores foreign keys unless this is set on every connection
    connection.execute('PRAGMA foreign_keys = ON')
    return connection

def get_last_scene_date(connection: sqlite3.Connection, aoi_name: str) -> str:
    """
    Reads the high-water mark for an AOI: the acquisition date of the newest scene already recorded.
    This is a single primary key lookup, so check_new_data.py can start its STAC search at this date
    instead of rescanning all history.

    Args:
        connection (sqlite3.Connection): Open project database connection.
        aoi_name (str): Name of the AOI from config.json.

    Returns:
        str: ISO date (YYYY-MM-DD), or an empty string if the AOI has no recorded scenes yet.
    """
    row = connection.execute(
        'SELECT value FROM metadata WHERE key = ?',
        (f'last_scene_processed:{aoi_name}',)
    ).fetchone()
    return row[0] if row else ''

def load_processed(connection: sqlite3.Connection, aoi_name: str, since: str = '') -> set[str]:
    """
    Loads the IDs of scenes already processed on or after a date into a set.
    Only the rows at the boundary of the STAC search window are returned, so the set stays small
    and each membership check afterward is O(1).

    Args:
        connection (sqlite3.Connection): Open project database connection.
        aoi_name (str): Name of the AOI from config.json.
        since (str): ISO date (YYYY-MM-DD). Normally the value from get_last_scene_date().

    Returns:
        set[str]: Image IDs that are already processed.
    """
    rows = connection.execute(
        'SELECT image_id FROM images WHERE aoi = ? AND processed = 1 AND acquisition_date >= ?',
        (aoi_name, since)
    )
    return {row[0] for row in rows}

def update_database(connection: sqlite3.Connection, aoi_name: str, results: list[dict], advance_mark: bool = True) -> int:
    """
    Writes a day's scene results and detections for one AOI in a single transaction.
    Safe to re-run: existing scenes and detections are updated in place instead of duplicated.

    Each dictionary in results must contain:
        image_id (str), acquisition_date (str, YYYY-MM-DD)
    and may contain:
        cloud_cover (float), cache_directory (str), processed (bool, default True),
        plume_detected (bool, default False), max_anomaly (float), plume_pixels (int), raster_directory (str)

    A detection row is written for every result where plume_detected is True.

    Args:
        connection (sqlite3.Connection): Open project database connection.
        aoi_name (str): Name of the AOI from config.json.
        results (list[dict]): Scene results from check_new_data.py.
        advance_mark (bool): Moves the AOI high-water mark forward to the newest scene date.
            Pass False if any scene failed, so the failed scene is retried on the next run.

    Returns:
        int: Number of detections written.
    """
    if not results:
        return 0
    processing_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    image_rows = []
    detection_rows = []
    # One pass over the results builds both row lists
    for result in results:
        detected = bool(result.get('plume_detected', False))
        image_rows.append((
            aoi_name,
            result['image_id'],
            result['acquisition_date'],
            processing_date,
            result.get('cloud_cover'),
            int(result.get('processed', True)),
            int(detected),
            result.get('cache_directory'),
        ))
        if detected:
            detection_rows.append((
                aoi_name,
                result['image_id'],
                processing_date,
                result.get('max_anomaly'),
                result.get('plume_pixels'),
                result.get('raster_directory'),
            ))
    # ISO dates sort chronologically as plain text, so max() gives the newest scene
    newest = max(result['acquisition_date'] for result in results)

    # "with connection" commits everything together, or rolls everything back if any statement fails
    with connection:
        connection.executemany("""
            INSERT INTO images (
                aoi, image_id, acquisition_date, processing_date,
                cloud_cover, processed, plume_detected, cache_directory
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(aoi, image_id) DO UPDATE SET
                processing_date = excluded.processing_date,
                cloud_cover = excluded.cloud_cover,
                processed = excluded.processed,
                plume_detected = excluded.plume_detected,
                cache_directory = excluded.cache_directory
        """, image_rows)
        connection.executemany("""
            INSERT INTO detections (
                aoi, image_id, detection_time,
                max_anomaly, plume_pixels, raster_directory
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(aoi, image_id) DO UPDATE SET
                detection_time = excluded.detection_time,
                max_anomaly = excluded.max_anomaly,
                plume_pixels = excluded.plume_pixels,
                raster_directory = excluded.raster_directory
        """, detection_rows)
        if advance_mark:
            # The WHERE clause keeps the mark from ever moving backward
            connection.execute("""
                INSERT INTO metadata (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                WHERE excluded.value > metadata.value
            """, (f'last_scene_processed:{aoi_name}', newest))

    print(f'[{aoi_name}] Recorded {len(image_rows)} scene(s), {len(detection_rows)} detection(s).')
    return len(detection_rows)

def main():
    if len(sys.argv) < 2:
        sys.exit('Usage: python update_db.py <path_to_config.json>')
    config = cutil.load_json(sys.argv[1])
    connection = connect(config)
    try:
        rows = connection.execute("""
            SELECT aoi, COUNT(*), SUM(plume_detected), MAX(acquisition_date)
            FROM images
            GROUP BY aoi
        """).fetchall()
    finally:
        connection.close()
    if not rows:
        print('Database is empty.')
        return
    for aoi_name, scenes, plumes, newest in rows:
        print(f'{aoi_name}: {scenes} scene(s), {plumes} with plumes, newest scene {newest}')

if __name__ == '__main__':
    main()