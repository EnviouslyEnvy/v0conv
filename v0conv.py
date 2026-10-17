import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import subprocess
from PIL import Image
import shutil
import glob
import io
import re
import queue
import concurrent.futures
import multiprocessing
from datetime import datetime
import mutagen
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TPE1, TIT2, TALB, TRCK, TDRC
import json
import phone_transfer

class MusicConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("Lossless to MP3 V0 Converter")
        self.root.geometry("1000x940")
        self.root.resizable(True, True)
        
        self.source_base_folder = ""
        self.source_subfolder = ""
        self.target_base_folder = ""
        self.conversion_in_progress = False
        self.scan_in_progress = False
        self.queue_conversion_active = False
        self.recent_by_id = {}
        self.conversion_queue = []
        self.queued_paths = set()
        self.queue_by_id = {}
        self.transfer_in_progress = False
        self.transfer_process = None
        self.phone_destinations = []
        self.phone_subfolder = "Music"
        self.phone_device_id = ""
        self.pending_phone_jobs = []
        self.last_converted_outputs = []
        self.device_scan_in_progress = False
        
        # Config file for remembering directories
        self.config_file = os.path.join(os.path.expanduser("~"), ".v0conv_config.json")
        
        # Load saved directories
        self.load_directory_config()
        
        self.create_widgets()
        
    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Source base folder selection (for reference only)
        ttk.Label(main_frame, text="Source Base (e.g., V:/Music/):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.source_base_entry = ttk.Entry(main_frame, width=50)
        self.source_base_entry.grid(row=0, column=1, sticky=tk.W+tk.E, pady=5, padx=5)
        self.source_base_entry.insert(0, self.source_base_folder)  # Load saved value
        ttk.Button(main_frame, text="Browse...", command=self.select_source_base).grid(row=0, column=2, pady=5)
        
        # Source specific subfolder selection
        ttk.Label(main_frame, text="Source Subfolder to Convert:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.source_subfolder_entry = ttk.Entry(main_frame, width=50)
        self.source_subfolder_entry.grid(row=1, column=1, sticky=tk.W+tk.E, pady=5, padx=5)
        self.source_subfolder_entry.insert(0, self.source_subfolder)  # Load saved value
        ttk.Button(main_frame, text="Browse...", command=self.select_source_subfolder).grid(row=1, column=2, pady=5)
        
        # Batch mode checkbox - add after source subfolder entry
        self.batch_mode_var = tk.BooleanVar(value=False)
        self.batch_mode_checkbox = ttk.Checkbutton(
            main_frame, 
            text="Batch Mode: Convert all subdirectories in subfolder", 
            variable=self.batch_mode_var
        )
        self.batch_mode_checkbox.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        # Add parallel processing controls
        parallelize_frame = ttk.Frame(main_frame)
        parallelize_frame.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        self.parallelize_var = tk.BooleanVar(value=True)
        self.parallelize_checkbox = ttk.Checkbutton(
            parallelize_frame, 
            text="Enable parallel processing", 
            variable=self.parallelize_var
        )
        self.parallelize_checkbox.pack(side=tk.LEFT)
        
        ttk.Label(parallelize_frame, text="Number of threads:").pack(side=tk.LEFT, padx=(20, 5))
        
        # Default to CPU core count - 1 (keep one core free for OS), capped at 8
        MAX_THREADS = 8
        default_threads = min(MAX_THREADS, max(1, multiprocessing.cpu_count() - 1))
        self.threads_var = tk.StringVar(value=str(default_threads))
        threads_spinbox = ttk.Spinbox(
            parallelize_frame,
            from_=1,
            to=MAX_THREADS,
            textvariable=self.threads_var,
            width=3
        )
        threads_spinbox.pack(side=tk.LEFT)
        
        # Target base folder selection - move to row 4
        ttk.Label(main_frame, text="Target Base Folder (e.g., V:/Lossy Music/):").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.target_entry = ttk.Entry(main_frame, width=50)
        self.target_entry.grid(row=4, column=1, sticky=tk.W+tk.E, pady=5, padx=5)
        self.target_entry.insert(0, self.target_base_folder)  # Load saved value
        ttk.Button(main_frame, text="Browse...", command=self.select_target_folder).grid(row=4, column=2, pady=5)

        # Recently edited source folders that are not already in the target tree
        recent_frame = ttk.LabelFrame(main_frame, text="Recently edited folders missing from target")
        recent_frame.grid(row=5, column=0, columnspan=3, sticky=tk.W+tk.E+tk.N+tk.S, pady=5)
        main_frame.rowconfigure(5, weight=2)

        recent_toolbar = ttk.Frame(recent_frame)
        recent_toolbar.pack(fill=tk.X, padx=5, pady=5)

        self.scan_button = ttk.Button(recent_toolbar, text="Scan folders", command=self.scan_recent_folders)
        self.scan_button.pack(side=tk.LEFT, padx=(0, 5))

        ttk.Label(recent_toolbar, text="Show newest:").pack(side=tk.LEFT)
        self.recent_limit_var = tk.StringVar(value="100")
        ttk.Spinbox(
            recent_toolbar,
            from_=10,
            to=2000,
            increment=10,
            textvariable=self.recent_limit_var,
            width=6
        ).pack(side=tk.LEFT, padx=5)

        ttk.Button(recent_toolbar, text="Select all", command=self.select_all_recent).pack(side=tk.LEFT, padx=5)
        self.queue_selected_button = ttk.Button(
            recent_toolbar,
            text="Queue selected",
            command=self.queue_selected_folders
        )
        self.queue_selected_button.pack(side=tk.LEFT, padx=5)

        self.recent_count_var = tk.StringVar(value="Not scanned")
        ttk.Label(recent_toolbar, textvariable=self.recent_count_var).pack(side=tk.RIGHT)

        recent_list_frame = ttk.Frame(recent_frame)
        recent_list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.recent_tree = ttk.Treeview(
            recent_list_frame,
            columns=('edited', 'folder'),
            show='headings',
            selectmode='extended',
            height=6
        )
        self.recent_tree.heading('edited', text='Edited')
        self.recent_tree.heading('folder', text='Folder (relative to source base)')
        self.recent_tree.column('edited', width=140, stretch=False)
        self.recent_tree.column('folder', width=640, stretch=True)
        recent_scroll = ttk.Scrollbar(recent_list_frame, orient=tk.VERTICAL, command=self.recent_tree.yview)
        self.recent_tree.configure(yscrollcommand=recent_scroll.set)
        self.recent_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        recent_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        queue_frame = ttk.LabelFrame(main_frame, text="Conversion queue (one folder at a time)")
        queue_frame.grid(row=6, column=0, columnspan=3, sticky=tk.W+tk.E+tk.N+tk.S, pady=5)
        main_frame.rowconfigure(6, weight=1)

        queue_toolbar = ttk.Frame(queue_frame)
        queue_toolbar.pack(fill=tk.X, padx=5, pady=5)

        self.convert_queue_button = ttk.Button(
            queue_toolbar,
            text="Convert queue",
            command=self.start_queue_conversion
        )
        self.convert_queue_button.pack(side=tk.LEFT, padx=(0, 5))
        self.remove_queue_button = ttk.Button(queue_toolbar, text="Remove selected", command=self.remove_selected_from_queue)
        self.remove_queue_button.pack(side=tk.LEFT, padx=5)
        self.clear_queue_button = ttk.Button(queue_toolbar, text="Clear queue", command=self.clear_queue)
        self.clear_queue_button.pack(side=tk.LEFT, padx=5)

        self.queue_count_var = tk.StringVar(value="Queue empty")
        ttk.Label(queue_toolbar, textvariable=self.queue_count_var).pack(side=tk.RIGHT)

        queue_list_frame = ttk.Frame(queue_frame)
        queue_list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        self.queue_tree = ttk.Treeview(
            queue_list_frame,
            columns=('edited', 'folder'),
            show='headings',
            selectmode='extended',
            height=4
        )
        self.queue_tree.heading('edited', text='Edited')
        self.queue_tree.heading('folder', text='Queued folder')
        self.queue_tree.column('edited', width=140, stretch=False)
        self.queue_tree.column('folder', width=640, stretch=True)
        queue_scroll = ttk.Scrollbar(queue_list_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=queue_scroll.set)
        self.queue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        queue_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        phone_frame = ttk.LabelFrame(main_frame, text="Send converted folders to a USB phone")
        phone_frame.grid(row=7, column=0, columnspan=3, sticky=tk.W+tk.E, pady=5)

        phone_row = ttk.Frame(phone_frame)
        phone_row.pack(fill=tk.X, padx=5, pady=(5, 2))

        self.refresh_devices_button = ttk.Button(phone_row, text="Refresh devices", command=self.refresh_phone_devices)
        self.refresh_devices_button.pack(side=tk.LEFT)

        self.phone_device_combo = ttk.Combobox(phone_row, state='readonly', width=52)
        self.phone_device_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.phone_device_combo.bind('<<ComboboxSelected>>', self._on_phone_device_selected)
        self.phone_device_combo.set('Looking for a phone...')

        self.browse_phone_button = ttk.Button(phone_row, text="Browse...", command=self.browse_phone_folder)
        self.browse_phone_button.pack(side=tk.LEFT)

        phone_actions = ttk.Frame(phone_frame)
        phone_actions.pack(fill=tk.X, padx=5, pady=(2, 5))

        ttk.Label(phone_actions, text="Folder on phone:").pack(side=tk.LEFT)
        self.phone_subfolder_entry = ttk.Entry(phone_actions, width=16)
        self.phone_subfolder_entry.pack(side=tk.LEFT, padx=5)
        self.phone_subfolder_entry.insert(0, self.phone_subfolder or "Music")

        self.send_queue_button = ttk.Button(phone_actions, text="Send queue to phone", command=self.send_queue_to_phone)
        self.send_queue_button.pack(side=tk.LEFT, padx=5)
        self.send_last_button = ttk.Button(
            phone_actions,
            text="Send last converted",
            command=self.send_last_converted_to_phone,
            state=tk.DISABLED
        )
        self.send_last_button.pack(side=tk.LEFT, padx=5)
        ttk.Label(
            phone_frame,
            text="Or copy one converted folder at a time and paste it where you want it."
        ).pack(anchor=tk.W, padx=8, pady=(2, 2))

        latest_actions = ttk.Frame(phone_frame)
        latest_actions.pack(fill=tk.X, padx=5, pady=(0, 2))
        self.open_latest_button = ttk.Button(
            latest_actions,
            text="Open folder",
            command=self.open_latest_folder,
            state=tk.DISABLED
        )
        self.open_latest_button.pack(side=tk.LEFT)
        self.copy_latest_button = ttk.Button(
            latest_actions,
            text="Copy this folder",
            command=self.copy_latest_folder,
            state=tk.DISABLED
        )
        self.copy_latest_button.pack(side=tk.LEFT, padx=5)
        ttk.Label(latest_actions, text="One folder per copy, so each paste can go somewhere else.").pack(side=tk.LEFT)

        latest_list = ttk.Frame(phone_frame)
        latest_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        self.latest_tree = ttk.Treeview(
            latest_list,
            columns=('folder',),
            show='headings',
            selectmode='browse',
            height=4
        )
        self.latest_tree.heading('folder', text='Latest converted folder')
        self.latest_tree.column('folder', width=760, stretch=True)
        latest_scroll = ttk.Scrollbar(latest_list, orient=tk.VERTICAL, command=self.latest_tree.yview)
        self.latest_tree.configure(yscrollcommand=latest_scroll.set)
        self.latest_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        latest_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.latest_tree.bind('<Double-1>', self._open_latest_from_double_click)
        self.latest_by_id = {}
        
        # Structure explanation
        explanation_frame = ttk.LabelFrame(main_frame, text="Directory Structure Example")
        explanation_frame.grid(row=8, column=0, columnspan=3, sticky=tk.W+tk.E, pady=10)
        example_text = (
            "If source base is V:/Music/, selected subfolder is V:/Music/Artist/Album1/\n"
            "and target base is V:/Lossy Music/, then output will be V:/Lossy Music/Artist/Album1/"
        )
        ttk.Label(explanation_frame, text=example_text, justify=tk.LEFT).pack(padx=10, pady=5, anchor=tk.W)
        
        # Progress bar and status
        ttk.Label(main_frame, text="Progress:").grid(row=9, column=0, sticky=tk.W, pady=5)
        self.progress = ttk.Progressbar(main_frame, length=400, mode="determinate")
        self.progress.grid(row=9, column=1, sticky=tk.W+tk.E, pady=5, padx=5)
        
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        ttk.Label(main_frame, textvariable=self.status_var).grid(row=10, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        # Current file label
        self.current_file_var = tk.StringVar()
        self.current_file_var.set("")
        ttk.Label(main_frame, textvariable=self.current_file_var, wraplength=900).grid(row=11, column=0, columnspan=3, sticky=tk.W, pady=5)
        
        # Log frame with scrollbar
        log_frame = ttk.LabelFrame(main_frame, text="Conversion Log")
        log_frame.grid(row=12, column=0, columnspan=3, sticky=tk.W+tk.E+tk.N+tk.S, pady=10)
        main_frame.rowconfigure(12, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Scrollbar and Text widget for logs
        scrollbar = ttk.Scrollbar(log_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(log_frame, height=6, width=70, yscrollcommand=scrollbar.set)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        scrollbar.config(command=self.log_text.yview)
        
        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=13, column=0, columnspan=3, pady=10)
        
        self.convert_button = ttk.Button(button_frame, text="Start Conversion", command=self.start_conversion)
        self.convert_button.pack(side=tk.LEFT, padx=5)
        
        self.cancel_button = ttk.Button(button_frame, text="Cancel", command=self.cancel_conversion, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(button_frame, text="Exit", command=self.root.quit).pack(side=tk.LEFT, padx=5)
        self.root.after(400, self.refresh_phone_devices)
        
    def sanitize_path(self, path):
        """Sanitize path by removing quotes and normalizing path separators"""
        if not path:
            return ""
        
        # Remove quotes at the beginning and end
        path = path.strip('"\'')
        
        # Normalize path separators for the current OS
        path = os.path.normpath(path)
        
        return path
    
    def select_source_base(self):
        # Use current value as initial directory if it exists
        initial_dir = self.source_base_folder if self.source_base_folder and os.path.exists(self.source_base_folder) else None
        
        folder = filedialog.askdirectory(
            title="Select Source Base Music Folder",
            initialdir=initial_dir
        )
        if folder:
            folder = self.sanitize_path(folder)
            self.source_base_folder = folder
            self.source_base_entry.delete(0, tk.END)
            self.source_base_entry.insert(0, folder)
            self.log("Source base folder set to: " + folder)
            self.save_directory_config()  # Save the selection
            
    def select_source_subfolder(self):
        # Use current subfolder or base folder as initial directory
        initial_dir = None
        if self.source_subfolder and os.path.exists(self.source_subfolder):
            initial_dir = self.source_subfolder
        elif self.source_base_folder and os.path.exists(self.source_base_folder):
            initial_dir = self.source_base_folder
            
        folder = filedialog.askdirectory(
            title="Select Specific Source Subfolder to Convert",
            initialdir=initial_dir
        )
        if folder:
            folder = self.sanitize_path(folder)
            self.source_subfolder = folder
            self.source_subfolder_entry.delete(0, tk.END)
            self.source_subfolder_entry.insert(0, folder)
            
            # Try to auto-detect the base folder
            if not self.source_base_folder:
                # Try to guess the base folder
                path_parts = os.path.normpath(folder).split(os.sep)
                
                if 'music' in [p.lower() for p in path_parts]:
                    # Try to use the 'Music' folder as base
                    music_idx = [p.lower() for p in path_parts].index('music')
                    base_path = os.path.join(*path_parts[:music_idx+1])
                    if os.path.sep == '\\':  # Windows
                        if path_parts[0]:  # Has drive letter
                            base_path = path_parts[0] + os.path.sep + base_path
                        else:
                            base_path = os.path.sep + base_path
                    else:  # Unix-like
                        base_path = os.path.sep + base_path
                    
                    self.source_base_folder = base_path
                    self.source_base_entry.delete(0, tk.END)
                    self.source_base_entry.insert(0, base_path)
                    self.log(f"Auto-detected source base folder: {base_path}")
            
            self.log("Source subfolder set to: " + folder)
            self.save_directory_config()  # Save the selection
            
    def is_subpath(self, potential_subpath, parent_path):
        """
        Check if one path is a subpath of another, handling special characters and normalization.
        Returns True if potential_subpath is inside parent_path.
        """
        # Normalize both paths to absolute paths with consistent separators
        norm_parent = os.path.normpath(os.path.abspath(parent_path))
        norm_sub = os.path.normpath(os.path.abspath(potential_subpath))
        
        # Check if the normalized subpath starts with the normalized parent path
        # Add path separator to ensure we're matching complete path components
        if not norm_parent.endswith(os.sep):
            norm_parent += os.sep
            
        return norm_sub.startswith(norm_parent)
            
    def select_target_folder(self):
        # Use current value as initial directory if it exists
        initial_dir = self.target_base_folder if self.target_base_folder and os.path.exists(self.target_base_folder) else None
        
        folder = filedialog.askdirectory(
            title="Select Target Base MP3 Folder",
            initialdir=initial_dir
        )
        if folder:
            folder = self.sanitize_path(folder)
            self.target_base_folder = folder
            self.target_entry.delete(0, tk.END)
            self.target_entry.insert(0, folder)
            self.log("Target base folder set to: " + folder)
            self.save_directory_config()  # Save the selection

    def _set_conversion_busy(self, busy):
        state = tk.DISABLED if busy else tk.NORMAL
        self.convert_button.config(state=state)
        self.scan_button.config(state=state)
        self.queue_selected_button.config(state=state)
        self.convert_queue_button.config(state=state)
        self.remove_queue_button.config(state=state)
        self.clear_queue_button.config(state=state)
        self.refresh_devices_button.config(state=state)
        self.browse_phone_button.config(state=state)
        self.send_queue_button.config(state=state)
        self.send_last_button.config(state=state)
        self.open_latest_button.config(state=state)
        self.copy_latest_button.config(state=state)
        self.phone_device_combo.config(state='disabled' if busy else 'readonly')
        self.cancel_button.config(state=tk.NORMAL if busy else tk.DISABLED)
        if not busy:
            self._update_send_last_button()

    def _audio_extensions(self):
        return {
            '.flac', '.wav', '.aiff', '.aif', '.ape', '.alac',
            '.mp3', '.m4a', '.ogg', '.opus', '.aac', '.wma', '.mp4'
        }

    def _directory_has_audio(self, filenames):
        audio_extensions = self._audio_extensions()
        for name in filenames:
            if os.path.splitext(name)[1].lower() in audio_extensions:
                return True
        return False

    def _transform_flac_path(self, rel_path):
        """Apply the same FLAC -> MP3V0 directory rename used when writing output."""
        parts = rel_path.split(os.sep)
        renamed = [
            re.sub(r'\bflac\b', 'MP3V0', part, flags=re.IGNORECASE)
            for part in parts
        ]
        return os.sep.join(renamed)

    def _index_directories(self, base_dir, music_folders_only, status_label):
        """
        Walk base_dir.
        When music_folders_only is True, return music folders with edited dates.
        Otherwise return a set of every relative directory path under the base.
        """
        indexed_paths = set()
        music_folders = []
        seen = 0

        def on_walk_error(err):
            message = f"Skipped unreadable directory: {getattr(err, 'filename', err)}"
            self.root.after(0, lambda msg=message: self.log(msg))

        for current_dir, _dirs, filenames in os.walk(base_dir, onerror=on_walk_error):
            seen += 1
            if seen % 250 == 0:
                self.root.after(
                    0,
                    lambda count=seen, label=status_label: self.status_var.set(f"{label} ({count} folders)")
                )

            rel_path = os.path.relpath(current_dir, base_dir)
            if rel_path == '.':
                continue

            indexed_paths.add(os.path.normcase(os.path.normpath(rel_path)))
            if music_folders_only and self._directory_has_audio(filenames):
                try:
                    edited = os.path.getmtime(current_dir)
                except OSError:
                    continue
                music_folders.append({
                    'path': current_dir,
                    'rel': rel_path,
                    'mtime': edited
                })

        if music_folders_only:
            return music_folders
        return indexed_paths

    def _folder_is_in_target(self, rel_path, target_index):
        candidates = [
            os.path.normcase(os.path.normpath(rel_path)),
            os.path.normcase(os.path.normpath(self._transform_flac_path(rel_path)))
        ]
        return any(candidate in target_index for candidate in candidates)

    def scan_recent_folders(self):
        if self.conversion_in_progress or self.scan_in_progress or self.transfer_in_progress:
            return

        source_base = self.sanitize_path(self.source_base_entry.get())
        target_base = self.sanitize_path(self.target_entry.get())

        if not source_base or not os.path.isdir(source_base):
            messagebox.showerror("Error", "Please select a valid source base folder before scanning.")
            return
        if not target_base or not os.path.isdir(target_base):
            messagebox.showerror("Error", "Please select a valid target base folder before scanning.")
            return

        try:
            limit = int(self.recent_limit_var.get())
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 2000))

        self.scan_in_progress = True
        self.scan_button.config(state=tk.DISABLED)
        self.recent_count_var.set("Scanning...")
        self.status_var.set("Indexing source folders...")
        self.log(f"Indexing source folders in {source_base}")
        self.log(f"Indexing target folders in {target_base}")

        worker = threading.Thread(
            target=self._scan_recent_folders_worker,
            args=(source_base, target_base, limit),
            daemon=True
        )
        worker.start()

    def _scan_recent_folders_worker(self, source_base, target_base, limit):
        try:
            source_folders = self._index_directories(source_base, True, "Indexing source")
            self.root.after(0, lambda: self.status_var.set("Indexing target folders..."))
            target_index = self._index_directories(target_base, False, "Indexing target")

            missing = [
                folder for folder in source_folders
                if not self._folder_is_in_target(folder['rel'], target_index)
            ]
            missing.sort(key=lambda folder: folder['mtime'], reverse=True)
            shown = missing[:limit]
            self.root.after(
                0,
                lambda shown=shown, source_count=len(source_folders), target_count=len(target_index), missing_count=len(missing), limit=limit: self._show_recent_folders(
                    shown, source_count, target_count, missing_count, limit
                )
            )
        except Exception as e:
            message = str(e)
            self.root.after(0, lambda message=message: self._scan_failed(message))

    def _show_recent_folders(self, folders, source_count, target_count, missing_count, limit):
        existing = self.recent_tree.get_children()
        if existing:
            self.recent_tree.delete(*existing)
        self.recent_by_id = {}

        for folder in folders:
            edited = datetime.fromtimestamp(folder['mtime']).strftime('%Y-%m-%d %H:%M')
            item_id = self.recent_tree.insert('', tk.END, values=(edited, folder['rel']))
            self.recent_by_id[item_id] = folder

        shown_count = len(folders)
        if missing_count > shown_count:
            summary = f"Showing {shown_count} of {missing_count} missing (newest {limit})"
        else:
            summary = f"{missing_count} missing folder{'s' if missing_count != 1 else ''}"
        self.recent_count_var.set(summary)
        self.status_var.set(
            f"Indexed {source_count} source folders and {target_count} target folders. {summary}."
        )
        self.log(
            f"Index complete: {source_count} source music folders, "
            f"{target_count} target directories, {missing_count} not found in target."
        )
        self.scan_in_progress = False
        if not self.conversion_in_progress:
            self.scan_button.config(state=tk.NORMAL)

    def _scan_failed(self, message):
        self.scan_in_progress = False
        self.recent_count_var.set("Scan failed")
        self.status_var.set("Scan failed")
        self.log(f"Folder scan failed: {message}")
        if not self.conversion_in_progress:
            self.scan_button.config(state=tk.NORMAL)
        messagebox.showerror("Scan failed", message)

    def select_all_recent(self):
        children = self.recent_tree.get_children()
        if children:
            self.recent_tree.selection_set(children)

    def queue_selected_folders(self):
        selected_ids = set(self.recent_tree.selection())
        if not selected_ids:
            messagebox.showinfo("Queue", "Select one or more folders in the recent list first.")
            return

        added = 0
        for item_id in self.recent_tree.get_children():
            if item_id not in selected_ids:
                continue
            folder = self.recent_by_id.get(item_id)
            if not folder or folder['path'] in self.queued_paths:
                continue
            edited = datetime.fromtimestamp(folder['mtime']).strftime('%Y-%m-%d %H:%M')
            item_id = self.queue_tree.insert('', tk.END, values=(edited, folder['rel']))
            self.queue_by_id[item_id] = folder
            self.conversion_queue.append(folder)
            self.queued_paths.add(folder['path'])
            added += 1

        self._update_queue_count()
        if added == 0:
            self.log("Selected folders are already in the queue.")
        else:
            self.log(f"Queued {added} folder{'s' if added != 1 else ''} for sequential conversion.")

    def remove_selected_from_queue(self):
        selected_ids = list(self.queue_tree.selection())
        if not selected_ids:
            return
        remove_paths = set()
        for item_id in selected_ids:
            folder = self.queue_by_id.pop(item_id, None)
            if folder:
                remove_paths.add(folder['path'])
            self.queue_tree.delete(item_id)
        self.conversion_queue = [
            folder for folder in self.conversion_queue
            if folder['path'] not in remove_paths
        ]
        self.queued_paths.difference_update(remove_paths)
        self._update_queue_count()

    def clear_queue(self):
        existing = self.queue_tree.get_children()
        if existing:
            self.queue_tree.delete(*existing)
        self.conversion_queue = []
        self.queued_paths = set()
        self.queue_by_id = {}
        self._update_queue_count()

    def _update_queue_count(self):
        count = len(self.conversion_queue)
        if count == 0:
            self.queue_count_var.set("Queue empty")
        else:
            self.queue_count_var.set(f"{count} queued")

    def _safe_phone_subfolder(self):
        text = self.phone_subfolder_entry.get().strip().replace('/', os.sep).replace('\\', os.sep)
        parts = [part.strip() for part in text.split(os.sep)]
        parts = [part for part in parts if part and part != '.']
        if not parts or any(part == '..' for part in parts):
            return ['Music']
        return parts

    def _jobs_for_sources(self, folders):
        """Point each album at its converted folder, keeping the Lossy Music tree."""
        jobs = []
        target_base = os.path.normpath(self.target_base_folder)
        target_name = os.path.basename(target_base)
        for folder in folders:
            relative = os.path.relpath(folder, self.source_base_folder)
            if relative in ('.', os.curdir):
                relative = os.path.basename(os.path.normpath(folder))
            target_relative = self._transform_flac_path(relative)
            converted = os.path.normpath(os.path.join(target_base, target_relative))
            if os.path.isdir(converted):
                under_target = os.path.relpath(converted, target_base)
            else:
                under_target = target_relative
            if under_target in ('.', os.curdir):
                library_relative = target_name
            else:
                library_relative = os.path.join(target_name, under_target)
            jobs.append({
                'src': converted,
                'rel': library_relative,
            })
        return jobs

    def _update_send_last_button(self):
        if self.conversion_in_progress or self.transfer_in_progress or self.scan_in_progress:
            return
        state = tk.NORMAL if self.last_converted_outputs else tk.DISABLED
        self.send_last_button.config(state=state)
        self.open_latest_button.config(state=state)
        self.copy_latest_button.config(state=state)

    def _selected_phone_destination(self):
        index = self.phone_device_combo.current()
        if index < 0 or index >= len(self.phone_destinations):
            return None
        return self.phone_destinations[index]

    def refresh_phone_devices(self):
        if self.device_scan_in_progress or self.transfer_in_progress or self.conversion_in_progress:
            return
        self.device_scan_in_progress = True
        self.refresh_devices_button.config(state=tk.DISABLED)
        self.phone_device_combo.set('Looking for a phone...')
        worker = threading.Thread(target=self._refresh_phone_devices_worker, daemon=True)
        worker.start()

    def _refresh_phone_devices_worker(self):
        try:
            destinations = phone_transfer.list_phone_destinations()
            self._post_to_ui(lambda found=destinations: self._show_phone_destinations(found, None))
        except Exception as error:
            message = str(error)
            self._post_to_ui(lambda message=message: self._show_phone_destinations([], message))

    def _post_to_ui(self, callback):
        try:
            self.root.after(0, callback)
        except RuntimeError:
            pass

    def _show_phone_destinations(self, found, error):
        previous = self._selected_phone_destination()
        previous_id = previous.get('id') if previous else self.phone_device_id
        customs = [item for item in self.phone_destinations if item.get('custom')]
        seen = {item.get('id') for item in found}
        self.phone_destinations = [item for item in customs if item.get('id') not in seen] + list(found)
        labels = [phone_transfer.destination_label(item) for item in self.phone_destinations]
        self.device_scan_in_progress = False
        if not self.conversion_in_progress and not self.transfer_in_progress:
            self.refresh_devices_button.config(state=tk.NORMAL)
        if error:
            self.log(f"Could not list phone devices: {error}")
        if not labels:
            self.phone_device_combo['values'] = ['No phone or USB drive detected']
            self.phone_device_combo.current(0)
            self.status_var.set('No phone detected. Unlock it and choose File transfer, then refresh.')
            return
        self.phone_device_combo['values'] = labels
        match = next((index for index, item in enumerate(self.phone_destinations) if item.get('id') == previous_id), 0)
        self.phone_device_combo.current(match)
        chosen = self.phone_destinations[match]
        self.phone_device_id = chosen.get('id', '')
        self.status_var.set(f"Phone ready: {labels[match]}")
        self.log(f"Found {len(self.phone_destinations)} USB destination(s).")

    def _on_phone_device_selected(self, _event=None):
        destination = self._selected_phone_destination()
        if not destination:
            return
        self.phone_device_id = destination.get('id', '')
        self.save_directory_config()

    def browse_phone_folder(self):
        if self.transfer_in_progress or self.conversion_in_progress:
            return
        folder = filedialog.askdirectory(title="Select the folder on the phone or USB drive")
        if not folder:
            return
        folder = self.sanitize_path(folder)
        destination = {
            'kind': 'drive',
            'id': folder,
            'volumeName': folder,
            'model': '',
            'path': folder,
            'names': [],
            'freeBytes': None,
            'custom': True,
            'useSubfolder': False,
        }
        self.phone_destinations = [destination] + [
            item for item in self.phone_destinations if item.get('id') != folder
        ]
        labels = [phone_transfer.destination_label(item) for item in self.phone_destinations]
        self.phone_device_combo['values'] = labels
        self.phone_device_combo.current(0)
        self.phone_device_id = folder
        self.log(f"Phone folder set to: {folder}")
        self.save_directory_config()

    def _fill_latest_converted_list(self):
        existing = self.latest_tree.get_children()
        if existing:
            self.latest_tree.delete(*existing)
        self.latest_by_id = {}
        for job in self.last_converted_outputs:
            path = job.get('src') or ''
            if not path:
                continue
            item_id = self.latest_tree.insert('', tk.END, values=(path,))
            self.latest_by_id[item_id] = path
        children = self.latest_tree.get_children()
        if len(children) == 1:
            self.latest_tree.selection_set(children[0])
            self.latest_tree.focus(children[0])

    def _selected_latest_path(self):
        selected = self.latest_tree.selection()
        if len(selected) != 1:
            return None
        return self.latest_by_id.get(selected[0])

    def _open_latest_from_double_click(self, _event):
        self.open_latest_folder()

    def open_latest_folder(self):
        path = self._selected_latest_path()
        if not path:
            messagebox.showinfo("Open folder", "Select one converted folder first.")
            return
        if not os.path.isdir(path):
            messagebox.showerror("Open folder", f"That folder is not there anymore:\n{path}")
            return
        os.startfile(path)
        self.log(f"Opened folder: {path}")

    def copy_latest_folder(self):
        path = self._selected_latest_path()
        if not path:
            messagebox.showinfo("Copy folder", "Select one converted folder. Each copy is only that folder.")
            return
        if not os.path.isdir(path):
            messagebox.showerror("Copy folder", f"That folder is not there anymore:\n{path}")
            return
        try:
            self._copy_directory_to_clipboard(path)
        except Exception as error:
            messagebox.showerror("Copy folder", str(error))
            return
        self.status_var.set("Copied one folder. Paste it, then select the next folder.")
        self.log(f"Copied one folder to the clipboard: {path}")

    def _copy_directory_to_clipboard(self, path):
        """Put one directory on the clipboard the same way Explorer's Copy does."""
        env = os.environ.copy()
        env['V0CONV_COPY_PATH'] = path
        completed = subprocess.run(
            [
                'powershell',
                '-NoProfile',
                '-NonInteractive',
                '-Command',
                'Set-Clipboard -LiteralPath $env:V0CONV_COPY_PATH'
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            check=False
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or '').strip()
            raise RuntimeError(detail or 'Could not copy that folder to the clipboard.')

    def send_queue_to_phone(self):
        folders = [item['path'] for item in self.conversion_queue]
        self._start_phone_transfer(folders, 'the queue')

    def send_last_converted_to_phone(self):
        self._start_phone_transfer(None, 'the last conversion', jobs=list(self.last_converted_outputs))

    def _start_phone_transfer(self, source_folders, description, jobs=None):
        if self.transfer_in_progress or self.conversion_in_progress or self.scan_in_progress:
            return
        destination = self._selected_phone_destination()
        if not destination:
            messagebox.showerror(
                "No phone selected",
                "No phone or USB drive is selected. Unlock the phone, choose File transfer, and refresh devices."
            )
            return
        self.source_base_folder = self.sanitize_path(self.source_base_entry.get())
        self.target_base_folder = self.sanitize_path(self.target_entry.get())
        if jobs is None:
            if not source_folders:
                messagebox.showerror("Nothing to send", "Queue some folders first, or convert them and use Send last converted.")
                return
            if not self.source_base_folder or not os.path.isdir(self.source_base_folder):
                messagebox.showerror("Error", "Please select a valid source base folder.")
                return
            if not self.target_base_folder:
                messagebox.showerror("Error", "Please select a target base folder.")
                return
            jobs = self._jobs_for_sources(source_folders)
        ready = [job for job in jobs if os.path.isdir(job['src'])]
        missing = [job['rel'] for job in jobs if not os.path.isdir(job['src'])]
        if not ready:
            messagebox.showerror(
                "Nothing to send",
                "Those folders are not in the target library yet. Convert them first, then send the MP3 copies."
            )
            return
        subfolder_parts = [] if destination.get('useSubfolder') is False else self._safe_phone_subfolder()
        where = phone_transfer.destination_label(destination)
        if subfolder_parts:
            where = where + ' / ' + '/'.join(subfolder_parts)
        message = f"Copy {len(ready)} converted folder(s) from {description} to:\n{where}"
        message += f"\n\nThey keep the Lossy Music folders, for example:\n{ready[0]['rel']}"
        if missing:
            message += f"\n\n{len(missing)} folder(s) have not been converted and will be skipped."
        if not messagebox.askyesno("Send to phone", message):
            return
        self.phone_subfolder = os.sep.join(subfolder_parts) if subfolder_parts else self.phone_subfolder
        self.phone_device_id = destination.get('id', '')
        self.save_directory_config()
        self.transfer_in_progress = True
        self.transfer_holder = {}
        self._set_conversion_busy(True)
        self.progress['value'] = 0
        self.progress['maximum'] = 1
        self.status_var.set('Sending folders to the phone...')
        self.log(f"Sending {len(ready)} folder(s) to {where}")
        worker = threading.Thread(
            target=self._phone_transfer_worker,
            args=(destination, subfolder_parts, ready),
            daemon=True
        )
        worker.start()

    def _phone_transfer_worker(self, destination, subfolder_parts, jobs):
        holder = {}
        self.transfer_holder = holder

        def on_progress(index, total, folder_rel, filename):
            def update(index=index, total=total, folder_rel=folder_rel, filename=filename):
                self.progress['maximum'] = max(total, 1)
                self.progress['value'] = index
                self.status_var.set(f"Sending {index}/{total}")
                location = f"{folder_rel}: {filename}" if folder_rel else filename
                self.current_file_var.set(location)
            self._post_to_ui(update)

        def should_cancel():
            return not self.transfer_in_progress

        try:
            if destination.get('kind') == 'mtp':
                finished = phone_transfer.copy_folders_to_mtp(
                    destination.get('names') or [],
                    subfolder_parts,
                    jobs,
                    on_progress,
                    should_cancel,
                    holder
                )
            else:
                dest_root = destination.get('path') or ''
                if destination.get('useSubfolder') is not False and subfolder_parts:
                    dest_root = os.path.join(dest_root, *subfolder_parts)
                finished = phone_transfer.copy_folders_to_drive(jobs, dest_root, on_progress, should_cancel)
            self._post_to_ui(lambda finished=finished: self._phone_transfer_finished(finished, None))
        except Exception as error:
            message = str(error)
            self._post_to_ui(lambda message=message: self._phone_transfer_finished(False, message))

    def _phone_transfer_finished(self, finished, error):
        self.transfer_in_progress = False
        self.transfer_process = None
        self._set_conversion_busy(False)
        self.current_file_var.set('')
        if error:
            self.status_var.set('Phone transfer failed')
            self.log(f"Phone transfer failed: {error}")
            messagebox.showerror("Phone transfer failed", error)
            return
        if finished:
            self.status_var.set('Finished sending folders to the phone')
            self.log('Finished sending folders to the phone. The copies in the target library were kept.')
            return
        self.status_var.set('Phone transfer cancelled')
        self.log('Phone transfer cancelled.')

    def start_queue_conversion(self):
        if self.conversion_in_progress or self.scan_in_progress or self.transfer_in_progress:
            return
        if not self.conversion_queue:
            messagebox.showerror("Error", "Queue is empty. Scan for folders, then queue the ones to convert.")
            return

        self.source_base_folder = self.sanitize_path(self.source_base_entry.get())
        self.target_base_folder = self.sanitize_path(self.target_entry.get())

        if not self.source_base_folder or not os.path.isdir(self.source_base_folder):
            messagebox.showerror("Error", "Please select a valid source base folder!")
            return

        folders = []
        for item in self.conversion_queue:
            folder = item['path']
            if not os.path.isdir(folder):
                self.log(f"Skipping missing folder: {folder}")
                continue
            if not self.is_subpath(folder, self.source_base_folder):
                messagebox.showerror(
                    "Error",
                    f"Queued folder is not inside the source base folder:\n{folder}"
                )
                return
            folders.append(folder)

        if not folders:
            messagebox.showerror("Error", "None of the queued folders are still available.")
            return

        if not os.path.isdir(self.target_base_folder):
            try:
                os.makedirs(self.target_base_folder)
                self.log(f"Created target base directory: {self.target_base_folder}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not create target base folder: {str(e)}")
                return

        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            messagebox.showerror("Error", "ffmpeg not found! Please install ffmpeg and make sure it's in your PATH.")
            return

        self.source_folders = folders
        self.pending_phone_jobs = self._jobs_for_sources(folders)
        self.batch_mode = True
        self.queue_conversion_active = True
        self.conversion_in_progress = True
        self._set_conversion_busy(True)
        self.log(f"Starting sequential conversion of {len(folders)} queued folders")

        conversion_thread = threading.Thread(target=self.batch_convert)
        conversion_thread.daemon = True
        conversion_thread.start()

    def _after_queue_success(self):
        self.clear_queue()
        self.scan_recent_folders()
        
    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        
    def start_conversion(self):
        if self.conversion_in_progress or self.scan_in_progress or self.transfer_in_progress:
            return
        # Validate folders
        self.source_base_folder = self.sanitize_path(self.source_base_entry.get())
        self.source_subfolder = self.sanitize_path(self.source_subfolder_entry.get())
        self.target_base_folder = self.sanitize_path(self.target_entry.get())
        
        # Check if batch mode is enabled
        self.batch_mode = self.batch_mode_var.get()
        
        if not self.source_base_folder:
            messagebox.showerror("Error", "Please select a source base folder!")
            return
            
        # In batch mode, we need the source subfolder to find subdirectories
        if self.batch_mode:
            if not self.source_subfolder:
                messagebox.showerror("Error", "Please select a source subfolder for batch mode!")
                return
            if not os.path.isdir(self.source_subfolder):
                messagebox.showerror("Error", "Source subfolder does not exist!")
                return
            self.source_folders = self.find_subdirectories(self.source_subfolder)
            if not self.source_folders:
                messagebox.showerror("Error", "No subdirectories found in source subfolder!")
                return
            self.log(f"Found {len(self.source_folders)} subdirectories to process in batch mode")
        else:
            # Regular mode - validate subfolder
            if not self.source_subfolder:
                messagebox.showerror("Error", "Please select a source subfolder to convert!")
                return
                
            if not os.path.isdir(self.source_subfolder):
                messagebox.showerror("Error", "Source subfolder does not exist!")
                return
                
            # Verify the subfolder is actually inside the base folder
            if not self.is_subpath(self.source_subfolder, self.source_base_folder):
                messagebox.showerror("Error", "The selected subfolder must be inside the base folder!")
                return
            
            self.source_folders = [self.source_subfolder]
            
        if not os.path.isdir(self.target_base_folder):
            try:
                os.makedirs(self.target_base_folder)
                self.log(f"Created target base directory: {self.target_base_folder}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not create target base folder: {str(e)}")
                return
        
        # Check for ffmpeg
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            messagebox.showerror("Error", "ffmpeg not found! Please install ffmpeg and make sure it's in your PATH.")
            return
            
        # Start conversion in a separate thread
        self.pending_phone_jobs = self._jobs_for_sources(self.source_folders)
        self.conversion_in_progress = True
        self.queue_conversion_active = False
        self._set_conversion_busy(True)
        
        conversion_thread = threading.Thread(target=self.batch_convert if self.batch_mode else self.convert_files)
        conversion_thread.daemon = True
        conversion_thread.start()
        
    def cancel_conversion(self):
        if self.transfer_in_progress:
            self.transfer_in_progress = False
            holder = getattr(self, 'transfer_holder', None) or {}
            process = holder.get('process')
            if process is not None and process.poll() is None:
                process.terminate()
            self.status_var.set("Cancelling transfer...")
            self.log("Cancelling phone transfer...")
            return
        if self.conversion_in_progress:
            self.conversion_in_progress = False
            self.status_var.set("Cancelling...")
            self.log("Cancelling conversion...")
            
    def get_image_dimensions(self, img_data):
        """Get dimensions of an image from its binary data"""
        try:
            img = Image.open(io.BytesIO(img_data))
            return img.size  # (width, height)
        except Exception:
            return (0, 0)  # Return zero dimensions if image can't be processed
            
    def find_subdirectories(self, base_dir):
        """Find all subdirectories in the base directory"""
        subdirs = []
        
        # If base directory contains audio files directly, include it
        has_audio_files = False
        for ext in ['.flac', '.wav', '.aiff', '.aif', '.ape', '.alac', '.mp3', '.m4a', '.ogg']:
            if glob.glob(os.path.join(base_dir, f'*{ext}')):
                has_audio_files = True
                break
                
        if has_audio_files:
            subdirs.append(base_dir)
            
        # Add all direct subdirectories
        for item in os.listdir(base_dir):
            item_path = os.path.join(base_dir, item)
            if os.path.isdir(item_path):
                subdirs.append(item_path)
                
        return subdirs
        
    def batch_convert(self):
        """Process multiple directories in batch mode"""
        total_dirs = len(self.source_folders)
        processed_dirs = 0
        
        self.log(f"Starting batch conversion of {total_dirs} directories")
        
        # Store the total number of processed files for final status
        total_processed_files = 0
        total_converted_files = 0
        total_copied_files = 0
        
        for folder in self.source_folders:
            if not self.conversion_in_progress:
                break
                
            self.log(f"\n--- Processing directory {processed_dirs+1}/{total_dirs}: {os.path.basename(folder)} ---")
            self.status_var.set(f"Processing directory {processed_dirs+1}/{total_dirs}")
            
            # Temporarily set the source_subfolder for this iteration
            self.source_subfolder = folder
            
            # Process the current directory
            self.convert_files(is_batch=True)
            
            # Update batch statistics
            total_processed_files += getattr(self, 'last_processed_count', 0)
            total_converted_files += getattr(self, 'last_converted_count', 0)
            total_copied_files += getattr(self, 'last_copied_count', 0)
            
            # Update progress for batch
            processed_dirs += 1
            
        # Batch conversion complete or cancelled
        if self.conversion_in_progress:
            self.status_var.set(f"Batch complete! Processed {total_processed_files} files ({total_converted_files} converted, {total_copied_files} copied) in {processed_dirs} directories.")
            self.log("\nBatch conversion completed successfully!")
        else:
            self.status_var.set(f"Batch cancelled. Processed {processed_dirs}/{total_dirs} directories.")
            self.log("\nBatch conversion was cancelled.")
            
        self.conversion_complete()
    
    def convert_files(self, is_batch=False):
        # Extensions to convert
        lossless_extensions = ['.flac', '.wav', '.aiff', '.aif', '.ape', '.alac']
        
        # Extensions to copy without conversion
        copy_extensions = ['.mp3', '.m4a', '.ogg', '.opus', '.aac', '.wma', '.mp4']
        
        # Find all audio files in the selected subfolder
        files_to_convert = []
        files_to_copy = []
        
        for root, _, files in os.walk(self.source_subfolder):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                file_path = os.path.join(root, file)
                
                if ext in lossless_extensions:
                    files_to_convert.append(file_path)
                elif ext in copy_extensions:
                    files_to_copy.append(file_path)
        
        total_convert_files = len(files_to_convert)
        total_copy_files = len(files_to_copy)
        total_files = total_convert_files + total_copy_files
        
        if total_files == 0:
            self.log("No audio files found in the selected subfolder!")
            self.status_var.set("No files found")
            if not is_batch:
                self.conversion_complete()
            return
            
        self.log(f"Found {total_convert_files} lossless files to convert and {total_copy_files} non-lossless files to copy")
        self.progress["maximum"] = total_files
        self.progress["value"] = 0
        
        # Decide whether to use parallel processing
        use_parallel = self.parallelize_var.get()
        
        if use_parallel:
            try:
                max_workers = int(self.threads_var.get())
            except ValueError:
                max_workers = max(1, multiprocessing.cpu_count() - 1)
            
            self.log(f"Using parallel processing with {max_workers} workers")
            self.process_files_parallel(files_to_convert, files_to_copy, total_files, is_batch)
        else:
            self.log("Using sequential processing")
            self.process_files_sequential(files_to_convert, files_to_copy, total_files, is_batch)
        
    def process_files_parallel(self, files_to_convert, files_to_copy, total_files, is_batch=False):
        """Process files using parallel execution"""
        # Create a lock for thread-safe operations
        self.lock = threading.Lock()
        self.processed_count = 0
        self.processed_convert = 0
        self.processed_copy = 0
        
        # Setup a thread pool
        # Cap at 8 to prevent too many processes from running simultaneously
        MAX_THREADS = 8
        try:
            max_workers = min(MAX_THREADS, int(self.threads_var.get()))
        except ValueError:
            max_workers = min(MAX_THREADS, max(1, multiprocessing.cpu_count() - 1))
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all conversion tasks
            convert_futures = {}
            for file_path in files_to_convert:
                if not self.conversion_in_progress:
                    break
                future = executor.submit(self.convert_file, file_path)
                convert_futures[future] = file_path
            
            # Submit all copy tasks
            copy_futures = {}
            for file_path in files_to_copy:
                if not self.conversion_in_progress:
                    break
                future = executor.submit(self.copy_file, file_path)
                copy_futures[future] = file_path
                
            # Process completed conversion tasks
            for future in concurrent.futures.as_completed(convert_futures):
                if not self.conversion_in_progress:
                    break
                try:
                    success = future.result()
                    with self.lock:
                        self.processed_count += 1
                        if success:
                            self.processed_convert += 1
                        self.progress["value"] = self.processed_count
                except Exception as e:
                    self.log(f"Error in worker thread: {str(e)}")
                    
            # Process completed copy tasks
            for future in concurrent.futures.as_completed(copy_futures):
                if not self.conversion_in_progress:
                    break
                try:
                    success = future.result()
                    with self.lock:
                        self.processed_count += 1
                        if success:
                            self.processed_copy += 1
                        self.progress["value"] = self.processed_count
                except Exception as e:
                    self.log(f"Error in worker thread: {str(e)}")
        
        # Store statistics for batch mode
        self.last_processed_count = self.processed_count
        self.last_converted_count = self.processed_convert
        self.last_copied_count = self.processed_copy
        
        # Only call conversion_complete if not in batch mode
        if not is_batch:
            if self.conversion_in_progress:
                self.status_var.set(f"Complete! Converted {self.processed_convert} files and copied {self.processed_copy} files.")
                self.log("All files processed successfully!")
            else:
                self.status_var.set(f"Cancelled. Processed {self.processed_count}/{total_files} files.")
                self.log("Operation was cancelled.")
                
            self.conversion_complete()
    
    def convert_file(self, file_path):
        """Convert a single file in a worker thread"""
        if not self.conversion_in_progress:
            return False
            
        # Create relative path from source base folder
        rel_path = os.path.relpath(file_path, self.source_base_folder)
        
        # Thread-safe UI updates
        with self.lock:
            self.status_var.set(f"Converting {self.processed_count+1}/{self.progress['maximum']}")
            self.current_file_var.set(f"Current: {rel_path}")
            self.log(f"Converting: {rel_path}")
            
        # Calculate the target directory and filename
        rel_dir = os.path.dirname(rel_path)
        
        # Replace "flac" with "MP3V0" in directory names (case insensitive)
        path_parts = rel_dir.split(os.sep)
        for i in range(len(path_parts)):
            # Use regex with word boundaries to replace only standalone "flac"
            path_parts[i] = re.sub(r'\bflac\b', 'MP3V0', path_parts[i], flags=re.IGNORECASE)
        
        modified_rel_dir = os.sep.join(path_parts) if path_parts else ""
        target_dir = os.path.join(self.target_base_folder, modified_rel_dir)
        
        file_base = os.path.splitext(os.path.basename(file_path))[0]
        target_file = os.path.join(target_dir, file_base + ".mp3")
        
        # Thread-safe directory creation
        with self.lock:
            os.makedirs(target_dir, exist_ok=True)
        
        # Find album art in the source directory
        source_dir = os.path.dirname(file_path)
        art_files = []
        for art_pattern in ['*.jpg', '*.jpeg', '*.png', 'cover.*', 'folder.*', 'front.*', 'artwork.*', 'album.*']:
            art_files.extend(glob.glob(os.path.join(source_dir, art_pattern)))
        
        art_path = None
        if art_files:
            art_path = art_files[0]  # Use the first artwork found
            
        # Convert the file
        try:
            # Convert audio with ffmpeg using MP3 VBR at highest quality (V0)
            # Windows-specific: hide CMD windows when spawning ffmpeg
            subprocess_kwargs = {
                'check': True,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE
            }
            if sys.platform == 'win32':
                subprocess_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            
            subprocess.run([
                "ffmpeg", "-i", file_path, 
                "-codec:a", "libmp3lame", 
                "-q:a", "0",  # V0 quality (VBR at highest quality) 
                "-map_metadata", "0", 
                "-id3v2_version", "3", 
                "-y",  # Overwrite output files
                target_file
            ], **subprocess_kwargs)
            
            # Embed album art if found - this part must be synchronized
            if art_path:
                try:
                    with open(art_path, 'rb') as img_file:
                        folder_art_data = img_file.read()
                        folder_art_dimensions = self.get_image_dimensions(folder_art_data)
                    
                    # Check if MP3 already has embedded art
                    audio = MP3(target_file, ID3=ID3)
                    
                    # Create ID3 tag if it doesn't exist
                    try:
                        audio.add_tags()
                    except mutagen.id3.error:
                        pass  # Tags already exist
                    
                    # Check if there's existing art and its resolution
                    embedded_art_dimensions = (0, 0)
                    replace_art = True
                    
                    if audio.tags and 'APIC:' in audio.tags:
                        existing_art = audio.tags['APIC:'].data
                        embedded_art_dimensions = self.get_image_dimensions(existing_art)
                        
                        # Compare resolutions: only replace if folder art has higher resolution
                        folder_art_pixels = folder_art_dimensions[0] * folder_art_dimensions[1]
                        embedded_art_pixels = embedded_art_dimensions[0] * embedded_art_dimensions[1]
                        
                        if embedded_art_pixels >= folder_art_pixels:
                            replace_art = False
                            with self.lock:
                                self.log(f"Keeping existing higher resolution art ({embedded_art_dimensions[0]}x{embedded_art_dimensions[1]}) in {os.path.basename(target_file)}")
                    
                    if replace_art:
                        # Determine image MIME type
                        mime_type = "image/jpeg"  # Default
                        if art_path.lower().endswith('.png'):
                            mime_type = "image/png"
                        
                        audio.tags.add(
                            APIC(
                                encoding=3,  # UTF-8
                                mime=mime_type,
                                type=3,  # Cover (front)
                                desc='Cover',
                                data=folder_art_data
                            )
                        )
                        audio.save()
                        with self.lock:
                            self.log(f"Embedded album art ({folder_art_dimensions[0]}x{folder_art_dimensions[1]}) into {os.path.basename(target_file)}")
                except Exception as e:
                    with self.lock:
                        self.log(f"Error handling album art: {str(e)}")
            
            with self.lock:
                self.log(f"Successfully converted to: {os.path.basename(target_file)}")
            return True
                
        except subprocess.CalledProcessError as e:
            with self.lock:
                self.log(f"Error converting {file_path}: {str(e)}")
            return False

    def copy_file(self, file_path):
        """Copy a single file in a worker thread"""
        if not self.conversion_in_progress:
            return False
            
        # Create relative path from source base folder
        rel_path = os.path.relpath(file_path, self.source_base_folder)
        
        # Thread-safe UI updates
        with self.lock:
            self.status_var.set(f"Copying {self.processed_count+1}/{self.progress['maximum']}")
            self.current_file_var.set(f"Current: {rel_path}")
            self.log(f"Copying: {rel_path}")
        
        # Calculate the target directory and filename
        rel_dir = os.path.dirname(rel_path)
        
        # Replace "flac" with "MP3V0" in directory names (case insensitive)
        path_parts = rel_dir.split(os.sep)
        for i in range(len(path_parts)):
            # Use regex with word boundaries to replace only standalone "flac"
            path_parts[i] = re.sub(r'\bflac\b', 'MP3V0', path_parts[i], flags=re.IGNORECASE)
        
        modified_rel_dir = os.sep.join(path_parts) if path_parts else ""
        target_dir = os.path.join(self.target_base_folder, modified_rel_dir)
        
        # Keep the original filename and extension for copied files
        file_name = os.path.basename(file_path)
        target_file = os.path.join(target_dir, file_name)
        
        # Thread-safe directory creation
        with self.lock:
            os.makedirs(target_dir, exist_ok=True)
        
        try:
            # Copy the file
            shutil.copy2(file_path, target_file)
            with self.lock:
                self.log(f"Successfully copied: {os.path.basename(target_file)}")
            return True
        except Exception as e:
            with self.lock:
                self.log(f"Error copying {file_path}: {str(e)}")
            return False
    
    def process_files_sequential(self, files_to_convert, files_to_copy, total_files, is_batch=False):
        """Process files sequentially (original implementation)"""
        processed = 0
        
        # Process lossless files for conversion
        for file_path in files_to_convert:
            if not self.conversion_in_progress:
                break
                
            # Create relative path from source base folder
            rel_path = os.path.relpath(file_path, self.source_base_folder)
            
            # Calculate the target directory and filename
            rel_dir = os.path.dirname(rel_path)
            
            # Replace "flac" with "MP3V0" in directory names (case insensitive)
            path_parts = rel_dir.split(os.sep)
            for i in range(len(path_parts)):
                # Use regex with word boundaries to replace only standalone "flac"
                path_parts[i] = re.sub(r'\bflac\b', 'MP3V0', path_parts[i], flags=re.IGNORECASE)
            
            modified_rel_dir = os.sep.join(path_parts) if path_parts else ""
            target_dir = os.path.join(self.target_base_folder, modified_rel_dir)
            
            file_base = os.path.splitext(os.path.basename(file_path))[0]
            target_file = os.path.join(target_dir, file_base + ".mp3")
            
            # Make sure target directory exists
            os.makedirs(target_dir, exist_ok=True)
            
            # Update status
            self.status_var.set(f"Converting {processed+1}/{total_files}")
            self.current_file_var.set(f"Current: {rel_path}")
            self.log(f"Converting: {rel_path}")
            
            # Find album art in the source directory
            source_dir = os.path.dirname(file_path)
            art_files = []
            for art_pattern in ['*.jpg', '*.jpeg', '*.png', 'cover.*', 'folder.*', 'front.*', 'artwork.*', 'album.*']:
                art_files.extend(glob.glob(os.path.join(source_dir, art_pattern)))
            
            art_path = None
            if art_files:
                art_path = art_files[0]  # Use the first artwork found
                
            # Convert the file
            try:
                # Convert audio with ffmpeg using MP3 VBR at highest quality (V0)
                subprocess.run([
                    "ffmpeg", "-i", file_path, 
                    "-codec:a", "libmp3lame", 
                    "-q:a", "0",  # V0 quality (VBR at highest quality) 
                    "-map_metadata", "0", 
                    "-id3v2_version", "3", 
                    "-y",  # Overwrite output files
                    target_file
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                # Embed album art if found
                if art_path:
                    try:
                        with open(art_path, 'rb') as img_file:
                            folder_art_data = img_file.read()
                            folder_art_dimensions = self.get_image_dimensions(folder_art_data)
                        
                        # Check if MP3 already has embedded art
                        audio = MP3(target_file, ID3=ID3)
                        
                        # Create ID3 tag if it doesn't exist
                        try:
                            audio.add_tags()
                        except mutagen.id3.error:
                            pass  # Tags already exist
                        
                        # Check if there's existing art and its resolution
                        embedded_art_dimensions = (0, 0)
                        replace_art = True
                        
                        if audio.tags and 'APIC:' in audio.tags:
                            existing_art = audio.tags['APIC:'].data
                            embedded_art_dimensions = self.get_image_dimensions(existing_art)
                            
                            # Compare resolutions: only replace if folder art has higher resolution
                            folder_art_pixels = folder_art_dimensions[0] * folder_art_dimensions[1]
                            embedded_art_pixels = embedded_art_dimensions[0] * embedded_art_dimensions[1]
                            
                            if embedded_art_pixels >= folder_art_pixels:
                                replace_art = False
                                self.log(f"Keeping existing higher resolution art ({embedded_art_dimensions[0]}x{embedded_art_dimensions[1]}) in {os.path.basename(target_file)}")
                        
                        if replace_art:
                            # Determine image MIME type
                            mime_type = "image/jpeg"  # Default
                            if art_path.lower().endswith('.png'):
                                mime_type = "image/png"
                            
                            audio.tags.add(
                                APIC(
                                    encoding=3,  # UTF-8
                                    mime=mime_type,
                                    type=3,  # Cover (front)
                                    desc='Cover',
                                    data=folder_art_data
                                )
                            )
                            audio.save()
                            self.log(f"Embedded album art ({folder_art_dimensions[0]}x{folder_art_dimensions[1]}) into {os.path.basename(target_file)}")
                    except Exception as e:
                        self.log(f"Error handling album art: {str(e)}")
                
                self.log(f"Successfully converted to: {os.path.basename(target_file)}")
                
            except subprocess.CalledProcessError as e:
                self.log(f"Error converting {file_path}: {str(e)}")
                
            # Update progress
            processed += 1
            self.progress["value"] = processed
            
        # Process non-lossless files for copying
        for file_path in files_to_copy:
            if not self.conversion_in_progress:
                break
                
            # Create relative path from source base folder
            rel_path = os.path.relpath(file_path, self.source_base_folder)
            
            # Calculate the target directory and filename
            rel_dir = os.path.dirname(rel_path)
            
            # Replace "flac" with "MP3V0" in directory names (case insensitive)
            path_parts = rel_dir.split(os.sep)
            for i in range(len(path_parts)):
                # Use regex with word boundaries to replace only standalone "flac"
                path_parts[i] = re.sub(r'\bflac\b', 'MP3V0', path_parts[i], flags=re.IGNORECASE)
            
            modified_rel_dir = os.sep.join(path_parts) if path_parts else ""
            target_dir = os.path.join(self.target_base_folder, modified_rel_dir)
            
            # Keep the original filename and extension for copied files
            file_name = os.path.basename(file_path)
            target_file = os.path.join(target_dir, file_name)
            
            # Make sure target directory exists
            os.makedirs(target_dir, exist_ok=True)
            
            # Update status
            self.status_var.set(f"Copying {processed+1}/{total_files}")
            self.current_file_var.set(f"Current: {rel_path}")
            self.log(f"Copying: {rel_path}")
            
            try:
                # Copy the file
                shutil.copy2(file_path, target_file)
                self.log(f"Successfully copied: {os.path.basename(target_file)}")
            except Exception as e:
                self.log(f"Error copying {file_path}: {str(e)}")
                
            # Update progress
            processed += 1
            self.progress["value"] = processed
            
        # Store statistics for batch mode
        self.last_processed_count = processed
        self.last_converted_count = total_convert_files
        self.last_copied_count = total_copy_files
        
        # Only call conversion_complete if not in batch mode
        # (batch_convert will handle completion)
        if not is_batch:
            if self.conversion_in_progress:
                self.status_var.set(f"Complete! Converted {total_convert_files} files and copied {total_copy_files} files.")
                self.log("All files processed successfully!")
            else:
                self.status_var.set(f"Cancelled. Processed {processed}/{total_files} files.")
                self.log("Operation was cancelled.")
                
            self.conversion_complete()
        
    def conversion_complete(self):
        completed = self.conversion_in_progress
        queue_run = self.queue_conversion_active
        jobs = list(self.pending_phone_jobs)
        self.conversion_in_progress = False
        self.queue_conversion_active = False

        def finish():
            if completed and jobs:
                ready = [job for job in jobs if os.path.isdir(job['src'])]
                if ready:
                    self.last_converted_outputs = ready
                    self._fill_latest_converted_list()
                    self.log(f"{len(ready)} converted folder(s) are listed. Copy or open one folder at a time.")
            self._set_conversion_busy(False)
            self.current_file_var.set("")
            if queue_run and completed:
                self._after_queue_success()

        self.root.after(0, finish)
        
    def load_directory_config(self):
        """Load previously used directories from config file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.source_base_folder = config.get('source_base_folder', '')
                    self.source_subfolder = config.get('source_subfolder', '')
                    self.target_base_folder = config.get('target_base_folder', '')
                    self.phone_subfolder = config.get('phone_subfolder') or 'Music'
                    self.phone_device_id = config.get('phone_device_id') or ''
        except Exception as e:
            # If config file is corrupted or unreadable, start with empty values
            self.source_base_folder = ""
            self.source_subfolder = ""
            self.target_base_folder = ""
            
    def save_directory_config(self):
        """Save current directories to config file"""
        try:
            phone_subfolder = self.phone_subfolder
            if hasattr(self, 'phone_subfolder_entry'):
                phone_subfolder = self.phone_subfolder_entry.get().strip() or 'Music'
                self.phone_subfolder = phone_subfolder
            config = {
                'source_base_folder': self.source_base_folder,
                'source_subfolder': self.source_subfolder,
                'target_base_folder': self.target_base_folder,
                'phone_subfolder': phone_subfolder,
                'phone_device_id': self.phone_device_id
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            # Silently fail if we can't save config
            pass

if __name__ == "__main__":
    # Check for required packages
    required_packages = {
        'pillow': 'pip install pillow',
        'mutagen': 'pip install mutagen'
    }
    
    missing_packages = []
    
    try:
        import PIL
    except ImportError:
        missing_packages.append(required_packages['pillow'])
        
    try:
        import mutagen
    except ImportError:
        missing_packages.append(required_packages['mutagen'])
    
    # Check if ffmpeg is installed
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("Error: ffmpeg is not installed or not in PATH.")
        print("Please install ffmpeg before running this program.")
        if 'win' in sys.platform:
            print("On Windows, download from https://ffmpeg.org/download.html and add to PATH")
        elif 'darwin' in sys.platform:
            print("On macOS, install using Homebrew: brew install ffmpeg")
        else:
            print("On Linux, install using your package manager (e.g., apt install ffmpeg)")
        
    if missing_packages:
        print("Missing required Python packages. Please install them using the following commands:")
        for cmd in missing_packages:
            print(cmd)
        print("\nAfter installing the required packages, run this script again.")
        
        # If on Windows, keep the console window open
        if 'win' in sys.platform:
            input("Press Enter to exit...")
        sys.exit(1)
    
    root = tk.Tk()
    app = MusicConverter(root)
    root.mainloop()