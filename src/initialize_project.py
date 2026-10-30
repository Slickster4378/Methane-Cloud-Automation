"""
Initialize Project v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 09/01/2026

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

def initialize_database(project):
    """
    Creates the SQLite database for a project AOI if it does not already exist.

    Args:
        project (dict): Project dictionary from config.json.
    """
    for aoi in config['aois']:
        db_dir = aoi['paths']['database']
        database_path = os.path.join(db_dir, 'database.db')
        if os.path.exists(database_path):
            print(f"AOI {aoi['name']} has an active tracking database. Skipping build.")
            continue
        
        connection = sqlite3.connect(database_path)
        cursor = connection.cursor()

        # Image Registry
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images(
                image_id TEXT PRIMARY KEY,
                acquisition_date TEXT,
                processing_date TEXT,
                cloud_cover REAL,
                processed INTEGER DEFAULT 0,
                plume_detected INTEGER DEFAULT 0,
                cache_directory TEXT
            )
        """)

        # Methane Plume Detections
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS detections(
                detection_id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id TEXT,
                detection_time TEXT,
                max_anomaly REAL,
                plume_pixels INTEGER,
                raster_directory TEXT,
                FOREIGN KEY(image_id)
                    REFERENCES images(image_id)
            )
        """)

        # Baseline Parameters
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS baseline(
                baseline_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created TEXT,
                start_date TEXT,
                end_date TEXT,
                baseline_file TEXT
            )
        """)

        # Metadata Registry
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata(
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cursor.executemany("""
            INSERT OR IGNORE INTO metadata (key, value) VALUES (?, ?)
        """, [
            ('database_version', '1.0.0'),
            ('last_baseline_update', ''),
            ('last_scene_processed', '')
        ])

        connection.commit()
        connection.close()

        print(f'Initialized database: {database_path}')
    print('All databases initialized!')

def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python initialize_project.py <path_to_config.json>")
    create_dirs(sys.argv[1])
    initialize_database(config['project_folder'])

if __name__ == '__main__':
    main()