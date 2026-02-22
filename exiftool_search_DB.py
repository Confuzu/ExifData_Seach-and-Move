import os
import subprocess
import sys
import configparser
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import logging
import sqlite3
from pathlib import Path
import json
import time
from utilities import validate_file_path

# Script directory (used for locating config, db, logs)
_script_dir = Path(__file__).resolve().parent

# --- Configuration ---

def _load_config():
    """Load configuration from config.ini, falling back to defaults."""
    config = configparser.ConfigParser()
    config_path = _script_dir / "config.ini"
    if config_path.exists():
        config.read(config_path)

    # General settings
    batch_size = config.getint('general', 'batch_size', fallback=100)
    max_workers = config.getint('general', 'max_workers', fallback=24)
    ext_str = config.get('general', 'valid_extensions', fallback='.jpg,.jpeg,.png')
    valid_extensions = {e.strip() for e in ext_str.split(',')}

    # Database settings
    db_name = config.get('database', 'db_name', fallback='statistics_image_metadata.db')

    # Logging settings
    log_level_str = config.get('logging', 'log_level', fallback='DEBUG')
    log_level = getattr(logging, log_level_str.upper(), logging.DEBUG)

    return {
        'batch_size': batch_size,
        'max_workers': max_workers,
        'valid_extensions': valid_extensions,
        'db_name': db_name,
        'log_level': log_level,
    }

_config = _load_config()

VALID_EXTENSIONS = _config['valid_extensions']
BATCH_SIZE = _config['batch_size']
MAX_WORKERS = _config['max_workers']

# --- Database path (configurable) ---

_db_path = _script_dir / _config['db_name']

def set_db_path(path):
    """Override the database path (useful for testing)."""
    global _db_path
    _db_path = Path(path)

def get_db_path():
    """Return the current database path."""
    return _db_path

# Keep module-level alias for backward compatibility
db_path = _db_path

# --- Logging (deferred setup, no import-time side effects) ---

logger_db = logging.getLogger('db')
_logger_initialized = False

def _ensure_logger():
    """Initialize file handler on first use, not at import time."""
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True

    log_file_path = _script_dir / "process_log_exiftool_search_DB.txt"
    logger_db.setLevel(_config['log_level'])
    file_handler_db = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler_db.setLevel(_config['log_level'])
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler_db.setFormatter(formatter)
    logger_db.addHandler(file_handler_db)


def db_connection():
    _ensure_logger()
    try:
        current_db_path = get_db_path()
        logger_db.info(f"Attempting to connect to database at: {current_db_path}")

        # Try to create the file if it doesn't exist
        if not os.path.exists(current_db_path):
            logger_db.info(f"Database file does not exist. Attempting to create it.")
            Path(current_db_path).touch(exist_ok=True)

        conn = sqlite3.connect(current_db_path)
        if conn is None:
            raise ValueError("Failed to establish a connection to the SQLite database.")
        logger_db.info("Successfully connected to the database.")
        return conn
    except sqlite3.Error as e:
        logger_db.error(f"SQLite error occurred while connecting to the database: {e}")
        raise
    except Exception as e:
        logger_db.error(f"Unexpected error occurred while connecting to the database: {e}")
        raise

def create_table():
    _ensure_logger()
    try:
        logger_db.info("Attempting to create table...")
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_metadata (
                    file_name TEXT UNIQUE,
                    file_path TEXT,
                    last_modified REAL,
                    metadata TEXT,
                    metadata_after_prompt TEXT,
                    last_updated REAL,
                    PRIMARY KEY (file_name)
                );
            """)
            conn.commit()
        logger_db.info(f"Table created or already exists in database: {get_db_path()}")
    except sqlite3.Error as e:
        logger_db.error(f"SQLite error occurred while creating table: {e}")
        raise
    except Exception as e:
        logger_db.error(f"Unexpected error occurred while creating table: {e}")
        raise

def normalize_metadata(metadata):
    if metadata is None:
        return None
    normalized_lines = []
    for line in metadata.split('\n'):
        if ': ' in line:
            key, value = line.split(': ', 1)
            normalized_key = key.strip().lower()
            normalized_value = value.strip()
            normalized_lines.append(f'{normalized_key}: {normalized_value}')
    return '\n'.join(normalized_lines)

def bulk_update_or_insert_metadata(metadata_list: List[Tuple[str, str, str]]):
    with db_connection() as conn:
        cursor = conn.cursor()
        current_time = time.time()
        for file_name, file_path, metadata in metadata_list:
            parts = metadata.split("Negative prompt:", 1)
            metadata_before_prompt = normalize_metadata(parts[0].strip()) if parts else None
            metadata_after_prompt = normalize_metadata(parts[1].strip()) if len(parts) > 1 else ""

            last_modified = os.path.getmtime(file_path)

            cursor.execute("""
                INSERT INTO file_metadata (file_name, file_path, last_modified, metadata, metadata_after_prompt, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_name)
                DO UPDATE SET
                    file_path = EXCLUDED.file_path,
                    last_modified = EXCLUDED.last_modified,
                    metadata = EXCLUDED.metadata,
                    metadata_after_prompt = EXCLUDED.metadata_after_prompt,
                    last_updated = EXCLUDED.last_updated;
                """, (file_name, file_path, last_modified, metadata_before_prompt, metadata_after_prompt, current_time))
        conn.commit()

def fetch_metadata(filepath: str, exiftool_cmd: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Fetch metadata for a single image file using ExifTool."""
    try:
        result = subprocess.run([exiftool_cmd, filepath], capture_output=True, text=True, check=True, timeout=30)
        return filepath, result.stdout, None
    except subprocess.TimeoutExpired:
        return filepath, None, f"Timeout processing file (>30s)"
    except subprocess.CalledProcessError as e:
        return filepath, None, f"Error processing file: {e}"
    except Exception as e:
        return filepath, None, f"Unexpected error: {e}"

def batch_update_metadata(file_list: List[str], exiftool_cmd: str,
                          max_workers: int = None, batch_size: int = None):
    """Updates the database with metadata from the specified image files."""
    if max_workers is None:
        max_workers = MAX_WORKERS
    if batch_size is None:
        batch_size = BATCH_SIZE

    _ensure_logger()
    create_table()  # Ensure the table exists before updating the database

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_metadata, filepath, exiftool_cmd) for filepath in file_list]

        results = []
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing images", unit="file"):
            filepath, metadata, error = future.result()
            if error:
                logger_db.error(f"Error processing file {filepath}: {error}")
            else:
                results.append((Path(filepath).name, filepath, metadata))

            # Batch insert into the database
            if len(results) >= batch_size:
                bulk_update_or_insert_metadata(results)
                results.clear()

        # Insert any remaining results
        if results:
            bulk_update_or_insert_metadata(results)

    logger_db.info("Finished adding Metadata from Images to the database.")

def update_file_path(old_path, new_path):
    _ensure_logger()
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            current_time = time.time()
            cursor.execute("""
                UPDATE file_metadata
                SET file_path = ?, last_updated = ?
                WHERE file_path = ?
            """, (new_path, current_time, old_path))
            if cursor.rowcount == 0:
                logger_db.warning(f"No database entry found for file: {old_path}")
            conn.commit()
        logger_db.info(f"Updated file path in database: {old_path} -> {new_path}")
    except sqlite3.Error as e:
        logger_db.error(f"Database error updating file path: {e}")
    except Exception as e:
        logger_db.error(f"Unexpected error updating file path: {e}")

def batch_update_file_paths(file_moves):
    _ensure_logger()
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            current_time = time.time()
            cursor.executemany("""
                UPDATE file_metadata
                SET file_path = ?, last_updated = ?
                WHERE file_path = ?
            """, [(new_path, current_time, old_path) for old_path, new_path in file_moves])
            conn.commit()
        logger_db.info(f"Batch updated {len(file_moves)} file paths in the database")
    except sqlite3.Error as e:
        logger_db.error(f"Database error during batch update of file paths: {e}")
    except Exception as e:
        logger_db.error(f"Unexpected error during batch update of file paths: {e}")

def get_metadata(file_path):
    if not file_path:
        raise ValueError("file_path is a required parameter")

    _ensure_logger()
    logger_db.debug(f"Getting metadata for file: {file_path}")

    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT metadata, metadata_after_prompt FROM file_metadata WHERE file_path = ?", (file_path,))
            data = cursor.fetchone()
            if data:
                logger_db.debug(f"Metadata found for {file_path}")
            else:
                logger_db.debug(f"No metadata found for {file_path}")
            return data if data else (None, None)
    except sqlite3.Error as e:
        logger_db.error(f"Database error retrieving metadata for {file_path}: {e}")
        raise
    except Exception as e:
        logger_db.error(f"Unexpected error retrieving metadata for {file_path}: {e}")
        raise

def extract_model_from_metadata(metadata_after_prompt):
    model = None
    for line in metadata_after_prompt.split(','):
        if "Model:" in line or "model:" in line:
            model = line.split(":", 1)[1].strip()
            break

    if model is None:
        try:
            if "Civitai resources:" in metadata_after_prompt:
                json_string_start = metadata_after_prompt.index("Civitai resources:") + len("Civitai resources:")
                json_string = metadata_after_prompt[json_string_start:].strip()
                json_string = json_string.split(']', 1)[0] + ']'
                json_data = json.loads(json_string)
                for item in json_data:
                    if 'modelName' in item:
                        model = item['modelName'].strip()
                        if model:
                            break
        except json.JSONDecodeError as e:
            _ensure_logger()
            logger_db.debug(f"Failed to decode JSON in metadata: {e}")

    return model

def parallel_list_models_in_directory(directory, max_workers: int = None):
    if max_workers is None:
        max_workers = MAX_WORKERS

    _ensure_logger()
    models = {}
    file_paths = []

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(tuple(VALID_EXTENSIONS)):
                file_paths.append(os.path.join(root, file))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(get_model_for_file, file_path) for file_path in file_paths]

        for future in tqdm(as_completed(futures), total=len(futures), desc="Scanning files", unit="file"):
            try:
                file_path, model = future.result()
                if model:
                    if model in models:
                        models[model].append(file_path)
                    else:
                        models[model] = [file_path]
            except Exception as e:
                logger_db.error(f"Error in parallel model listing: {e}")

    return models

def get_model_for_file(file_path):
    _ensure_logger()
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT metadata_after_prompt FROM file_metadata WHERE file_path = ?", (file_path,))
            data = cursor.fetchone()

            if data:
                metadata_after_prompt = data[0]
                model = extract_model_from_metadata(metadata_after_prompt)
                return file_path, model
            else:
                logger_db.debug(f"No metadata found for file: {file_path}")
                return file_path, None
    except sqlite3.Error as e:
        logger_db.error(f"Database error getting model for file {file_path}: {e}")
        return file_path, None
    except Exception as e:
        logger_db.error(f"Unexpected error getting model for file {file_path}: {e}")
        return file_path, None

def update_database_with_folder_contents(source_dir, exiftool_cmd):
    _ensure_logger()
    if isinstance(source_dir, list):
        raise ValueError("update_database_with_folder_contents expects a single directory, not a list")

    current_db_path = get_db_path()
    logger_db.info(f"Updating database at {current_db_path}")
    logger_db.info(f"Updating database with contents of {source_dir}")

    # Check if we can write to the directory
    db_dir = os.path.dirname(current_db_path)
    if not os.access(db_dir, os.W_OK):
        logger_db.error(f"No write permission in directory: {db_dir}")
        raise PermissionError(f"No write permission in directory: {db_dir}")

    try:
        create_table()  # Ensure the table exists

        image_files = []
        resolved_root = os.path.realpath(source_dir)
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if file.lower().endswith(tuple(VALID_EXTENSIONS)):
                    full_path = os.path.join(root, file)
                    if validate_file_path(full_path, resolved_root):
                        image_files.append(full_path)

        logger_db.info(f"Found {len(image_files)} image files to process")

        batch_update_metadata(image_files, exiftool_cmd)

        logger_db.info("Finished updating database")
    except Exception as e:
        logger_db.error(f"Error during database update: {e}")
        raise

# Helper function to check if ExifTool is installed
def check_exiftool():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_exiftool = os.path.join(script_dir, "exiftool.exe" if sys.platform.startswith('win32') else "exiftool")

    if os.path.exists(local_exiftool):
        return local_exiftool, None

    try:
        exiftool_cmd = "exiftool.exe" if sys.platform.startswith('win32') else "exiftool"
        subprocess.run([exiftool_cmd, "-ver"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
        return exiftool_cmd, None
    except FileNotFoundError:
        return None, (
        "ExifTool not found. Please install it or place it in the same directory as this script.\n"
        "https://exiftool.org/install.html\n"
        "Rename it to exiftool.exe for command-line use."
    )
    except subprocess.CalledProcessError:
        return None, "Error occurred while checking ExifTool."

# Main function for testing
def main():
    exiftool_cmd, error = check_exiftool()
    if error:
        print(error)
        return

    source_directory = input("Enter the directory to update the database with: ").strip()
    update_database_with_folder_contents(source_directory, exiftool_cmd)
    print("Database update completed successfully.")

if __name__ == "__main__":
    main()
