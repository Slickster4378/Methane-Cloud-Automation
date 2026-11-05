"""
Initialize Project v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/04/2026

This script loads a previously existing config.json, then creates the folder file directories and database.
"""
import os, sys, sqlite3
import config_util as cutil

config = {}

def create_dirs(arg: str):
    """
    Creates all project directories at specified project folder
    
    Args:
        arg (str): Path to project directory.
    """
    global config
    config = cutil.load_json(arg)
    for aoi in config['aois']:
        # Create directories for each AOI
        for path_key, raw_path in aoi['paths'].items():
            clean_path = os.path.abspath(raw_path.replace('\\', '/'))
            aoi['paths'][path_key] = clean_path
            if not os.path.exists(clean_path):
                try:
                    os.makedirs(clean_path,exist_ok=True)
                except OSError:
                    sys.exit(f'CRITICAL: Failed tracking initialization at: {clean_path}')
        # Create the directory for the single project database
    config['database'] = os.path.abspath(config['database'].replace('\\', '/'))
    database_dir = os.path.dirname(config['database'])
    if not os.path.exists(database_dir):
        try:
            os.makedirs(database_dir, exist_ok=True)
        except OSError:
            sys.exit(f'CRITICAL: Failed tracking initialization at: {database_dir}')

def initialize_database():
    """
    Creates the single SQLite database for the project if it does not already exist.
    """
    database_path = config['database']
    if os.path.exists(database_path):
        print('Project has an active tracking database. Skipping build.')
        return

    connection = sqlite3.connect(database_path)
    cursor = connection.cursor()

    # Write-ahead logging lets reports read while the pipeline writes
    cursor.execute('PRAGMA journal_mode = WAL')

    # Image Registry (one row per scene per AOI)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS images(
            aoi TEXT NOT NULL,
            image_id TEXT NOT NULL,
            acquisition_date TEXT,
            processing_date TEXT,
            cloud_cover REAL,
            processed INTEGER DEFAULT 0,
            plume_detected INTEGER DEFAULT 0,
            cache_directory TEXT,
            PRIMARY KEY (aoi, image_id)
        ) WITHOUT ROWID
    """)

    # Methane Plume Detections (one row per detected scene per AOI)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detections(
            detection_id INTEGER PRIMARY KEY AUTOINCREMENT,
            aoi TEXT NOT NULL,
            image_id TEXT NOT NULL,
            detection_time TEXT,
            max_anomaly REAL,
            plume_pixels INTEGER,
            raster_directory TEXT,
            UNIQUE (aoi, image_id),
            FOREIGN KEY (aoi, image_id)
                REFERENCES images (aoi, image_id)
        )
    """)

    # Metadata Registry (one high-water mark per AOI)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata(
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.executemany("""
        INSERT OR IGNORE INTO metadata (key, value) VALUES (?, ?)
    """, [('database_version', '2.0.0')] + [
        (f"last_scene_processed:{aoi['name']}", '') for aoi in config['aois']
    ])

    connection.commit()
    connection.close()

    print(f'Initialized database: {database_path}')

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python initialize_project.py <path_to_config.json>")
    create_dirs(sys.argv[1])
    initialize_database()

if __name__ == '__main__':
    main()