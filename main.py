import exiftool_search
import exiftool_search_model
from utilities import CommandLineInterface


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
            exiftool_search_model.main()
        elif choice == '4':
            print("Exiting the program. Goodbye!")
            break
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()
