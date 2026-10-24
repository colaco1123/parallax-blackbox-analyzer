import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import numpy as np

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

class ScrollableCheckboxFrame(ttk.Frame):
    def __init__(self, parent, callback=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.callback = callback
        
        # Configure scrollable canvas
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, background="#1e293b")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        
        self.scrollable_frame = ttk.Frame(self.canvas, style="Card.TFrame")
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.bind('<Configure>', self._on_canvas_configure)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # Bind mouse scroll
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
        self.vars = {}        # col_name: BooleanVar
        self.checkboxes = {}  # col_name: Checkbutton
        self.columns_list = []
        
    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)
        
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
    def populate(self, columns, search_term=""):
        self.columns_list = columns
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
                    style="DarkCheck.TCheckbutton",
                    command=self._on_check_changed
                )
                self.checkboxes[col] = cb
                
            self.checkboxes[col].pack(anchor=tk.W, fill=tk.X, padx=8, pady=2)
            
    def _on_check_changed(self):
        if self.callback:
            self.callback()

    def get_selected(self):
        return [col for col, var in self.vars.items() if var.get()]
        
    def clear_all(self):
        for var in self.vars.values():
            var.set(False)
        if self.callback:
            self.callback()
            
    def select_all_filtered(self, search_term=""):
        search_term = search_term.lower()
        for col in self.columns_list:
            if not search_term or search_term in col.lower():
                if col in self.vars:
                    self.vars[col].set(True)
        if self.callback:
            self.callback()

class ParallaxPlotterApp:
    def __init__(self, root, default_csv):
        self.root = root
        self.root.title("Parallax Telemetry Log Viewer")
        self.root.geometry("1450x900")
        self.root.minsize(1000, 700)
        
        # Data and State
        self.csv_path = default_csv
        self.df = None
        self.time_series = None  # X axis data (datetime or float)
        self.time_col = None
        self.canvas = None
        self.toolbar = None
        self.plot_colors = [
            "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#06b6d4",
            "#a855f7", "#ec4899", "#84cc16", "#f97316", "#14b8a6"
        ]
        
        self.setup_styles()
        self.create_widgets()
        
        # Load default CSV if exists
        if os.path.exists(self.csv_path):
            self.load_csv(self.csv_path)
        else:
            self.set_status(f"Default log not found. Please click 'Browse' to open a telemetry CSV.")
            
    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # Premium Slate Dark Theme Colors
        # BG: #0f172a, Cards: #1e293b, Accent: #6366f1
        self.style.configure("TFrame", background="#0f172a")
        self.style.configure("Left.TFrame", background="#1e293b", relief="flat")
        self.style.configure("Right.TFrame", background="#0f172a", relief="flat")
        self.style.configure("Card.TFrame", background="#1e293b", relief="flat")
        
        # Labels
        self.style.configure("TLabel", background="#0f172a", foreground="#94a3b8", font=("Segoe UI", 10))
        self.style.configure("Card.TLabel", background="#1e293b", foreground="#f8fafc", font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", background="#1e293b", foreground="#6366f1", font=("Segoe UI", 14, "bold"))
        self.style.configure("Status.TLabel", background="#0f172a", foreground="#64748b", font=("Segoe UI", 9, "italic"))
        self.style.configure("Header.TLabel", background="#1e293b", foreground="#f1f5f9", font=("Segoe UI", 11, "bold"))
        
        # Buttons
        self.style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=6, background="#334155", foreground="#f8fafc", borderwidth=0)
        self.style.map("TButton",
                      background=[("active", "#475569"), ("pressed", "#1e293b")],
                      foreground=[("active", "#ffffff")])
                      
        self.style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=8, background="#6366f1", foreground="#ffffff", borderwidth=0)
        self.style.map("Action.TButton",
                      background=[("active", "#4f46e5"), ("pressed", "#3730a3")])
                      
        # Checkbuttons & Radiobuttons
        self.style.configure("DarkCheck.TCheckbutton", background="#1e293b", foreground="#cbd5e1", font=("Segoe UI", 9))
        self.style.map("DarkCheck.TCheckbutton",
                      foreground=[("active", "#ffffff")],
                      background=[("active", "#1e293b")])
                      
        self.style.configure("DarkRadio.TRadiobutton", background="#1e293b", foreground="#cbd5e1", font=("Segoe UI", 9))
        self.style.map("DarkRadio.TRadiobutton",
                      foreground=[("active", "#ffffff")],
                      background=[("active", "#1e293b")])
                      
        # Entries & Comboboxes
        self.style.configure("TEntry", fieldbackground="#0f172a", foreground="#f8fafc", insertcolor="#ffffff")
        
    def create_widgets(self):
        # Top Header Bar
        header_frame = ttk.Frame(self.root, padding=(16, 10), style="TFrame")
        header_frame.pack(fill=tk.X, side=tk.TOP)
        
        app_title = ttk.Label(header_frame, text="PARALLAX TELEMETRY VISUALIZER", font=("Segoe UI", 16, "bold"), foreground="#6366f1")
        app_title.pack(side=tk.LEFT)
        
        self.file_info_lbl = ttk.Label(header_frame, text="No log loaded", foreground="#64748b", font=("Segoe UI", 10, "italic"))
        self.file_info_lbl.pack(side=tk.RIGHT, padx=10)
        
        # Main body splits Left (parameters/options) and Right (graphs)
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # Left Panel (Controls)
        left_frame = ttk.Frame(main_pane, style="Left.TFrame", padding=12, width=320)
        left_frame.pack_propagate(False)
        main_pane.add(left_frame, weight=1)
        
        # Right Panel (Plot Area)
        right_frame = ttk.Frame(main_pane, style="Right.TFrame", padding=(10, 0, 0, 0))
        main_pane.add(right_frame, weight=4)
        
        # Left controls contents
        # 1. File Selection Section
        file_sec = ttk.LabelFrame(left_frame, text=" 1. Data Source ", padding=8, style="Left.TFrame")
        file_sec.pack(fill=tk.X, pady=(0, 12))
        
        browse_btn = ttk.Button(file_sec, text="Browse CSV Log...", command=self.browse_file)
        browse_btn.pack(fill=tk.X, pady=2)
        
        self.path_lbl = ttk.Label(file_sec, text="Default File: None", font=("Segoe UI", 8), wraplength=280, justify=tk.LEFT, foreground="#94a3b8", style="Card.TLabel")
        self.path_lbl.pack(anchor=tk.W, pady=(4, 0))
        
        # 2. Plot Configuration Options
        opt_sec = ttk.LabelFrame(left_frame, text=" 2. Plot Layout ", padding=8, style="Left.TFrame")
        opt_sec.pack(fill=tk.X, pady=(0, 12))
        
        self.layout_var = tk.StringVar(value="subplots")
        r_sub = ttk.Radiobutton(opt_sec, text="Stacked Subplots (Aligned X)", value="subplots", variable=self.layout_var, style="DarkRadio.TRadiobutton", command=self.delayed_replock)
        r_sub.pack(anchor=tk.W, pady=2)
        r_over = ttk.Radiobutton(opt_sec, text="Overlayed (Single Chart)", value="overlay", variable=self.layout_var, style="DarkRadio.TRadiobutton", command=self.delayed_replock)
        r_over.pack(anchor=tk.W, pady=2)
        
        # X-Axis Time Mode Choice
        time_sec = ttk.Frame(opt_sec, style="Card.TFrame")
        time_sec.pack(fill=tk.X, pady=(6, 2))
        ttk.Label(time_sec, text="X-Axis Unit:", style="Card.TLabel").pack(side=tk.LEFT)
        self.time_mode_var = tk.StringVar(value="auto")
        self.time_combo = ttk.Combobox(time_sec, textvariable=self.time_mode_var, values=["auto", "Wall Clock (iso_time)", "Elapsed Seconds (t_ms)"], state="readonly", width=22)
        self.time_combo.pack(side=tk.RIGHT, padx=4)
        self.time_combo.bind("<<ComboboxSelected>>", lambda e: self.process_time_column())
        
        # Auto Update Toggle
        self.auto_update_var = tk.BooleanVar(value=True)
        cb_auto = ttk.Checkbutton(opt_sec, text="Auto-update on column change", variable=self.auto_update_var, style="DarkCheck.TCheckbutton")
        cb_auto.pack(anchor=tk.W, pady=(6, 0))
        
        # 3. Parameters Selection
        param_sec = ttk.LabelFrame(left_frame, text=" 3. Telemetry Fields ", padding=8, style="Left.TFrame")
        param_sec.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        
        # Search Entry
        search_frame = ttk.Frame(param_sec, style="Card.TFrame")
        search_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(search_frame, text="Search:", style="Card.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.on_search_changed)
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, background="#0f172a")
        self.search_entry.pack(fill=tk.X, expand=True)
        
        # Quick actions for selections
        act_frame = ttk.Frame(param_sec, style="Card.TFrame")
        act_frame.pack(fill=tk.X, pady=(0, 6))
        
        clear_btn = ttk.Button(act_frame, text="Clear All", command=self.clear_all, padding=3)
        clear_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(2, 0))
        
        self.sel_filt_btn = ttk.Button(act_frame, text="Select Visible", command=self.select_all_filtered, padding=3)
        self.sel_filt_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        
        # Scrollable Checkboxes
        self.checkbox_frame = ScrollableCheckboxFrame(param_sec, callback=self.on_checkbox_clicked)
        self.checkbox_frame.pack(fill=tk.BOTH, expand=True)
        
        # Manual Plot button (in case auto-update is off)
        self.plot_btn = ttk.Button(left_frame, text="Update Chart", style="Action.TButton", command=self.generate_plots)
        self.plot_btn.pack(fill=tk.X, side=tk.BOTTOM, pady=(4, 0))
        
        # Status Bar at the bottom
        self.status_lbl = ttk.Label(self.root, text="Ready", style="Status.TLabel")
        self.status_lbl.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=4)
        
        # Right Plot Frame Contents
        self.plot_container = ttk.Frame(right_frame, style="Right.TFrame")
        self.plot_container.pack(fill=tk.BOTH, expand=True)
        
        self.placeholder_lbl = ttk.Label(
            self.plot_container,
            text="PARALLAX LOG VISUALIZER\n\n- Columns list will populate once the CSV is loaded.\n- Choose variables on the left panel to graph them.\n- Use the graph toolbar to zoom and pan.",
            justify=tk.CENTER,
            font=("Segoe UI", 12, "bold"),
            foreground="#475569",
            style="Right.TFrame"
        )
        self.placeholder_lbl.pack(expand=True)
        
    def set_status(self, message):
        self.status_lbl.config(text=message)
        self.root.update_idletasks()
        
    def browse_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("CSV Telemetry Log", "*.csv"), ("All Files", "*.*")]
        )
        if file_path:
            self.load_csv(file_path)
            
    def load_csv(self, path):
        self.set_status(f"Loading {os.path.basename(path)}...")
        self.csv_path = path
        self.path_lbl.config(text=f"Loaded: {os.path.basename(path)}")
        
        try:
            # Load headers first
            preview = pd.read_csv(path, nrows=5)
            self.all_columns = sorted(list(preview.columns))
            
            # Load full dataframe
            self.df = pd.read_csv(path)
            
            # Remove time columns from selectable list
            selectable = [c for c in self.all_columns if c not in ('iso_time', 't_ms')]
            
            # Populate checkboxes
            self.checkbox_frame.populate(selectable, self.search_var.get())
            
            # Setup X axis time column
            self.process_time_column()
            
            file_size_mb = os.path.getsize(path) / (1024 * 1024)
            self.file_info_lbl.config(text=f"{os.path.basename(path)} ({file_size_mb:.2f} MB | {len(self.df)} rows)")
            self.set_status(f"Successfully loaded {len(self.df)} rows. Select fields to plot.")
            
            # Auto select a couple of useful ones to start off (e.g. att.p, att.r, bat.v if present)
            initials = ['att.p', 'att.r', 'bat.v', 'seq.pct', 'ba']
            for col in initials:
                if col in self.checkbox_frame.vars:
                    self.checkbox_frame.vars[col].set(True)
            
            self.generate_plots()
            
        except Exception as e:
            messagebox.showerror("Error Loading CSV", f"Failed to parse the CSV file:\n{str(e)}")
            self.set_status("Loading failed.")
            
    def process_time_column(self):
        if self.df is None:
            return
            
        mode = self.time_mode_var.get()
        
        if mode == "auto":
            # Decide automatically
            if 'iso_time' in self.df.columns:
                self.time_col = 'iso_time'
            elif 't_ms' in self.df.columns:
                self.time_col = 't_ms'
            else:
                self.time_col = None
        elif "iso_time" in mode:
            self.time_col = 'iso_time' if 'iso_time' in self.df.columns else None
        else:
            self.time_col = 't_ms' if 't_ms' in self.df.columns else None
            
        if self.time_col == 'iso_time':
            try:
                self.time_series = pd.to_datetime(self.df['iso_time'])
                self.time_label = "Time (Wall Clock)"
                self.time_is_datetime = True
            except Exception:
                # Fallback
                self.time_series = np.arange(len(self.df))
                self.time_label = "Row Index (Date parsing failed)"
                self.time_is_datetime = False
        elif self.time_col == 't_ms':
            self.time_series = self.df['t_ms'] / 1000.0  # Convert ms to seconds
            self.time_label = "Elapsed Time (Seconds)"
            self.time_is_datetime = False
        else:
            self.time_series = np.arange(len(self.df))
            self.time_label = "Row Index"
            self.time_is_datetime = False
            
        # If active plot exists, regenerate it
        if self.checkbox_frame.get_selected():
            self.generate_plots()
            
    def on_search_changed(self, *args):
        term = self.search_var.get()
        selectable = [c for c in self.all_columns if c not in ('iso_time', 't_ms')]
        self.checkbox_frame.populate(selectable, term)
        
    def clear_all(self):
        self.checkbox_frame.clear_all()
        
    def select_all_filtered(self):
        self.checkbox_frame.select_all_filtered(self.search_var.get())
        
    def on_checkbox_clicked(self):
        if self.auto_update_var.get():
            self.delayed_replock()
            
    def delayed_replock(self):
        # Prevent spamming multiple updates inside a single event loop iteration
        self.root.after(50, self.generate_plots)
        
    def generate_plots(self):
        if self.df is None:
            return
            
        selected_cols = self.checkbox_frame.get_selected()
        if not selected_cols:
            self.clear_canvas()
            self.placeholder_lbl.pack(expand=True)
            self.set_status("No columns selected.")
            return
            
        self.clear_canvas()
        self.placeholder_lbl.pack_forget()
        
        layout = self.layout_var.get()
        num_plots = len(selected_cols)
        
        # Calculate dynamic figure height based on layout
        if layout == "subplots":
            fig_height = max(4.0, min(15.0, num_plots * 2.2))
        else:
            fig_height = 5.5
            
        # Create matplotlib Figure
        fig = Figure(figsize=(10, fig_height), dpi=100)
        fig.patch.set_facecolor('#1e293b') # slate 800
        
        try:
            if layout == "subplots":
                axes = fig.subplots(num_plots, 1, sharex=True)
                if num_plots == 1:
                    axes = [axes]
                    
                for idx, col in enumerate(selected_cols):
                    ax = axes[idx]
                    color = self.plot_colors[idx % len(self.plot_colors)]
                    
                    # Clean data for plotting (remove NaNs if any)
                    valid_mask = self.df[col].notna()
                    x_data = self.time_series[valid_mask]
                    y_data = self.df[col][valid_mask]
                    
                    ax.plot(x_data, y_data, color=color, linewidth=1.5, label=col)
                    ax.set_ylabel(col, color=color, fontweight='bold', fontsize=9)
                    ax.tick_params(colors='#94a3b8', labelsize=8)
                    ax.grid(True, linestyle='--', alpha=0.3, color='#475569')
                    ax.set_facecolor('#0f172a') # slate 900
                    
                    # Hide upper spines for cleaner look
                    ax.spines['top'].set_visible(False)
                    ax.spines['right'].set_visible(False)
                    ax.spines['left'].set_color('#475569')
                    ax.spines['bottom'].set_color('#475569')
                    
                    # Highlight axis label in graph
                    ax.legend(loc='upper right', framealpha=0.1, facecolor='#1e293b', edgecolor='none', labelcolor='#cbd5e1')
                    
                # Format X axis formatters for clock time
                if self.time_is_datetime:
                    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                axes[-1].set_xlabel(self.time_label, color='#94a3b8', fontweight='bold')
                
            else:
                # Overlay layout
                ax = fig.add_subplot(111)
                ax.set_facecolor('#0f172a')
                
                for idx, col in enumerate(selected_cols):
                    color = self.plot_colors[idx % len(self.plot_colors)]
                    valid_mask = self.df[col].notna()
                    x_data = self.time_series[valid_mask]
                    y_data = self.df[col][valid_mask]
                    
                    ax.plot(x_data, y_data, color=color, linewidth=1.5, label=col)
                    
                ax.tick_params(colors='#94a3b8', labelsize=9)
                ax.grid(True, linestyle='--', alpha=0.3, color='#475569')
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_color('#475569')
                ax.spines['bottom'].set_color('#475569')
                ax.legend(loc='upper right', framealpha=0.5, facecolor='#1e293b', edgecolor='none', labelcolor='#cbd5e1')
                
                if self.time_is_datetime:
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                ax.set_xlabel(self.time_label, color='#94a3b8', fontweight='bold')
                ax.set_title("Overlayed Telemetry Log Trends", color='#f8fafc', fontweight='bold', fontsize=12, pad=10)
                
            fig.tight_layout()
            
            # Embed Canvas in Tkinter frame
            self.canvas = FigureCanvasTkAgg(fig, master=self.plot_container)
            self.canvas.draw()
            
            # Toolbar
            self.toolbar = NavigationToolbar2Tk(self.canvas, self.plot_container, pack_toolbar=False)
            self.toolbar.update()
            
            # Styling the Toolbar for dark mode (subtle colors)
            self.toolbar.config(background='#1e293b')
            for child in self.toolbar.winfo_children():
                if isinstance(child, tk.Button):
                    child.config(background='#334155', foreground='#f8fafc', activebackground='#475569')
                else:
                    child.config(background='#1e293b')
                    
            self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)
            self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            
            self.set_status(f"Plotted {num_plots} parameters successfully.")
            
        except Exception as e:
            messagebox.showerror("Plotting Error", f"An error occurred while generating plots:\n{str(e)}")
            self.set_status("Plotting failed.")
            self.clear_canvas()
            self.placeholder_lbl.pack(expand=True)
            
    def clear_canvas(self):
        if self.canvas:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None
        if self.toolbar:
            self.toolbar.destroy()
            self.toolbar = None

def main():
    # Parse CLI or default path
    default_csv = r"C:\Users\varad\Downloads\parallax_log_2026-06-18T11-07-26.csv"
    if len(sys.argv) > 1:
        default_csv = sys.argv[1]
        
    root = tk.Tk()
    
    # Simple dark title bar styling on Windows if supported, else normal title
    try:
        import ctypes
        dwmapi = ctypes.windll.dwmapi
        # Set dark title bar (attribute 20)
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark_mode = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            ctypes.windll.user32.GetActiveWindow(),
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark_mode),
            ctypes.sizeof(dark_mode)
        )
    except Exception:
        pass
        
    app = ParallaxPlotterApp(root, default_csv)
    root.mainloop()

if __name__ == "__main__":
    main()
