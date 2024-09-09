import os
import readline
import atexit

class PathHistory:
    def __init__(self, max_history=10):
        self.history = []
        self.max_history = max_history

    def add(self, path):
        if path in self.history:
            self.history.remove(path)
        self.history.insert(0, path)
        if len(self.history) > self.max_history:
            self.history.pop()

    def get(self):
        return self.history

    def clear(self):
        self.history.clear()

class CommandLineInterface:
    def __init__(self):
        self.path_history = PathHistory()
        self.history_file = os.path.expanduser('~/.exiftool_search_history')
        
        # Set up readline
        readline.set_completer_delims(' \t\n;')
        readline.parse_and_bind("tab: complete")
        
        # Set a reasonable history length
        readline.set_history_length(1000)
        
        # Load history file if it exists
        if os.path.exists(self.history_file):
            readline.read_history_file(self.history_file)
        
        # Save history on exit
        atexit.register(readline.write_history_file, self.history_file)

    def input(self, prompt):
        user_input = input(prompt)
        return user_input

    def prompt_for_directory(self, prompt_message):
        while True:
            directory_input = self.input(prompt_message).strip()
            if directory_input.lower() == 'h':
                return self.show_and_select_history()
            elif directory_input:
                paths = self.process_directory_input(directory_input)
                if paths:
                    return paths
            print("Invalid input. Please enter valid directory path(s) or 'h' for history.")

    def show_and_select_history(self):
        history = self.path_history.get()
        if not history:
            print("History is empty.")
            return None
        
        print("Recent directories:")
        for i, path in enumerate(history, 1):
            print(f"{i}: {path}")
        
        selection = self.input("Enter the number(s) of the directory(ies) you want to use (comma-separated) or 'c' to cancel: ")
        if selection.lower() == 'c':
            return None
        
        try:
            selected_indices = [int(i.strip()) - 1 for i in selection.split(',')]
            selected_paths = [history[i] for i in selected_indices if 0 <= i < len(history)]
            if not selected_paths:
                print("No valid selections made.")
                return None
            return selected_paths
        except ValueError:
            print("Invalid input. Please enter numbers separated by commas.")
            return None

    def process_directory_input(self, input_string):
        paths = []
        for item in input_string.split(','):
            item = item.strip()
            if item.isdigit():
                history = self.path_history.get()
                index = int(item) - 1
                if 0 <= index < len(history):
                    paths.append(history[index])
                else:
                    print(f"Invalid history index: {item}")
                    return None
            elif os.path.isdir(item):
                paths.append(os.path.abspath(item))
                self.path_history.add(os.path.abspath(item))
            else:
                print(f"Invalid directory path: {item}")
                return None
        return paths if paths else None