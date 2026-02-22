import os
import sys
import platform
import configparser
import logging
import readline
import atexit
from pathlib import Path

logger_security = logging.getLogger('security')

# Script directory for locating config
_script_dir = Path(__file__).resolve().parent


def _load_security_config():
    """Load security settings from config.ini."""
    config = configparser.ConfigParser()
    config_path = _script_dir / "config.ini"
    if config_path.exists():
        config.read(config_path)

    enable_blocklist = config.getboolean('security', 'enable_blocklist', fallback=True)
    custom_str = config.get('security', 'custom_blocked_paths', fallback='')
    custom_blocked = [p.strip() for p in custom_str.split(',') if p.strip()]

    return {
        'enable_blocklist': enable_blocklist,
        'custom_blocked_paths': custom_blocked,
    }


def get_blocked_paths():
    """Return platform-specific list of dangerous system paths."""
    security_config = _load_security_config()

    if not security_config['enable_blocklist']:
        return []

    blocked = []

    if sys.platform.startswith('win'):
        win_root = os.environ.get('SystemRoot', r'C:\Windows')
        blocked = [
            win_root,
            os.path.join(win_root, 'System32'),
            os.path.join(win_root, 'SysWOW64'),
            r'C:\Program Files',
            r'C:\Program Files (x86)',
            os.environ.get('ProgramData', r'C:\ProgramData'),
        ]
    else:
        blocked = [
            '/bin', '/sbin', '/usr/bin', '/usr/sbin',
            '/boot', '/dev', '/proc', '/sys',
            '/etc', '/lib', '/lib64',
            '/usr/lib', '/usr/lib64',
            '/var/run', '/var/lock',
            '/root',
        ]

    blocked.extend(security_config['custom_blocked_paths'])
    return [os.path.realpath(p) for p in blocked]


def is_blocked_path(path):
    """Check if the given path falls within any blocked system directory."""
    resolved = os.path.realpath(path)
    for blocked in get_blocked_paths():
        # Exact match or child of blocked path
        if resolved == blocked or resolved.startswith(blocked + os.sep):
            logger_security.warning(
                f"BLOCKED: Path '{path}' resolves to blocked area '{blocked}'"
            )
            return True
    return False


def is_network_path(path):
    """Detect UNC paths (Windows) and common network mount indicators."""
    path_str = str(path)
    # UNC paths: \\server\share or //server/share
    if path_str.startswith('\\\\') or path_str.startswith('//'):
        return True
    # Common network filesystem mount points
    network_prefixes = ['/mnt/nfs', '/net/', '/smb/']
    for prefix in network_prefixes:
        if path_str.startswith(prefix):
            return True
    return False


def validate_file_path(file_path, allowed_root):
    """Whitelist validation: ensure resolved file_path is under allowed_root.

    Returns True if the file is safe to process, False otherwise.
    """
    try:
        resolved_file = os.path.realpath(file_path)
        resolved_root = os.path.realpath(allowed_root)

        # File must be under the allowed root directory
        if not resolved_file.startswith(resolved_root + os.sep) and resolved_file != resolved_root:
            logger_security.warning(
                f"SKIPPED: File '{file_path}' resolves outside allowed root '{allowed_root}'"
            )
            return False
        return True
    except (OSError, ValueError) as e:
        logger_security.warning(f"SKIPPED: Could not validate '{file_path}': {e}")
        return False


def validate_directory(path):
    """7-step defense-in-depth directory validation.

    Returns (is_valid, error_message) tuple.
    """
    # Step 1: Resolve to real path (follow symlinks)
    try:
        resolved = os.path.realpath(path)
    except (OSError, ValueError) as e:
        return False, f"Cannot resolve path: {e}"

    # Step 2: Blocklist check
    if is_blocked_path(resolved):
        return False, f"Path is in a blocked system directory: {resolved}"

    # Step 3: Existence check
    if not os.path.exists(resolved):
        return False, f"Path does not exist: {resolved}"

    # Step 4: Directory check
    if not os.path.isdir(resolved):
        return False, f"Path is not a directory: {resolved}"

    # Step 5: Permission check (read + execute for traversal)
    if not os.access(resolved, os.R_OK | os.X_OK):
        return False, f"Insufficient permissions for directory: {resolved}"

    # Step 6: Network path check
    if is_network_path(resolved):
        return False, f"Network paths are not allowed: {resolved}"

    # Step 7: Symlink escape check -- ensure the resolved path isn't
    # wildly different from the input (logged as warning, not blocked,
    # since realpath already resolved it for the blocklist check)
    if os.path.islink(path) and resolved != os.path.abspath(path):
        logger_security.info(
            f"Symlink detected: '{path}' -> '{resolved}' (allowed after validation)"
        )

    return True, None

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
            else:
                is_valid, error_msg = validate_directory(item)
                if is_valid:
                    resolved = os.path.realpath(item)
                    paths.append(resolved)
                    self.path_history.add(resolved)
                else:
                    print(f"Directory rejected: {item} -- {error_msg}")
                    return None
        return paths if paths else None
