import os
import subprocess
import sys
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import logging
import sqlite3
from pathlib import Path
import json
import time

# Setup logging
script_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(script_dir, "process_exiftool_search_DB.txt")
logger_db = logging.getLogger('db')
logger_db.setLevel(logging.DEBUG)
file_handler_db = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler_db.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler_db.setFormatter(formatter)
logger_db.addHandler(file_handler_db)

# Constants
VALID_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
BATCH_SIZE = 100  # Adjust as needed
MAX_WORKERS = 24  # Adjust based on your system's capabilities

script_directory = Path(__file__).resolve().parent
db_name = "statistics_image_metadata.db"
db_path = script_directory / db_name
logger_db.info(f"Database path set to: {db_path}")

def db_connection():
    try:
        logger_db.info(f"Attempting to connect to database at: {db_path}")
        
        # Try to create the file if it doesn't exist
        if not os.path.exists(db_path):
            logger_db.info(f"Database file does not exist. Attempting to create it.")
            open(db_path, 'a').close()
        
        conn = sqlite3.connect(db_path)
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
        logger_db.info(f"Table created or already exists in database: {db_path}")
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
        result = subprocess.run([exiftool_cmd, filepath], capture_output=True, text=True, check=True)
        return filepath, result.stdout, None
    except subprocess.CalledProcessError as e:
        return filepath, None, f"Error processing file: {e}"
    except Exception as e:
        return filepath, None, f"Unexpected error: {e}"

def batch_update_metadata(file_list: List[str], exiftool_cmd: str):
    """Updates the database with metadata from the specified image files."""
    create_table()  # Ensure the table exists before updating the database

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_metadata, filepath, exiftool_cmd) for filepath in file_list]
        
        results = []
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing images", unit="file"):
            filepath, metadata, error = future.result()
            if error:
                logger_db.error(f"Error processing file {filepath}: {error}")
            else:
                results.append((Path(filepath).name, filepath, metadata))

            # Batch insert into the database
            if len(results) >= BATCH_SIZE:
                bulk_update_or_insert_metadata(results)
                results.clear()

        # Insert any remaining results
        if results:
            bulk_update_or_insert_metadata(results)

    logger_db.info("Finished adding Metadata from Images to the database.")

def update_file_path(old_path, new_path):
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
            logger_db.debug(f"Failed to decode JSON in metadata: {e}")
    
    return model

def parallel_list_models_in_directory(directory):
    models = {}
    file_paths = []

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith(tuple(VALID_EXTENSIONS)):
                file_paths.append(os.path.join(root, file))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
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
    if isinstance(source_dir, list):
        raise ValueError("update_database_with_folder_contents expects a single directory, not a list")
    
    logger_db.info(f"Updating database at {db_path}")
    logger_db.info(f"Updating database with contents of {source_dir}")
    
    # Check if we can write to the directory
    db_dir = os.path.dirname(db_path)
    if not os.access(db_dir, os.W_OK):
        logger_db.error(f"No write permission in directory: {db_dir}")
        raise PermissionError(f"No write permission in directory: {db_dir}")
    
    try:
        create_table()  # Ensure the table exists
        
        image_files = []
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if file.lower().endswith(tuple(VALID_EXTENSIONS)):
                    image_files.append(os.path.join(root, file))
        
        logger_db.info(f"Found {len(image_files)} image files to process")
        
        batch_update_metadata(image_files, exiftool_cmd)
        
        logger_db.info("Finished updating database")
    except Exception as e:
        logger_db.error(f"Error during database update: {e}")
        raise

# Helper function to check if ExifTool is installed
def check_exiftool():
    try:
        exiftool_cmd = "exiftool.exe" if sys.platform.startswith('win32') else "exiftool"
        subprocess.run([exiftool_cmd, "-ver"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return exiftool_cmd, None
    except FileNotFoundError:
        return None, "ExifTool not found. Please install it to use this script. https://exiftool.org/install.html"
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
