import os
import shutil
import exiftool_search_DB as db_module
from tqdm import tqdm
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from utilities import CommandLineInterface

# Configure logger
script_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(script_dir, "process_log_exiftool_search.txt")
logger_search = logging.getLogger('search')
logger_search.setLevel(logging.DEBUG)
file_handler_search = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler_search.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler_search.setFormatter(formatter)
logger_search.addHandler(file_handler_search)

def process_file(args):
    file_path, target_dir, metadata_key, metadata_value, search_mode, exiftool_cmd = args
    logger_search.debug(f"Processing file: {file_path}")
    
    try:
        metadata, metadata_after_prompt = db_module.get_metadata(file_path)
        if metadata and metadata_after_prompt:
            metadata_to_search = metadata if search_mode == "1" else metadata + " " + metadata_after_prompt
            
            if metadata_key in metadata_to_search and metadata_value in metadata_to_search:
                new_file_path = os.path.join(target_dir, os.path.basename(file_path))
                try:
                    shutil.move(file_path, new_file_path)
                    db_module.update_file_path(file_path, new_file_path)
                    logger_search.debug(f"File moved and database updated: {new_file_path}")
                    return True, file_path, new_file_path
                except Exception as e:
                    logger_search.error(f"Error moving file {file_path} to {new_file_path}: {e}")
        else:
            logger_search.debug(f"No metadata found for file: {file_path}")
    except Exception as e:
        logger_search.error(f"Error processing file {file_path}: {e}")
    
    return False, file_path, None

def find_and_move_images(source_dirs, target_dir, metadata_key, metadata_value, search_mode, exiftool_cmd, batch_size=100):
    if not source_dirs or not target_dir:
        raise ValueError("source_dirs and target_dir cannot be None")

    all_files = []
    for source_dir in source_dirs:
        for root, _, files in os.walk(source_dir):
            all_files.extend([os.path.join(root, f) for f in files if f.lower().endswith(('.png', '.jpeg', '.jpg'))])

    total_files = len(all_files)
    moved_files = 0
    file_moves = []

    logger_search.info(f"Total files to process: {total_files}")
    logger_search.info(f"Processing in batches of {batch_size}")
    logger_search.info(f"Searching for metadata key: {metadata_key}")
    logger_search.info(f"Searching for metadata value: {metadata_value}")
    logger_search.info(f"Search mode: {search_mode}")

    with tqdm(total=total_files, desc="Searching and Moving Files", unit="file") as pbar:
        for i in range(0, total_files, batch_size):
            batch = all_files[i:i+batch_size]
            
            with ProcessPoolExecutor() as executor:
                futures = [executor.submit(process_file, (file_path, target_dir, metadata_key, metadata_value, search_mode, exiftool_cmd)) 
                           for file_path in batch]
                
                for future in as_completed(futures):
                    result, old_path, new_path = future.result()
                    if result:
                        moved_files += 1
                        if new_path:
                            file_moves.append((old_path, new_path))
                    pbar.update(1)

            # Perform batch update after processing each batch
            if file_moves:
                try:
                    db_module.batch_update_file_paths(file_moves)
                    file_moves.clear()
                except Exception as e:
                    logger_search.error(f"Error in batch updating file paths: {e}")

    logger_search.info(f"Search complete. Processed {total_files} files.")
    logger_search.info(f"Moved {moved_files} files to {target_dir}")
    print(f"Search complete. Processed {total_files} files.")
    print(f"Moved {moved_files} files to {target_dir}")

def search_and_move_images(cli: CommandLineInterface):
    source_directories = []
    while True:
        input_dirs = cli.prompt_for_directory("Enter Source Directory(ies) (comma-separated or 'h' for history): ")
        
        if input_dirs is None:
            continue
        
        source_directories.extend(input_dirs)
        
        print("Current source directories:")
        for dir_path in source_directories:
            print(f" - {dir_path}")
        
        if cli.input("Add more directories? (y/n): ").lower() != 'y':
            break

    if not source_directories:
        print("No valid source directories specified. Exiting search.")
        return

    target_directory = cli.prompt_for_directory("Enter Target Directory: ")
    if not target_directory:
        print("No valid target directory specified. Exiting search.")
        return
    target_directory = target_directory[0]  # Since prompt_for_directory now returns a list

    metadata_key = cli.input("Enter the metadata key to search for (or press enter for default 'parameters'): ").strip() or "parameters"
    metadata_value = cli.input("Enter the metadata value to search for: ").strip()

    search_mode = cli.input("Search only in prompt (1) or in entire parameters (2)? Enter 1 or 2: ").strip()
    while search_mode not in ['1', '2']:
        print("Invalid input. Please enter 1 or 2.")
        search_mode = cli.input("Search only in prompt (1) or in entire parameters (2)? Enter 1 or 2: ").strip()

    batch_size = cli.input("Enter batch size for processing (default is 100): ").strip()
    batch_size = int(batch_size) if batch_size.isdigit() else 100

    exiftool_cmd, error = db_module.check_exiftool()
    if error:
        print(error)
        return

    find_and_move_images(source_directories, target_directory, metadata_key.lower(), metadata_value, search_mode, exiftool_cmd, batch_size)

def update_database(cli: CommandLineInterface):
    source_directories = cli.prompt_for_directory("Enter Source Directory(ies) (comma-separated) to update the database: ")
    if not source_directories:
        print("No valid source directories specified. Exiting update.")
        return

    exiftool_cmd, error = db_module.check_exiftool()
    if error:
        print(error)
        return

    for source_directory in source_directories:
        print(f"Updating database for directory: {source_directory}")
        db_module.update_database_with_folder_contents(source_directory, exiftool_cmd)
    
    print("Database update completed successfully.")

# This function is no longer needed as a separate menu, but kept for compatibility
def main():
    cli = CommandLineInterface()
    search_and_move_images(cli)

if __name__ == "__main__":
    main()
