# ExifTool Search and Move 

This tool is designed to find images by their prompts in their embedded metadata across multiple directories and move them to a target directory. It also maintains a database of image metadata for faster searching and can analyze AI model usage across image collections.

## Key Features

- Multi-directory search and moving of image files based on specific metadata criteria
- Automatically updates file paths in the database when images are moved, ensuring the database always reflects the current locations of images
- Update and maintain a SQLite database of image metadata for searching
- Analyze and list models used in AI-generated images across directories
- Efficient metadata extraction using ExifTool
- Parallel processing for improved performance with large datasets
- User-friendly command-line interface with history functionality
- Batch processing capabilities for handling multiple files and directories


## Project Structure

The project consists of four core scripts with the main.py to start:


1. `main.py`: 
   - Central entry point 
   - Coordinates execution of sub-scripts and functions
   
2. `exiftool_search.py`: 
   - Handles the search and move functionality
   - Interacts with the user to get search criteria and directories

3. `exiftool_search_DB.py`:
   - Manages the SQLite database operations
   - Handles metadata extraction and storage

4. `exiftool_Search_Model.py`:
   - Analyzes directories to list models used in AI-generated images

5. `utilities.py`:
   - Provides CLI utilities and input handling   


### Prerequisites

Python 3.x <br>
ExifTool by Phil Harvey (https://exiftool.org/install.html)<br>
Ensure ExifTool is in your PATH and accessible from the command line

### Installation

1. Install required Python packages:
   ```
   pip install -r requirements.txt
   ```

## Configuration

You can adjust the following settings in the scripts:

- `BATCH_SIZE`: Number of images to process in each batch (default: 100)
- `MAX_WORKERS`: Number of worker threads for parallel processing (default: 24)
   
Adjust these based on your system's capabilities and requirements.<br>
On a 12 Core 24 Thread CPU + SSD + 32GB 25k Images in 01:38 min data extracted and written to the Database


## How to Use

1. Run the main script:
   ```
   python main.py
   ```

2. Follow the prompts to:<br>
   ```
   Exiftool Search and Analysis Tool
    1. Search and Move Images
    2. Update Database
    3. Search for Models
    4. Exit
   Enter your choice (1-4):
   ```


## Example Usage

1. Searching for images:
   - Select option 1 
   - Enter Source Directory(ies) (comma-separated or 'h' for history)
   - Add more directories? (y/n) 
   - Specify the target directory
   - Enter the metadata key to search for (or press enter for default 'parameters')
   - Enter the metadata value to search for
   - Search only in prompt (1) or in entire parameters (2)? Enter 1 or 2
   - Enter batch size for processing (default is 100)

2. Updating the database:
   - Select option 2 
   - Enter Source Directory(ies) (comma-separated) to update the database

3. Analyzing model usage:
   - Select option 3 
   - Enter the directory path to search for Images with model information
   - View the results in the generated text file
  
``` 
Model information for Image files:

Model: Model Name
Files: 2
 - /user/SSD/stable-diffusion-webui/outputs/txt2img-images/2024-07-24/00032-3447480767.png
 - /user/SSD/stable-diffusion-webui/outputs/txt2img-images/2024-07-24/00074-3212151072.png

Model: Model Name
Files: 3
 - /user/SSD/stable-diffusion-webui/outputs/txt2img-images/2024-07-24/00000-80320310.png
 - /user/SSD/stable-diffusion-webui/outputs/txt2img-images/2024-07-24/00003-80320313.png
 - /user/SSD/stable-diffusion-webui/outputs/txt2img-images/2024-07-24/00002-80320312.png
```


### Acknowledgements
  Thanks to Phil Harvey for his awesome exif data tool https://exiftool.org



## Updates

1.Windows compatibility update
- Added a requirement pyreadline3; sys_platform == 'win32' for windows compatibility

2.Qualitiy of Life update
- Added support for using the ExifTool executable when placed in the same directory as the script. The script now checks if it is in the same folder or accessible system-wide.
- Increased flexibility for users who prefer not to install ExifTool system-wide.


