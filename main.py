import exiftool_search
import exiftool_Search_Model
from utilities import CommandLineInterface
import logging
import os
import exiftool_search_DB as db_module


def display_menu():
    print("\nExiftool Search and Analysis Tool")
    print(" 1. Search and Move Images")
    print(" 2. Update Database")
    print(" 3. Search for Models")
    print(" 4. Exit")

def main():
    cli = CommandLineInterface()

    while True:
        display_menu()
        choice = cli.input("Enter your choice (1-4): ")

        if choice == '1':
            exiftool_search.search_and_move_images(cli)
        elif choice == '2':
            exiftool_search.update_database(cli)
        elif choice == '3':
            exiftool_Search_Model.main()
        elif choice == '4':
            print("Exiting the program. Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")


def update_database(cli: CommandLineInterface):
    source_directory = cli.prompt_for_directory("Enter Source Directory to update the database: ")
    exiftool_cmd, error = db_module.check_exiftool()
    if error:
        print(error)
        return

    db_module.update_database_with_folder_contents(source_directory, exiftool_cmd)
    
    if os.path.exists(db_module.db_path):
        print(f"Database updated successfully. File located at: {db_module.db_path}")
    else:
        print(f"Warning: Database file not found at expected location: {db_module.db_path}")
    
    print("Database update completed.")

if __name__ == "__main__":
    main()
