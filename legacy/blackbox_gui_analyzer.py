import os
import sys
import glob
import re
import datetime
import subprocess
import threading
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

class ScrollableCheckboxFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, background="#f1f5f9", height=180)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        
        # Style inner frame to match Left panel style
        self.scrollable_frame = ttk.Frame(self.canvas, style="Left.TFrame")
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Bind mousewheel for scrolling
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
        self.vars = {}        # col_name: BooleanVar
        self.checkboxes = {}  # col_name: Checkbutton
        
    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)
        
    def _on_mousewheel(self, event):
        # Only scroll if mouse is over this widget or canvas
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
    def populate(self, columns, search_term=""):
        # Hide all currently packed checkboxes
        for cb in self.checkboxes.values():
            cb.pack_forget()
            
        search_term = search_term.lower()
        for col in columns:
            if search_term and search_term not in col.lower():
                continue
                
            if col not in self.vars:
                self.vars[col] = tk.BooleanVar(value=False)
                
            if col not in self.checkboxes:
                cb = ttk.Checkbutton(
                    self.scrollable_frame,
                    text=col,
                    variable=self.vars[col],
                    style="TCheckbutton"
                )
                self.checkboxes[col] = cb
                
            self.checkboxes[col].pack(anchor=tk.W, fill=tk.X, padx=5, pady=1)
            
    def get_selected(self):
        return [col for col, var in self.vars.items() if var.get()]
        
    def clear_all(self):
        for var in self.vars.values():
            var.set(False)
            
    def select_all_filtered(self, columns, search_term=""):
        search_term = search_term.lower()
        for col in columns:
            if not search_term or search_term in col.lower():
                if col in self.vars:
                    self.vars[col].set(True)

class BlackboxAnalyzerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("INAV Blackbox Interactive Analyzer")
        self.root.geometry("1400x950")
        self.root.minsize(1050, 750)
        
        # State variables
        self.selected_txt_path = ""
        self.available_csvs = []
        self.current_df = None
        self.all_columns = []
        self.canvas = None
        self.toolbar = None
        
        # Determine paths
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.decoder_path = os.path.join(script_dir, "blackbox_decode.exe")
        if not os.path.exists(self.decoder_path):
            self.decoder_path = os.path.join(script_dir, "obj", "blackbox_decode.exe")
            
        # Create temp folder for decoding (prevents dumping next to source logs)
        self.temp_decode_dir = os.path.join(script_dir, "decoded_temp")
        os.makedirs(self.temp_decode_dir, exist_ok=True)

        self.setup_styles()
        self.create_widgets()
        self.set_status("Ready. Select a Blackbox log (.TXT) or CSV.")
        
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        
        # Colors: slate / indigo theme
        style.configure("TFrame", background="#f8fafc")
        style.configure("Left.TFrame", background="#f1f5f9", relief="flat")
        style.configure("Right.TFrame", background="#ffffff", relief="flat")
        
        style.configure("TLabel", background="#f8fafc", foreground="#334155", font=("Segoe UI", 10))
        style.configure("Header.TLabel", background="#f1f5f9", foreground="#1e293b", font=("Segoe UI", 11, "bold"))
        style.configure("Title.TLabel", background="#f1f5f9", foreground="#4f46e5", font=("Segoe UI", 13, "bold"))
        
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=5, background="#e2e8f0", borderwidth=1)
        style.map("TButton",
                  background=[("active", "#cbd5e1"), ("pressed", "#94a3b8")],
                  foreground=[("active", "#0f172a")])
                  
        style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=7, background="#4f46e5", foreground="#ffffff")
        style.map("Action.TButton",
                  background=[("active", "#4338ca"), ("pressed", "#3730a3")])
                  
        style.configure("TCheckbutton", background="#f1f5f9", foreground="#334155", font=("Segoe UI", 9))
        style.configure("TRadiobutton", background="#f1f5f9", foreground="#334155", font=("Segoe UI", 9))
        style.configure("TEntry", fieldbackground="#ffffff", foreground="#334155")
        
    def create_widgets(self):
        # Main layout pane split into Left (Controls) and Right (Visuals)
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)
        
        left_frame = ttk.Frame(main_pane, style="Left.TFrame", padding=12, width=380)
        main_pane.add(left_frame, weight=1)
        
        right_frame = ttk.Frame(main_pane, style="Right.TFrame", padding=10)
        main_pane.add(right_frame, weight=4)
        
        # --- LEFT PANEL: CONTROLS ---
        title_lbl = ttk.Label(left_frame, text="Blackbox Plot Analyzer", style="Title.TLabel")
        title_lbl.pack(anchor=tk.W, pady=(0, 10))
        
        # 1. Select log file
        file_sec = ttk.LabelFrame(left_frame, text=" 1. Select Log File ", padding=8)
        file_sec.pack(fill=tk.X, pady=(0, 10))
        
        select_btn = ttk.Button(file_sec, text="Open .TXT or .CSV Log", command=self.browse_file)
        select_btn.pack(fill=tk.X, pady=(0, 4))
        
        self.file_lbl = ttk.Label(file_sec, text="No log loaded", wraplength=340, justify=tk.LEFT, font=("Segoe UI", 8, "italic"), foreground="#64748b")
        self.file_lbl.pack(anchor=tk.W, fill=tk.X)
        
        # 2. Select specific session from combobox
        self.log_sec = ttk.LabelFrame(left_frame, text=" 2. Select Flight Session ", padding=8)
        self.log_sec.pack(fill=tk.X, pady=(0, 10))
        
        self.log_combo_var = tk.StringVar()
        self.log_combo = ttk.Combobox(self.log_sec, textvariable=self.log_combo_var, state="readonly")
        self.log_combo.pack(fill=tk.X, pady=(0, 4))
        self.log_combo.bind("<<ComboboxSelected>>", self.on_log_selected)
        
        self.log_info_lbl = ttk.Label(self.log_sec, text="Select log to load columns", font=("Segoe UI", 8), foreground="#64748b")
        self.log_info_lbl.pack(anchor=tk.W)
        
        # Status (packed first at the bottom of left panel)
        self.status_lbl = ttk.Label(left_frame, text="Ready", font=("Segoe UI", 8, "italic"), foreground="#475569", anchor=tk.W, wraplength=340)
        self.status_lbl.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 0))
        
        # Action buttons (packed next at the bottom, so they sit above the status label)
        self.save_plot_btn = ttk.Button(left_frame, text="Save Current Plot image...", command=self.save_plot)
        self.save_plot_btn.pack(fill=tk.X, side=tk.BOTTOM, pady=(0, 5))
        
        self.plot_btn = ttk.Button(left_frame, text="Generate Interactive Graph", style="Action.TButton", command=self.plot_data)
        self.plot_btn.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 5))
        
        # 3. Choose Presets or Custom options (packed last as fill/expand so it takes remaining middle space)
        graph_sec = ttk.LabelFrame(left_frame, text=" 3. Select Telemetry Views ", padding=8)
        graph_sec.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.plot_preset_var = tk.StringVar(value="lidar_motors")
        
        presets = [
            ("LiDAR & Motors & Throttle", "lidar_motors"),
            ("Motors Only (motor[0..3])", "motors_only"),
            ("Receiver Commands (rcData[0..3])", "rc_inputs"),
            ("LiDAR Altitude (surfaceRaw)", "lidar_only"),
            ("Battery Levels (vbat & amp)", "battery"),
            ("Custom Multi-Select Columns...", "custom")
        ]
        
        for text, val in presets:
            rbtn = ttk.Radiobutton(graph_sec, text=text, value=val, variable=self.plot_preset_var, command=self.on_preset_changed)
            rbtn.pack(anchor=tk.W, pady=2)
            
        # Custom multiselect view
        self.custom_frame = ttk.Frame(graph_sec, padding=(10, 4, 0, 0))
        
        # Filter entry for searching columns
        filter_lbl = ttk.Label(self.custom_frame, text="Search Columns:", font=("Segoe UI", 9, "bold"))
        filter_lbl.pack(anchor=tk.W)
        
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", self.on_filter_changed)
        self.filter_entry = ttk.Entry(self.custom_frame, textvariable=self.filter_var)
        self.filter_entry.pack(fill=tk.X, pady=(2, 4))
        
        # Checkbox actions (Select All / Clear All)
        btn_act_frame = ttk.Frame(self.custom_frame)
        btn_act_frame.pack(fill=tk.X, pady=(0, 4))
        
        sel_all_btn = ttk.Button(btn_act_frame, text="Select Filtered", command=self.select_all_filtered, padding=2)
        sel_all_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        
        clear_btn = ttk.Button(btn_act_frame, text="Clear All", command=self.clear_all_checkboxes, padding=2)
        clear_btn.pack(side=tk.RIGHT, expand=True, fill=tk.X, padx=(2, 0))
        
        # Scrollable checkbox container
        self.checkbox_frame = ScrollableCheckboxFrame(self.custom_frame)
        self.checkbox_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- RIGHT PANEL: INTERACTIVE VISUALIZATIONS ---
        self.plot_container = ttk.Frame(right_frame)
        self.plot_container.pack(fill=tk.BOTH, expand=True)
        
        self.placeholder_lbl = ttk.Label(
            self.plot_container,
            text="No Flight Log Loaded\n\n1. Select a file on the left.\n2. Choose a session and preset.\n3. Click 'Generate Interactive Graph'.\n\nUse the toolbar at the bottom of the graph to pan, zoom, and navigate the timeseries data.",
            justify=tk.CENTER,
            font=("Segoe UI", 11, "bold"),
            foreground="#94a3b8"
        )
        self.placeholder_lbl.pack(expand=True)
        
    def set_status(self, text):
        self.status_lbl.config(text=text)
        self.root.update_idletasks()
        
    def browse_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("INAV Blackbox Files", "*.TXT;*.csv"), ("Raw Blackbox Logs", "*.TXT"), ("Decoded CSV Logs", "*.csv")]
        )
        if not file_path:
            return
            
        self.selected_txt_path = file_path
        self.file_lbl.config(text=os.path.basename(file_path))
        
        if file_path.lower().endswith(".txt"):
            self.set_status("TXT file selected. Running decoder...")
            threading.Thread(target=self.run_decoder, args=(file_path,), daemon=True).start()
        else:
            self.set_status("CSV file selected. Loading data...")
            self.available_csvs = [file_path]
            self.update_log_combobox()
            
    def run_decoder(self, txt_path):
        if not os.path.exists(self.decoder_path):
            self.root.after(0, lambda: messagebox.showerror("Decoder Error", f"Could not find blackbox_decode.exe in workspace path:\n{self.decoder_path}\n\nPlease compile it first using 'make' or verify folder layout."))
            self.root.after(0, lambda: self.set_status("Failed to locate blackbox_decode.exe."))
            return
            
        self.root.after(0, lambda: self.set_status("Decoding raw TXT file..."))
        
        try:
            # Copy the TXT file to the temp directory so that outputs are created there
            temp_txt_path = os.path.join(self.temp_decode_dir, os.path.basename(txt_path))
            if os.path.abspath(txt_path) != os.path.abspath(temp_txt_path):
                shutil.copy2(txt_path, temp_txt_path)
                
            # Run the blackbox decoder on the copied TXT file in the temp directory
            cmd = [self.decoder_path, temp_txt_path]
            process = subprocess.run(cmd, capture_output=True, text=True, cwd=self.temp_decode_dir)
            
            # Clean up the temp copied TXT file to save space
            if os.path.abspath(txt_path) != os.path.abspath(temp_txt_path) and os.path.exists(temp_txt_path):
                try:
                    os.remove(temp_txt_path)
                except Exception:
                    pass
            
            if process.returncode != 0:
                self.root.after(0, lambda: messagebox.showwarning("Decoder Warning", f"Decoder finished with exit code {process.returncode}.\nStderr:\n{process.stderr}"))
                
            # Scan for generated CSV files in temp directory
            base_no_ext = os.path.splitext(os.path.basename(txt_path))[0]
            pattern = os.path.join(self.temp_decode_dir, f"{base_no_ext}.*.csv")
            generated_csvs = sorted(glob.glob(pattern))
            
            if not generated_csvs:
                # Check standard fallback formats
                pattern_alt = os.path.join(self.temp_decode_dir, f"{base_no_ext}*.csv")
                generated_csvs = sorted(glob.glob(pattern_alt))
                
            if not generated_csvs:
                self.root.after(0, lambda: messagebox.showerror("Error", "Decoding succeeded but no CSV files were found. Check output logs."))
                self.root.after(0, lambda: self.set_status("No CSV logs parsed."))
                return
                
            self.available_csvs = generated_csvs
            self.root.after(0, self.update_log_combobox)
            self.root.after(0, lambda: self.set_status(f"Successfully decoded. Parsed {len(generated_csvs)} log session(s) in temp directory."))
            
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Decoder Error", f"Exception during decode execution:\n{str(e)}"))
            self.root.after(0, lambda: self.set_status("Exception occurred during decoding."))

    def update_log_combobox(self):
        names = []
        start_dt = self.get_start_time(self.selected_txt_path)
        
        for i, path in enumerate(self.available_csvs):
            try:
                # Fast read of just the time column using pandas
                df_time = pd.read_csv(path, usecols=['time (us)'])
                if not df_time.empty:
                    first_us = df_time['time (us)'].iloc[0]
                    last_us = df_time['time (us)'].iloc[-1]
                    duration_sec = (last_us - first_us) / 1_000_000.0
                    
                    # Log session start wall-clock time
                    session_start = start_dt + datetime.timedelta(microseconds=int(first_us))
                    time_str = session_start.strftime("%H:%M:%S")
                    duration_str = f"{duration_sec:.1f}s"
                    
                    suffix = os.path.basename(path).split('.')[-2]
                    names.append(f"Log {i+1} ({suffix}) - {duration_str} @ {time_str}")
                else:
                    names.append(f"Log {i+1} ({os.path.basename(path).split('.')[-2]})")
            except Exception:
                names.append(f"Log {i+1} ({os.path.basename(path).split('.')[-2]})")
                
        self.log_combo['values'] = names
        if names:
            self.log_combo.current(0)
            self.on_log_selected(None)
            
    def get_start_time(self, txt_path):
        # Try to read start datetime from TXT header
        if txt_path and txt_path.lower().endswith('.txt'):
            try:
                with open(txt_path, 'rb') as f:
                    header_bytes = f.read(12000)
                    header_text = header_bytes.decode('ascii', errors='ignore')
                    for line in header_text.splitlines():
                        if "Log start datetime" in line:
                            parts = line.split(":", 1)
                            if len(parts) > 1:
                                dt_str = parts[1].strip()
                                match = re.search(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})", dt_str)
                                if match:
                                    date_str, h, m, s = match.groups()
                                    return datetime.datetime.strptime(f"{date_str} {h}:{m}:{s}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
                
        if not txt_path:
            return datetime.datetime.now()
            
        # Fallback to filename blackbox_log_2026-06-17_134345.TXT
        base = os.path.basename(txt_path)
        match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(\d{2})", base)
        if match:
            date_str, h, m, s = match.groups()
            try:
                return datetime.datetime.strptime(f"{date_str} {h}:{m}:{s}", "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        
        # Fallback to file system modification time
        try:
            mtime = os.path.getmtime(txt_path)
            return datetime.datetime.fromtimestamp(mtime)
        except Exception:
            return datetime.datetime.now()

    def parse_pids(self, txt_path):
        pids = {}
        if not txt_path:
            return pids
            
        # If they opened a CSV, try to find a matching TXT file in same or parent directory
        if txt_path.lower().endswith('.csv'):
            base_dir = os.path.dirname(txt_path)
            base_name = os.path.basename(txt_path)
            match = re.match(r"(blackbox_log_\d{4}-\d{2}-\d{2}_\d{6})", base_name)
            if match:
                root_name = match.group(1)
                cand = os.path.join(base_dir, f"{root_name}.TXT")
                if os.path.exists(cand):
                    txt_path = cand
                else:
                    parent_dir = os.path.dirname(base_dir)
                    cand_parent = os.path.join(parent_dir, f"{root_name}.TXT")
                    if os.path.exists(cand_parent):
                        txt_path = cand_parent
                        
        if not txt_path.lower().endswith('.txt') or not os.path.exists(txt_path):
            return pids
            
        try:
            with open(txt_path, 'rb') as f:
                header_bytes = f.read(15000)
                header_text = header_bytes.decode('ascii', errors='ignore')
                for line in header_text.splitlines():
                    if line.startswith('H') and 'PID:' in line:
                        parts = line[1:].strip().split(':')
                        if len(parts) == 2:
                            name = parts[0].strip()
                            vals = parts[1].strip()
                            pids[name] = vals
        except Exception:
            pass
        return pids

    def on_log_selected(self, event):
        idx = self.log_combo.current()
        if idx < 0:
            return
            
        csv_path = self.available_csvs[idx]
        self.set_status(f"Loading {os.path.basename(csv_path)}...")
        
        try:
            # Load headers and a preview to configure options
            preview_df = pd.read_csv(csv_path, nrows=50)
            self.all_columns = list(preview_df.columns)
            
            # Setup checkboxes in custom list
            self.checkbox_frame.populate(self.all_columns, self.filter_var.get())
                
            # Display file specs & Load full dataframe
            file_size_mb = os.path.getsize(csv_path) / (1024 * 1024)
            self.current_df = pd.read_csv(csv_path)
            
            # Calculate duration / flight time
            duration_desc = "Unknown"
            actual_start_desc = "Unknown Start"
            
            if 'time (us)' in self.current_df.columns:
                start_us = self.current_df['time (us)'].iloc[0]
                end_us = self.current_df['time (us)'].iloc[-1]
                duration_sec = (end_us - start_us) / 1_000_000.0
                duration_desc = f"{duration_sec:.2f}s"
                
                # Calculate absolute wall-clock times
                start_dt = self.get_start_time(self.selected_txt_path)
                session_start = start_dt + datetime.timedelta(microseconds=int(start_us))
                actual_start_desc = session_start.strftime("%Y-%m-%d %H:%M:%S")
                
            # Parse and format PIDs
            pids = self.parse_pids(self.selected_txt_path)
            pid_text = ""
            if pids:
                pid_text = "\n\n--- Configured PIDs ---"
                for axis in ['roll', 'pitch', 'yaw']:
                    key = f"{axis}PID"
                    if key in pids:
                        vals = pids[key].split(',')
                        if len(vals) >= 4:
                            pid_text += f"\n{axis.capitalize()}: P={vals[0]} I={vals[1]} D={vals[2]} FF={vals[3]}"
                        elif len(vals) == 3:
                            pid_text += f"\n{axis.capitalize()}: P={vals[0]} I={vals[1]} D={vals[2]}"
                
                # Level/Alt/Pos PIDs if present
                extra_pids = []
                for key in ['altPID', 'posPID', 'levelPID']:
                    if key in pids:
                        name = key[:-3].capitalize()
                        vals = pids[key].split(',')
                        extra_pids.append(f"{name}: P={vals[0]}")
                if extra_pids:
                    pid_text += "\n" + " | ".join(extra_pids)
            else:
                pid_text = "\n\n--- Configured PIDs ---\nNo PID headers found"
                
            self.log_info_lbl.config(
                text=f"File Size: {file_size_mb:.2f} MB | Duration: {duration_desc}\nLogged At: {actual_start_desc}\nColumns: {len(preview_df.columns)}{pid_text}"
            )
            self.set_status(f"Loaded session. Flight Time: {duration_desc} starting at {actual_start_desc}.")
            
        except Exception as e:
            messagebox.showerror("File Error", f"Failed to load CSV file:\n{str(e)}")
            self.set_status("Error loading CSV file.")

    def on_preset_changed(self):
        val = self.plot_preset_var.get()
        if val == "custom":
            self.custom_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.custom_frame.pack_forget()

    def on_filter_changed(self, *args):
        term = self.filter_var.get()
        self.checkbox_frame.populate(self.all_columns, term)

    def select_all_filtered(self):
        self.checkbox_frame.select_all_filtered(self.all_columns, self.filter_var.get())

    def clear_all_checkboxes(self):
        self.checkbox_frame.clear_all()

    def plot_data(self):
        if self.current_df is None:
            messagebox.showwarning("Warning", "Please load a flight log file first.")
            return
            
        preset = self.plot_preset_var.get()
        
        time_col = 'time (us)'
        if time_col not in self.current_df.columns:
            time_col = self.current_df.columns[1] # fallback to second column
            
        time_sec = (self.current_df[time_col] - self.current_df[time_col].iloc[0]) / 1_000_000.0
        
        # Calculate actual datetimes for X-axis
        start_dt = self.get_start_time(self.selected_txt_path)
        time_datetimes = pd.Series([start_dt + datetime.timedelta(seconds=float(t)) for t in time_sec])
        
        # Clean up existing widgets in plot container
        self.placeholder_lbl.pack_forget()
        if self.canvas:
            self.canvas.get_tk_widget().destroy()
        if self.toolbar:
            self.toolbar.destroy()
            
        # Plot styling setup
        # Calculate number of subplots to adjust size dynamically
        num_subplots = 1
        if preset == "lidar_motors":
            num_subplots = 3
        elif preset == "rc_inputs":
            num_subplots = 4
        elif preset == "battery":
            num_subplots = 2
        elif preset == "custom":
            num_subplots = max(1, len(self.checkbox_frame.get_selected()))
            
        fig_height = max(4.5, min(14.0, num_subplots * 2.0))
        
        # Plot styling setup
        fig = Figure(figsize=(10, fig_height), dpi=100)
        fig.patch.set_facecolor('#ffffff')
        
        try:
            if preset == "lidar_motors":
                (ax1, ax2, ax3) = fig.subplots(3, 1, sharex=True)
                
                # Plot Lidar Raw (surfaceRaw)
                if 'surfaceRaw' in self.current_df.columns:
                    valid = self.current_df[self.current_df['surfaceRaw'] > 0]
                    v_time_sec = (valid[time_col] - self.current_df[time_col].iloc[0]) / 1_000_000.0
                    v_time_datetimes = [start_dt + datetime.timedelta(seconds=float(t)) for t in v_time_sec]
                    ax1.plot(v_time_datetimes, valid['surfaceRaw'], color='#0f766e', linewidth=1.5)
                    ax1.set_ylabel("LiDAR Altitude (cm)", color='#0f766e', fontweight='semibold')
                    ax1.set_title("Rangefinder (LiDAR) Raw Altitude", fontsize=11, fontweight='bold', loc='left', color='#334155')
                else:
                    ax1.text(0.5, 0.5, "surfaceRaw column not found", ha='center', va='center')
                
                # Plot Throttle (rcData[3])
                if 'rcData[3]' in self.current_df.columns:
                    ax2.plot(time_datetimes, self.current_df['rcData[3]'], color='#4f46e5', linewidth=1.5)
                    ax2.set_ylabel("Throttle Input", color='#4f46e5', fontweight='semibold')
                    ax2.set_title("Receiver Throttle Command (rcData[3])", fontsize=11, fontweight='bold', loc='left', color='#334155')
                    ax2.set_ylim(950, 2050)
                else:
                    ax2.text(0.5, 0.5, "rcData[3] column not found", ha='center', va='center')
                    
                # Plot Motors (motor[0..3])
                motor_colors = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b']
                motors_plotted = False
                for i in range(4):
                    m_col = f"motor[{i}]"
                    if m_col in self.current_df.columns:
                        ax3.plot(time_datetimes, self.current_df[m_col], color=motor_colors[i], linewidth=1.2, label=f"Motor {i}")
                        motors_plotted = True
                
                if motors_plotted:
                    ax3.set_ylabel("Motor Power", fontweight='semibold')
                    ax3.set_title("ESC Motors Output", fontsize=11, fontweight='bold', loc='left', color='#334155')
                    ax3.set_ylim(1000, 2050)
                    ax3.legend(loc='upper right', frameon=True, facecolor='white', edgecolor='none')
                else:
                    ax3.text(0.5, 0.5, "motor[0..3] columns not found", ha='center', va='center')
                
                ax3.set_xlabel("Flight Time (Clock Time)", fontweight='semibold')
                
            elif preset == "motors_only":
                ax = fig.add_subplot(111)
                motor_colors = ['#ef4444', '#3b82f6', '#10b981', '#f59e0b']
                for i in range(4):
                    m_col = f"motor[{i}]"
                    if m_col in self.current_df.columns:
                        ax.plot(time_datetimes, self.current_df[m_col], color=motor_colors[i], linewidth=1.5, label=f"Motor {i}")
                ax.set_title("ESC Motor Commands (motor[0..3])", fontsize=12, fontweight='bold', loc='left', color='#334155')
                ax.set_xlabel("Flight Time (Clock Time)", fontweight='semibold')
                ax.set_ylabel("Signal Value", fontweight='semibold')
                ax.set_ylim(1000, 2050)
                ax.legend(loc='upper right')
                
            elif preset == "rc_inputs":
                axes = fig.subplots(4, 1, sharex=True)
                channels = ["Roll", "Pitch", "Yaw", "Throttle"]
                colors = ["#ef4444", "#3b82f6", "#10b981", "#4f46e5"]
                
                for i in range(4):
                    r_col = f"rcData[{i}]"
                    if r_col in self.current_df.columns:
                        axes[i].plot(time_datetimes, self.current_df[r_col], color=colors[i], linewidth=1.5)
                        axes[i].set_ylabel(channels[i], color=colors[i], fontweight='semibold')
                        if i == 0:
                            axes[i].set_title("Receiver Inputs (rcData[0..3])", fontsize=12, fontweight='bold', loc='left', color='#334155')
                    else:
                        axes[i].text(0.5, 0.5, f"{r_col} not found", ha='center', va='center')
                
                axes[3].set_xlabel("Flight Time (Clock Time)", fontweight='semibold')
                
            elif preset == "lidar_only":
                ax = fig.add_subplot(111)
                if 'surfaceRaw' in self.current_df.columns:
                    valid = self.current_df[self.current_df['surfaceRaw'] > 0]
                    v_time_sec = (valid[time_col] - self.current_df[time_col].iloc[0]) / 1_000_000.0
                    v_time_datetimes = [start_dt + datetime.timedelta(seconds=float(t)) for t in v_time_sec]
                    ax.plot(v_time_datetimes, valid['surfaceRaw'], color='#0f766e', linewidth=1.5)
                    ax.set_title("Rangefinder (LiDAR) Raw Altitude", fontsize=12, fontweight='bold', loc='left', color='#334155')
                    ax.set_ylabel("Distance (cm)", fontweight='semibold')
                    ax.set_xlabel("Flight Time (Clock Time)", fontweight='semibold')
                else:
                    ax.text(0.5, 0.5, "surfaceRaw column not found", ha='center', va='center')
                    
            elif preset == "battery":
                (ax1, ax2) = fig.subplots(2, 1, sharex=True)
                
                if 'vbat (V)' in self.current_df.columns:
                    ax1.plot(time_datetimes, self.current_df['vbat (V)'], color='#dc2626', linewidth=1.5)
                    ax1.set_ylabel("Battery Voltage (V)", color='#dc2626', fontweight='semibold')
                    ax1.set_title("Battery Telemetry", fontsize=12, fontweight='bold', loc='left', color='#334155')
                else:
                    ax1.text(0.5, 0.5, "vbat (V) not found", ha='center', va='center')
                    
                if 'amperage (A)' in self.current_df.columns:
                    ax2.plot(time_datetimes, self.current_df['amperage (A)'], color='#2563eb', linewidth=1.5)
                    ax2.set_ylabel("Current Amperage (A)", color='#2563eb', fontweight='semibold')
                else:
                    ax2.text(0.5, 0.5, "amperage (A) not found", ha='center', va='center')
                    
                ax2.set_xlabel("Flight Time (Clock Time)", fontweight='semibold')
                
            elif preset == "custom":
                selected_cols = self.checkbox_frame.get_selected()
                if not selected_cols:
                    messagebox.showwarning("Warning", "Please check one or more columns from the custom list.")
                    self.placeholder_lbl.pack(expand=True)
                    return
                    
                count = len(selected_cols)
                if count == 1:
                    ax = fig.add_subplot(111)
                    col = selected_cols[0]
                    ax.plot(time_datetimes, self.current_df[col], color='#4f46e5', linewidth=1.5)
                    ax.set_ylabel(col, fontweight='semibold')
                    ax.set_title(f"Custom Plot: {col}", fontsize=12, fontweight='bold', loc='left', color='#334155')
                    ax.set_xlabel("Flight Time (Clock Time)", fontweight='semibold')
                else:
                    axes = fig.subplots(count, 1, sharex=True)
                    if count == 1:
                        axes = [axes]
                        
                    for i, col in enumerate(selected_cols):
                        axes[i].plot(time_datetimes, self.current_df[col], linewidth=1.5)
                        axes[i].set_ylabel(col, fontweight='semibold', fontsize=9)
                        if i == 0:
                            axes[i].set_title("Custom Multitrend Plot", fontsize=12, fontweight='bold', loc='left', color='#334155')
                            
                    axes[-1].set_xlabel("Flight Time (Clock Time)", fontweight='semibold')
            
            # Setup grids, spines, and datetime formatters for all axes
            for ax in fig.get_axes():
                ax.grid(True, linestyle='--', alpha=0.5, color='#cbd5e1')
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_color('#94a3b8')
                ax.spines['bottom'].set_color('#94a3b8')
                ax.tick_params(colors='#475569')
                
                # Format X-axis with actual wall-clock time
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                
            # Add general header title in a clean single-line format
            total_sec = time_sec.iloc[-1]
            log_filename = os.path.basename(self.available_csvs[self.log_combo.current()])
            start_time_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            fig.suptitle(f"INAV Telemetry | {log_filename} | Start: {start_time_str} | Duration: {total_sec:.2f}s", fontsize=10, fontweight='bold', color='#1e293b')
            
            # Using tight_layout to make all subplots fit nicely
            fig.tight_layout()
            # Ensure suptitle has enough space at the top dynamically
            top_margin = 1.0 - (0.50 / fig_height)
            fig.subplots_adjust(top=top_margin)
            
            # Embed canvas
            self.canvas = FigureCanvasTkAgg(fig, master=self.plot_container)
            self.canvas.draw()
            
            # Embed toolbar at bottom of plot container, packed nicely
            self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_container, pack_toolbar=False)
            self.toolbar.update()
            
            self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)
            self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            
            self.set_status("Interactive plot loaded. Use the bottom toolbar to Zoom (rectangle), Pan (move), or Save.")
            
        except Exception as e:
            messagebox.showerror("Plotting Error", f"An error occurred while plotting data:\n{str(e)}")
            self.set_status("Plotting failed.")
            self.placeholder_lbl.pack(expand=True)

    def save_plot(self):
        if not self.canvas:
            messagebox.showwarning("Warning", "There is no active plot to save.")
            return
            
        file_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("PDF Document", "*.pdf"), ("SVG Vector Graphics", "*.svg"), ("All Files", "*.*")]
        )
        if file_path:
            try:
                self.canvas.figure.savefig(file_path, dpi=300, bbox_inches='tight')
                self.set_status(f"Successfully saved plot to {os.path.basename(file_path)}.")
                messagebox.showinfo("Success", f"Plot saved successfully to:\n{file_path}")
            except Exception as e:
                messagebox.showerror("Save Error", f"Failed to save plot image:\n{str(e)}")

def main():
    root = tk.Tk()
    app = BlackboxAnalyzerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
