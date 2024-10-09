import exiftool_search_DB as db_module
import os
from datetime import datetime
import logging
from utilities import CommandLineInterface
from tqdm import tqdm



# Configure logger
script_directory = os.path.dirname(os.path.abspath(__file__))
logger_model = logging.getLogger('model')
logger_model.setLevel(logging.DEBUG)
log_file_path = os.path.join(script_directory, "process_log_search_model.txt")
file_handler_model = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler_model.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler_model.setFormatter(formatter)
logger_model.addHandler(file_handler_model)


def main():
    cli = CommandLineInterface()
    directory = cli.prompt_for_directory("Enter the directory path to search for Images with model information: ")
    
    if not directory:
        print("Invalid input. Please enter a directory path.")
        return
    
    # Since prompt_for_directory now returns a list, we'll take the first item
    directory = directory[0]
    
    directory_name = os.path.basename(os.path.normpath(directory))
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"{timestamp}.{directory_name}.txt"
    filename = os.path.join(script_directory, filename)
    
    db_module.create_table()
    
    print("Searching for models...")
    models = db_module.parallel_list_models_in_directory(directory)
    
    total_files = sum(len(files) for files in models.values())
    print(f"Found {len(models)} unique models across {total_files} files.")
    
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            if models:
                f.write("Model information for Image files:\n")
                for model, files in tqdm(models.items(), desc="Writing results", unit="model"):
                    f.write(f"\nModel: {model}\n")
                    f.write(f"Files: {len(files)}\n")
                    for file in files:
                        f.write(f" - {file}\n")
            else:
                f.write("No Image files with model information found in the specified directory.\n")
    except Exception as e:
        print(f"Error saving results to {filename}: {str(e)}")
    
    print(f"Results saved to {filename}")

if __name__ == "__main__":
    main()
