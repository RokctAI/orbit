# Copyright (c) 2026, Rokct Intelligence (pty) Ltd.
# For license information, please see license.txt

import os
import sys
import json
import socket
import threading
import time
import getpass
import tkinter as tk
from tkinter import messagebox
from tkinter import filedialog
from http.server import BaseHTTPRequestHandler, HTTPServer
import psutil

# Optional tiktoken import for token calculation
try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

# Path to Orbit Config
CONFIG_DIR = os.path.expanduser("~/.orbit")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
THEME_FILE = os.path.join(CONFIG_DIR, "widget_theme.json")

ACTIVE_WIDGET_INSTANCE = None

class OrbitHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging request info to console to keep it clean
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/ping':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "app": "orbit"}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/report':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                global ACTIVE_WIDGET_INSTANCE
                if ACTIVE_WIDGET_INSTANCE:
                    ACTIVE_WIDGET_INSTANCE.handle_chrome_data(data)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()


def load_baseline_snapshot() -> dict:
    baseline_file = os.path.join(CONFIG_DIR, "baseline_snapshot.json")
    if os.path.isfile(baseline_file):
        try:
            with open(baseline_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_baseline_snapshot(snapshot: dict):
    baseline_file = os.path.join(CONFIG_DIR, "baseline_snapshot.json")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        with open(baseline_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception:
        pass


def load_orbit_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_orbit_config(data: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_todos() -> list:
    todo_file = os.path.join(CONFIG_DIR, "widget_todos.json")
    if os.path.isfile(todo_file):
        try:
            with open(todo_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_todos(todos: list):
    todo_file = os.path.join(CONFIG_DIR, "widget_todos.json")
    try:
        with open(todo_file, "w") as f:
            json.dump(todos, f, indent=2)
    except Exception:
        pass


def load_widget_theme() -> dict:
    default_theme = {
        "bg_color": "#181825",
        "fg_color": "#cdd6f4",
        "accent_color": "#89b4fa",
        "online_color": "#a6e3a1",
        "offline_color": "#f38ba8",
        "hover_color": "#313244",
        "width": 260,
        "height": 36,
        "refresh_interval_seconds": 30
    }
    
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.isfile(THEME_FILE):
        try:
            with open(THEME_FILE, "w") as f:
                json.dump(default_theme, f, indent=2)
        except Exception:
            pass
        return default_theme
        
    try:
        with open(THEME_FILE, "r") as f:
            user_theme = json.load(f)
            # Merge defaults for any missing keys
            for k, v in default_theme.items():
                if k not in user_theme:
                    user_theme[k] = v
            return user_theme
    except Exception:
        return default_theme


def to_superscript(text: str) -> str:
    m = {
        'A': 'ᴬ', 'B': 'ᴮ', 'C': 'ᶜ', 'D': 'ᴰ', 'E': 'ᴱ', 'F': 'ᶠ', 'G': 'ᴳ', 'H': 'ᴴ',
        'I': 'ᴵ', 'J': 'ᴶ', 'K': 'ᴷ', 'L': 'ᴸ', 'M': 'ᴹ', 'N': 'ᴺ', 'O': 'ᴼ', 'P': 'ᴾ',
        'Q': 'ᑫ', 'R': 'ᴿ', 'S': 'ˢ', 'T': 'ᵀ', 'U': 'ᵁ', 'V': 'ⱽ', 'W': 'ᵂ', 'X': 'ˣ',
        'Y': 'ʸ', 'Z': 'ᶻ'
    }
    return "".join(m.get(c.upper(), c) for c in text)





class ReminderDialog(tk.Toplevel):
    def __init__(self, parent, theme, current_val, on_save):
        super().__init__(parent)
        self.theme = theme
        self.on_save = on_save
        
        self.title("Set Reminder")
        self.configure(bg=self.theme["bg_color"])
        self.resizable(False, False)
        
        # Center dialog
        w, h = 280, 130
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        
        self.attributes("-topmost", True)
        self.transient(parent)
        self.grab_set()
        
        tk.Label(
            self, text="Set Reminder Date / Time",
            font=("Segoe UI", 9, "bold"), fg=self.theme["accent_color"], bg=self.theme["bg_color"]
        ).pack(pady=(12, 6))
        
        self.entry = tk.Entry(
            self, bg=self.theme["hover_color"], fg=self.theme["fg_color"],
            insertbackground=self.theme["fg_color"], bd=1, relief=tk.FLAT,
            font=("Segoe UI", 9)
        )
        self.entry.pack(fill=tk.X, padx=20, pady=4)
        if current_val:
            self.entry.insert(0, current_val)
        else:
            self.entry.insert(0, "e.g., Tomorrow 9am, or 12 Jun")
            self.entry.bind("<FocusIn>", lambda e: self.entry.delete(0, tk.END) if self.entry.get().startswith("e.g.") else None)
            
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self.submit())
        
        bf = tk.Frame(self, bg=self.theme["bg_color"])
        bf.pack(pady=10)
        
        tk.Button(
            bf, text="Save", font=("Segoe UI", 8, "bold"),
            bg=self.theme["accent_color"], fg=self.theme["bg_color"],
            activebackground=self.theme["accent_color"], activeforeground=self.theme["bg_color"],
            bd=0, padx=12, pady=3, relief=tk.FLAT, cursor="hand2", command=self.submit
        ).pack(side=tk.LEFT, padx=4)
        
        tk.Button(
            bf, text="Clear", font=("Segoe UI", 8),
            bg=self.theme["hover_color"], fg=self.theme["fg_color"],
            activebackground=self.theme["hover_color"], activeforeground=self.theme["fg_color"],
            bd=0, padx=12, pady=3, relief=tk.FLAT, cursor="hand2", command=self.clear_reminder
        ).pack(side=tk.LEFT, padx=4)

    def submit(self):
        val = self.entry.get().strip()
        if val.startswith("e.g."):
            val = ""
        self.on_save(val)
        self.destroy()
        
    def clear_reminder(self):
        self.on_save("")
        self.destroy()


class TokenStatusWidget:
    def __init__(self, root):
        self.root = root
        self.root.title("Orbit Status Bar")
        
        # Borderless window and topmost setup
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        # Register global instance
        global ACTIVE_WIDGET_INSTANCE
        ACTIVE_WIDGET_INSTANCE = self
        
        # Network monitoring state
        self.chrome_extension_connected = False
        self.chrome_data = {}
        self.net_expanded = False
        self.net_height = 220
        
        # Local changes tracking state
        self.pending_changes = []
        self.changes_expanded = False
        self.changes_height = 200
        
        # Get system username
        try:
            self.username = getpass.getuser()
        except Exception:
            self.username = "user"
            
        # Load custom theme / colors from JSON
        self.theme = load_widget_theme()
        
        self.bg_color = self.theme["bg_color"]
        self.fg_color = self.theme["fg_color"]
        self.accent_color = self.theme["accent_color"]
        self.online_color = self.theme["online_color"]
        self.offline_color = self.theme["offline_color"]
        self.hover_color = self.theme["hover_color"]
        
        self.root.configure(bg=self.bg_color)
        self.root.pack_propagate(False)
        
        # Dimensions
        self.width = self.theme["width"]
        self.height = self.theme["height"]
        self.refresh_interval = max(5, self.theme["refresh_interval_seconds"]) * 1000 # Minimum 5s
        
        # Snapping placement just above typical taskbar
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        # Bottom-right corner alignment
        start_x = screen_w - self.width - 25
        start_y = screen_h - self.height - 60
        
        # Ensure it works on macOS/Windows layout differences
        if sys.platform == "darwin":
            start_y = screen_h - self.height - 80  # Account for Mac Dock
            
        self.root.geometry(f"{self.width}x{self.height}+{start_x}+{start_y}")
        
        # State
        config = load_orbit_config()
        self.tokens_str = config.get("cached_tokens_str", "...")
        self.size_str = config.get("cached_size_str", "0 B")
        self.is_online = False
        self.is_updating = False
        
        # Load cached country code from config to prevent lookup delay
        self.country_code = config.get("country_code", "")
        
        self.logged_in = False
        self.is_compact = False
        self.collapse_timer = None
        self.todo_expanded = False
        self.todo_height = 180
        self._prev_todo_expanded = False
        self.login_expanded = False
        self._prev_login_expanded = False
        self.login_height = 140
        self.original_y = None # Track the position of the widget before expanding todo
        self._calculation_started_cycle = False
        self.is_transacting = False
        self.is_online = False
        
        # Build layout UI
        self.setup_ui()
        
        # Interaction events
        self.setup_events()
        
        # Start background HTTP server for Chrome Extension integration after 2s stabilization grace period
        self.root.after(2000, self.start_http_server)
        
        # Start initial async update after 500ms grace period
        self.root.after(500, self.refresh)
        
        # Start auto-update scheduler after initial delay
        self.root.after(500, self.schedule_auto_refresh)
        
        # Start blinking corner triangle loop after grace period
        self.blink_state = True
        self.root.after(500, self.run_blink_loop)

    def setup_ui(self):
        # Create container frame
        self.main_frame = tk.Frame(self.root, bg=self.bg_color, bd=0, highlightthickness=0)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=(0, 8), pady=0)
        
        # Left side: Pill badge for Orbit Logo & Status (filling full height, no internal padding)
        self.brand_badge = tk.Frame(self.main_frame, bg="#ff4600", bd=0, highlightthickness=0)
        self.brand_badge.pack(side=tk.LEFT, fill=tk.Y)
        
        # Status indicator line running across the top of the brand badge (16% badge height)
        self.status_line = tk.Frame(self.brand_badge, height=6, bg="#ffffff", bd=0, highlightthickness=0)
        self.status_line.place(x=0, y=0, relwidth=1.0)
        self.status_line.lift()
        
        # App branding name inside the badge (larger font size, pads left edge)
        self.app_label = tk.Label(
            self.brand_badge,
            text="Orbit",
            font=("Segoe UI", 14, "bold") if sys.platform == "win32" else ("SF Pro Text", 15, "bold"),
            fg="#ffffff",
            bg="#ff4600"
        )
        self.app_label.pack(side=tk.LEFT, padx=(12, 0))
        
        # Country code label inside the badge (superscript style, pads right edge)
        self.cc_label = tk.Label(
            self.brand_badge,
            text="",
            font=("Segoe UI", 8, "bold") if sys.platform == "win32" else ("SF Pro Text", 9, "bold"),
            fg="#ffffff",
            bg="#ff4600"
        )
        self.cc_label.pack(side=tk.LEFT, anchor=tk.N, pady=(4, 0), padx=(2, 12))
        
        # Next: Sleek Login Icon (Remix-style Key emoji)
        self.login_btn = tk.Label(
            self.main_frame,
            text="🔑",
            font=("Segoe UI", 11) if sys.platform == "win32" else ("SF Pro Text", 12),
            fg=self.accent_color,
            bg=self.bg_color,
            cursor="hand2"
        )
        
        # Next: Sleek Logout Icon (Remix-style Exit Door emoji)
        self.logout_btn = tk.Label(
            self.main_frame,
            text="🚪",
            font=("Segoe UI", 11) if sys.platform == "win32" else ("SF Pro Text", 12),
            fg=self.accent_color,
            bg=self.bg_color,
            cursor="hand2"
        )
        
        # Next: Set Workspace Icon (Remix-style Folder emoji)
        self.workspace_btn = tk.Label(
            self.main_frame,
            text="📁",
            font=("Segoe UI", 11) if sys.platform == "win32" else ("SF Pro Text", 12),
            fg=self.accent_color,
            bg=self.bg_color,
            cursor="hand2"
        )

        # Next: Network Monitor Icon (Globe emoji)
        self.net_btn = tk.Label(
            self.main_frame,
            text="🌐",
            font=("Segoe UI", 11) if sys.platform == "win32" else ("SF Pro Text", 12),
            fg=self.accent_color,
            bg=self.bg_color,
            cursor="hand2"
        )

        
        # Separator 1
        self.sep_label1 = tk.Label(
            self.main_frame,
            text="|",
            font=("Segoe UI", 9) if sys.platform == "win32" else ("SF Pro Text", 10),
            fg="#585b79",
            bg=self.bg_color
        )
        self.sep_label1.pack(side=tk.LEFT, padx=6)
        
        # Right: Tokens display
        self.token_label = tk.Label(
            self.main_frame,
            text="...",
            font=("Segoe UI", 9, "bold") if sys.platform == "win32" else ("SF Pro Text", 10, "bold"),
            fg=self.fg_color,
            bg=self.bg_color
        )
        self.token_label.pack(side=tk.LEFT)
        
        # Delta label to show (+X or -Y) in custom color
        self.delta_label = tk.Label(
            self.main_frame,
            text="",
            font=("Segoe UI", 8, "bold") if sys.platform == "win32" else ("SF Pro Text", 9, "bold"),
            fg="#fab387", # Sleek peach/orange color for local additions/removals
            bg=self.bg_color
        )
        self.delta_label.pack(side=tk.LEFT, padx=(4, 0))
        
        # Far Right: Close cross button
        self.close_btn = tk.Label(
            self.main_frame,
            text="×",
            font=("Segoe UI", 12, "bold") if sys.platform == "win32" else ("SF Pro Text", 13, "bold"),
            fg="#585b79",
            bg=self.bg_color,
            cursor="hand2"
        )
        self.close_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.close_btn.bind("<Button-1>", lambda e: self.root.destroy())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.configure(fg=self.offline_color))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.configure(fg="#585b79"))

    def setup_events(self):
        # Hover highlights and window dragging (excluding buttons from dragging)
        interactive_widgets = (
            self.root, self.main_frame, self.brand_badge, self.app_label, 
            self.sep_label1, self.token_label, self.status_line
        )
        for w in interactive_widgets:
            w.bind("<Enter>", self.on_enter)
            w.bind("<Leave>", self.on_leave)
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", self.drag)
            w.bind("<ButtonRelease-1>", self.end_drag)
            if w in (self.brand_badge, self.app_label, self.status_line, self.cc_label):
                w.bind("<Double-Button-1>", self.toggle_changes_panel)
            else:
                w.bind("<Double-Button-1>", self.toggle_compact)
            
        # Specific hover and click events for buttons
        self.login_btn.bind("<Button-1>", lambda e: self.toggle_login_expansion())
        self.login_btn.bind("<Enter>", lambda e: [self.on_enter(e), self.login_btn.configure(fg=self.fg_color)])
        self.login_btn.bind("<Leave>", lambda e: [self.on_leave(e), self.login_btn.configure(fg=self.accent_color)])
        
        self.logout_btn.bind("<Button-1>", lambda e: self.logout())
        self.logout_btn.bind("<Enter>", lambda e: [self.on_enter(e), self.logout_btn.configure(fg=self.fg_color)])
        self.logout_btn.bind("<Leave>", lambda e: [self.on_leave(e), self.logout_btn.configure(fg=self.accent_color)])
        
        self.workspace_btn.bind("<Button-1>", lambda e: self.select_workspace())
        self.workspace_btn.bind("<Enter>", lambda e: [self.on_enter(e), self.workspace_btn.configure(fg=self.fg_color)])
        self.workspace_btn.bind("<Leave>", lambda e: [self.on_leave(e), self.workspace_btn.configure(fg=self.accent_color)])
        
        self.net_btn.bind("<Button-1>", lambda e: self.toggle_net_panel())
        self.net_btn.bind("<Enter>", lambda e: [self.on_enter(e), self.net_btn.configure(fg=self.fg_color)])
        self.net_btn.bind("<Leave>", lambda e: [self.on_leave(e), self.net_btn.configure(fg=self.accent_color)])
        
        # Override token label click to handle calculation cancellation
        self.token_label.bind("<Button-1>", self.on_token_click)
             
        # Context menu
        self.menu = tk.Menu(self.root, tearoff=0, bg=self.hover_color, fg=self.fg_color, activebackground=self.accent_color, activeforeground=self.bg_color)
        self.update_menu()
        
        # Bind right click
        self.root.bind("<Button-3>", self.show_context_menu)
        if sys.platform == "darwin":
            self.root.bind("<Button-2>", self.show_context_menu)
  
    def on_enter(self, event):
        self.root.configure(bg=self.hover_color)
        self.main_frame.configure(bg=self.hover_color)
        self.login_btn.configure(bg=self.hover_color)
        self.logout_btn.configure(bg=self.hover_color)
        self.workspace_btn.configure(bg=self.hover_color)
        self.net_btn.configure(bg=self.hover_color)
        self.sep_label1.configure(bg=self.hover_color)
        self.token_label.configure(bg=self.hover_color)
        self.close_btn.configure(bg=self.hover_color)
        
        # Cancel auto-collapse timer and expand if compact
        if self.collapse_timer:
            self.root.after_cancel(self.collapse_timer)
            self.collapse_timer = None
        if self.is_compact:
            self.is_compact = False
            self.update_layout()
  
    def on_leave(self, event):
        # Prevent spurious leaves if the mouse pointer is still inside the window bounds
        try:
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery()
            wx = self.root.winfo_rootx()
            wy = self.root.winfo_rooty()
            ww = self.root.winfo_width()
            wh = self.root.winfo_height()
            if wx <= x <= wx + ww and wy <= y <= wy + wh:
                return  # Pointer is still within the window bounds, ignore
        except Exception:
            pass

        self.root.configure(bg=self.bg_color)
        self.main_frame.configure(bg=self.bg_color)
        self.login_btn.configure(bg=self.bg_color)
        self.logout_btn.configure(bg=self.bg_color)
        self.workspace_btn.configure(bg=self.bg_color)
        self.net_btn.configure(bg=self.bg_color)
        self.sep_label1.configure(bg=self.bg_color)
        self.token_label.configure(bg=self.bg_color)
        self.close_btn.configure(bg=self.bg_color)
        
        # Auto-collapse to compact mode disabled as requested
        pass



    def on_token_click(self, event):
        if self.is_updating:
            self.cancel_calculation = True
            self.token_label.configure(text="Canceling...")
        else:
            self.start_drag(event)

    def start_drag(self, event):
        self.drag_x = event.x
        self.drag_y = event.y
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root

    def drag(self, event):
        # Calculate coordinate delta and move window
        x = self.root.winfo_x() - self.drag_x + event.x
        y = self.root.winfo_y() - self.drag_y + event.y
        self.root.geometry(f"+{x}+{y}")

    def end_drag(self, event):
        dx = abs(event.x_root - getattr(self, "drag_start_x", event.x_root))
        dy = abs(event.y_root - getattr(self, "drag_start_y", event.y_root))
        if dx < 5 and dy < 5:
            if event.widget in (self.brand_badge, self.app_label, self.status_line, self.cc_label):
                if getattr(self, "pending_changes", []):
                    self.orbit_push()
                    return
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        curr_x = self.root.winfo_x()
        curr_y = self.root.winfo_y()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        
        # Snapping thresholds and margins
        margin_x = 25
        margin_y = 60
        if sys.platform == "darwin":
            margin_y = 80
            
        top_y = 15 if sys.platform != "darwin" else 40
        bottom_y = screen_h - h - margin_y
        left_x = margin_x
        right_x = screen_w - w - margin_x
        
        # Corner configurations and positions
        corners = {
            "top_left": (left_x, top_y),
            "top_right": (right_x, top_y),
            "bottom_left": (left_x, bottom_y),
            "bottom_right": (right_x, bottom_y)
        }
        
        # Check if close to any corner (Euclidean distance threshold of 180px)
        corner_threshold = 180
        closest_corner = None
        min_dist = float("inf")
        
        for name, (cx, cy) in corners.items():
            dist = ((curr_x - cx) ** 2 + (curr_y - cy) ** 2) ** 0.5
            if dist < min_dist:
                min_dist = dist
                closest_corner = (cx, cy)
                
        snap_x = curr_x
        snap_y = curr_y
        
        if closest_corner and min_dist < corner_threshold:
            snap_x, snap_y = closest_corner
        else:
            # Fall back to edge snapping with smaller threshold (60px)
            edge_threshold = 60
            # Snap horizontally
            if curr_x < edge_threshold:
                snap_x = left_x
            elif (curr_x + w) > (screen_w - edge_threshold):
                snap_x = right_x
                
            # Snap vertically
            if curr_y < edge_threshold:
                snap_y = top_y
            elif (curr_y + h) > (screen_h - edge_threshold - 40):
                snap_y = bottom_y
                
        if snap_x != curr_x or snap_y != curr_y:
            self.root.geometry(f"+{snap_x}+{snap_y}")


    def show_context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def schedule_auto_refresh(self):
        # Auto refresh using interval from theme config
        self.root.after(self.refresh_interval, self.refresh_and_reschedule)

    def refresh_and_reschedule(self):
        self.refresh()
        self.root.after(self.refresh_interval, self.refresh_and_reschedule)


    def refresh(self):
        if self.is_updating:
            return
        self.is_updating = True
        self.cancel_calculation = False
        
        # Start worker thread to do heavy operations asynchronously
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        # Check login status
        config = load_orbit_config()
        self.logged_in = bool(config.get("token"))
        
        # Count Tokens and Size of current workspace
        workspace_dir = config.get("workspace")
        if not workspace_dir or not os.path.isdir(workspace_dir):
            # Fallback to repository root
            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        def progress_callback(tokens, size_bytes, is_done):
            # Check if calculation was canceled
            was_canceled = getattr(self, "cancel_calculation", False)
            
            # Format tokens neatly
            if was_canceled:
                tokens_str = "Canceled"
            elif tokens >= 1_000_000_000:
                tokens_str = f"{round(tokens / 1_000_000_000)}G"
            elif tokens >= 1_000_000:
                tokens_str = f"{round(tokens / 1_000_000)}M"
            elif tokens >= 1_000:
                tokens_str = f"{round(tokens / 1_000)}K"
            else:
                tokens_str = str(tokens)
                
            # Format size neatly
            if size_bytes >= 1_073_741_824:
                size_str = f"{round(size_bytes / 1_073_741_824)} GB"
            elif size_bytes >= 1_048_576:
                size_str = f"{round(size_bytes / 1_048_576)} MB"
            elif size_bytes >= 1024:
                size_str = f"{round(size_bytes / 1024)} KB"
            else:
                size_str = f"{size_bytes} B"
                
            # Schedule GUI updates on the main thread safely
            self.root.after(0, self._apply_updates, tokens_str, size_str, is_done or was_canceled)
            
        self._calculate_codebase_tokens(workspace_dir, progress_callback)
        try:
            self._detect_changes(workspace_dir)
        except Exception:
            pass

    def _apply_updates(self, tokens_str, size_str, is_done=True):
        self.tokens_str = tokens_str
        self.size_str = size_str
        
        # Cache token counts and sizes to configuration to persist across widget launches
        config = load_orbit_config()
        config["cached_tokens_str"] = tokens_str
        config["cached_size_str"] = size_str
        save_orbit_config(config)
        
        self.update_layout(is_done=is_done)

    def update_layout(self, is_done=True):
            
        # Update status line color based on transaction state
        if getattr(self, "is_transacting", False):
            self.status_line.configure(bg="#13F300")
        else:
            self.status_line.configure(bg="#ff4600")
        
        # Clear packing for all dynamically ordered widgets to preserve strict sorting
        self.brand_badge.pack_forget()
        self.login_btn.pack_forget()
        self.logout_btn.pack_forget()
        self.workspace_btn.pack_forget()
        self.net_btn.pack_forget()
        self.sep_label1.pack_forget()
        self.token_label.pack_forget()
        
        config = load_orbit_config()
        workspace_set = bool(config.get("workspace"))
        
        # Always pack brand badge first
        self.brand_badge.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # Update country code label
        self.cc_label.pack_forget()
        if self.country_code:
            self.cc_label.configure(text=self.country_code.upper())
            self.cc_label.pack(side=tk.LEFT, anchor=tk.N, pady=(4, 0))
            
        if getattr(self, "pending_changes", []):
            brand = "Push"
            badge_bg = "#228B22"  # Forest Green
        else:
            brand = "Orbit"
            badge_bg = "#ff4600"  # Orange
            
        self.brand_badge.configure(bg=badge_bg)
        self.app_label.configure(bg=badge_bg)
        self.cc_label.configure(bg=badge_bg)
        
        # Fetch remote metadata tokens to calculate additions/removals delta
        remote_tokens = config.get("gravity_remote_tokens", 0) # Default to 0 if not loaded from Gravity fetch yet
        
        # Strip string suffix to get local token number approximation
        try:
            local_tokens = 0
            if "G" in self.tokens_str:
                local_tokens = int(float(self.tokens_str.replace("G", "")) * 1_000_000_000)
            elif "M" in self.tokens_str:
                local_tokens = int(float(self.tokens_str.replace("M", "")) * 1_000_000)
            elif "K" in self.tokens_str:
                local_tokens = int(float(self.tokens_str.replace("K", "")) * 1_000)
            elif "k" in self.tokens_str:
                local_tokens = int(float(self.tokens_str.replace("k", "")) * 1_000)
            else:
                local_tokens = int(self.tokens_str.replace("...", "0").replace("Canceled", "0"))
        except Exception:
            local_tokens = 0

        # Calculate difference (local tokens compared to remote gravity metadata baseline)
        delta_tokens = local_tokens - remote_tokens if remote_tokens > 0 else 0
        delta_str = ""
        delta_color = "#fab387" # Standard peach
        if delta_tokens > 0:
            if delta_tokens >= 1_000_000_000:
                delta_str = f"+{round(delta_tokens / 1_000_000_000)}G"
            elif delta_tokens >= 1_000_000:
                delta_str = f"+{round(delta_tokens / 1_000_000)}M"
            elif delta_tokens >= 1_000:
                delta_str = f"+{round(delta_tokens / 1_000)}K"
            else:
                delta_str = f"+{delta_tokens}"
            delta_color = "#a6e3a1" # Vibrant green for additions
        elif delta_tokens < 0:
            abs_delta = abs(delta_tokens)
            if abs_delta >= 1_000_000_000:
                delta_str = f"-{round(abs_delta / 1_000_000_000)}G"
            elif abs_delta >= 1_000_000:
                delta_str = f"-{round(abs_delta / 1_000_000)}M"
            elif abs_delta >= 1_000:
                delta_str = f"-{round(abs_delta / 1_000)}K"
            else:
                delta_str = f"-{abs_delta}"
            delta_color = "#f38ba8" # Vibrant red for removals
 
        # Render display: show remote baseline tokens (Gravity metadata baseline) if it exists, otherwise local tokens count
        base_display = ""
        if remote_tokens > 0:
            if remote_tokens >= 1_000_000_000:
                base_display = f"{round(remote_tokens / 1_000_000_000)}G"
            elif remote_tokens >= 1_000_000:
                base_display = f"{round(remote_tokens / 1_000_000)}M"
            elif remote_tokens >= 1_000:
                base_display = f"{round(remote_tokens / 1_000)}K"
            else:
                base_display = str(remote_tokens)
        else:
            base_display = self.tokens_str

        # Clear delta label packing in update_layout forget block
        self.delta_label.pack_forget()

        if self.is_compact:
            # Compact Layout
            self.app_label.configure(text=brand)
            self.sep_label1.pack_forget()
            self.token_label.configure(text=f"{base_display} ({self.size_str.replace(' ', '')})")
            self.token_label.pack(side=tk.LEFT)
            if delta_str:
                self.delta_label.configure(text=delta_str, fg=delta_color)
                self.delta_label.pack(side=tk.LEFT, padx=(4, 0))
        else:
            # Expanded Layout
            # Always show workspace button to allow changing workspace at any time
            self.workspace_btn.pack(side=tk.LEFT, padx=(0, 4))

            if self.logged_in:
                self.app_label.configure(text=f"{brand} ({self.username})")
                self.logout_btn.pack(side=tk.LEFT, padx=(0, 4))
            else:
                self.app_label.configure(text=brand)
                if workspace_set:
                    self.login_btn.pack(side=tk.LEFT, padx=(0, 4))
            
            # Pack net_btn if chrome extension has connected
            if getattr(self, "chrome_extension_connected", False):
                self.net_btn.pack(side=tk.LEFT, padx=(0, 4))
                if self.net_expanded:
                    self.net_btn.configure(fg=self.accent_color)
                else:
                    self.net_btn.configure(fg=self.fg_color)
                    
            # Repack separator and display
            self.sep_label1.pack(side=tk.LEFT, padx=6)
            self.token_label.configure(text=f"{base_display} ({self.size_str})")
            self.token_label.pack(side=tk.LEFT)
            if delta_str:
                self.delta_label.configure(text=delta_str, fg=delta_color)
                self.delta_label.pack(side=tk.LEFT, padx=(4, 0))
            
        # Determine stable width depending on state (login/todo/net/changes expansion vs normal/compact)
        if self.login_expanded or self.todo_expanded or self.net_expanded or self.changes_expanded:
            new_width = 300
        else:
            new_width = 260
            
        # Re-pack self.main_frame and set heights depending on expanded todo state
        self.main_frame.pack_forget()
        if self.todo_expanded or self.login_expanded or self.net_expanded or self.changes_expanded:
            self.main_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=(0, 8), pady=0)
        else:
            self.main_frame.pack(fill=tk.BOTH, expand=True, padx=(0, 8), pady=0)
            
        self.main_frame.configure(height=self.height, width=new_width)
        self.main_frame.pack_propagate(False)
            
        if self.todo_expanded:
            target_height = self.height + self.todo_height
        elif self.login_expanded:
            target_height = self.height + self.login_height
        elif self.net_expanded:
            target_height = self.height + self.net_height
        elif self.changes_expanded:
            target_height = self.height + self.changes_height
        else:
            target_height = self.height
        
        # Preserve position coordinates while adapting window geometry (upwards/downwards expansion)
        curr_x = self.root.winfo_x()
        curr_y = self.root.winfo_y()
        old_width = self.root.winfo_width()
        old_height = self.root.winfo_height()
        
        # Shift Y coordinate correctly depending on screen half (expand upwards if on the bottom half, downwards if on the top half)
        new_y = curr_y
        if old_height > 1:
            screen_h = self.root.winfo_screenheight()
            if curr_y + (old_height / 2) > (screen_h / 2):
                new_y = curr_y - (target_height - old_height)
            else:
                new_y = curr_y
                
        # Adjust X based on screen half (anchor right if on the right half, left if on the left half)
        new_x = curr_x
        if old_width > 1:
            screen_w = self.root.winfo_screenwidth()
            if curr_x + (old_width / 2) > (screen_w / 2):
                new_x = curr_x - (new_width - old_width)
            else:
                new_x = curr_x
            
        self.root.geometry(f"{new_width}x{target_height}+{new_x}+{new_y}")
        
        # Dynamically adjust menu depending on login state
        self.update_menu()
        self.is_updating = False

    def update_menu(self):
        self.menu.delete(0, tk.END)
        self.menu.add_command(label="Force Refresh", command=self.refresh)
        
        config = load_orbit_config()
        if not config.get("workspace"):
            self.menu.add_command(label="Set Workspace Directory...", command=self.select_workspace)
        else:
            self.menu.add_command(label="Change Workspace...", command=self.select_workspace)
            self.menu.add_command(label="Clear Workspace", command=self.clear_workspace)
            self.menu.add_command(label="Toggle Tasks List", command=self.toggle_todo_list)
            self.menu.add_command(label="Toggle Changes Panel", command=self.toggle_changes_panel)
            
        if config.get("token"):
            self.menu.add_command(label="Logout", command=self.logout)
        elif config.get("workspace"):
            self.menu.add_command(label="Login", command=self.toggle_login_expansion)
            
        self.menu.add_separator()
        self.menu.add_command(label="Exit Widget", command=self.root.destroy)

    def setup_login_ui(self):
        self.login_frame = tk.Frame(self.root, bg=self.bg_color, bd=0)
        
        # Header title
        header_frame = tk.Frame(self.login_frame, bg=self.bg_color)
        header_frame.pack(fill=tk.X, padx=10, pady=(8, 2))
        
        tk.Label(
            header_frame, text="Connect to Gravity",
            font=("Segoe UI", 9, "bold") if sys.platform == "win32" else ("SF Pro Text", 10, "bold"),
            fg=self.accent_color, bg=self.bg_color
        ).pack(side=tk.LEFT)
        
        # Form fields container
        form_frame = tk.Frame(self.login_frame, bg=self.bg_color)
        form_frame.pack(fill=tk.X, padx=10, pady=2)
        
        # Email / Username Row
        ef = tk.Frame(form_frame, bg=self.bg_color)
        ef.pack(fill=tk.X, pady=2)
        tk.Label(ef, text="Email / Usr:", font=("Segoe UI", 9), fg=self.fg_color, bg=self.bg_color, width=10, anchor="w").pack(side=tk.LEFT)
        self.email_entry = tk.Entry(ef, bg=self.hover_color, fg=self.fg_color, insertbackground=self.fg_color, bd=1, relief=tk.FLAT)
        self.email_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        config = load_orbit_config()
        if config.get("email"):
            self.email_entry.insert(0, config["email"])
            
        # Password Row
        pf = tk.Frame(form_frame, bg=self.bg_color)
        pf.pack(fill=tk.X, pady=2)
        tk.Label(pf, text="Password:", font=("Segoe UI", 9), fg=self.fg_color, bg=self.bg_color, width=10, anchor="w").pack(side=tk.LEFT)
        self.password_entry = tk.Entry(pf, show="*", bg=self.hover_color, fg=self.fg_color, insertbackground=self.theme["fg_color"], bd=1, relief=tk.FLAT)
        self.password_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.password_entry.bind("<Return>", lambda e: self.submit_login())
        
        # Buttons Row
        bf = tk.Frame(self.login_frame, bg=self.bg_color)
        bf.pack(fill=tk.X, padx=10, pady=(6, 8))
        
        btn_conn = tk.Button(
            bf, text="Connect", font=("Segoe UI", 8, "bold"),
            bg=self.accent_color, fg=self.bg_color,
            activebackground=self.accent_color, activeforeground=self.bg_color,
            bd=0, padx=12, pady=3, relief=tk.FLAT, cursor="hand2", command=self.submit_login
        )
        btn_conn.pack(side=tk.RIGHT, padx=4)
        
        btn_cancel = tk.Button(
            bf, text="Cancel", font=("Segoe UI", 8),
            bg=self.hover_color, fg=self.fg_color,
            activebackground=self.hover_color, activeforeground=self.fg_color,
            bd=0, padx=12, pady=3, relief=tk.FLAT, cursor="hand2", command=self.toggle_login_expansion
        )
        btn_cancel.pack(side=tk.RIGHT, padx=4)

    def submit_login(self):
        server = "https://platform.rokct.ai"
        email = self.email_entry.get().strip()
        password = self.password_entry.get().strip()
        
        if not email or not password:
            messagebox.showerror("Error", "All fields are required.", parent=self.root)
            return
            
        self.set_transacting(True)
        # 1. Perform login on Control site
        login_url = f"{server}/api/method/rcore.api.auth.login.login"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        login_payload = json.dumps({"usr": email, "pwd": password}).encode("utf-8")
        
        import urllib.request
        import urllib.error
        
        try:
            req = urllib.request.Request(login_url, data=login_payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode())
                
            if not res_data.get("status") or "data" not in res_data:
                self.set_transacting(False)
                messagebox.showerror("Login Failed", res_data.get("message", "Invalid response from Gravity"), parent=self.root)
                return
                
            access_token = res_data["data"]["access_token"]
            
        except urllib.error.HTTPError as e:
            self.set_transacting(False)
            try:
                err_data = json.loads(e.read().decode())
                msg = err_data.get("message", e.reason)
            except Exception:
                msg = e.reason
            messagebox.showerror("Login Error", f"Gravity login failed: {msg}", parent=self.root)
            return
        except Exception as e:
            self.set_transacting(False)
            messagebox.showerror("Connection Error", f"Failed to connect to Gravity: {str(e)}", parent=self.root)
            return

        # 2. Perform Handshake on Gravity via the reverse proxy (/gravity/v1/handshake)
        handshake_url = f"{server}/gravity/v1/handshake"
        device_id = f"{getpass.getuser()}_{socket.gethostname()}"
        handshake_payload = json.dumps({
            "access_token": access_token,
            "device_id": device_id
        }).encode("utf-8")
        
        try:
            req = urllib.request.Request(handshake_url, data=handshake_payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode())
                
            if not res_data.get("status") or "gravity_token" not in res_data:
                self.set_transacting(False)
                messagebox.showerror("Handshake Failed", "Invalid handshake response from Gravity", parent=self.root)
                return
                
            gravity_token = res_data["gravity_token"]
            
        except urllib.error.HTTPError as e:
            self.set_transacting(False)
            try:
                err_data = json.loads(e.read().decode())
                msg = err_data.get("detail", e.reason)
            except Exception:
                msg = e.reason
            messagebox.showerror("Handshake Error", f"Gravity handshake failed: {msg}", parent=self.root)
            return
        except Exception as e:
            self.set_transacting(False)
            messagebox.showerror("Handshake Connection Error", f"Failed to connect to Gravity: {str(e)}", parent=self.root)
            return

        # 3. Store Gravity session token and server
        config = load_orbit_config()
        config["server"] = server
        config["email"] = email
        config["token"] = gravity_token
        config["control_token"] = access_token
        save_orbit_config(config)
        
        self.set_transacting(False)
        self.toggle_login_expansion()
        self.refresh()

    def toggle_login_expansion(self, event=None):
        self.login_expanded = not self.login_expanded
        
        if self.collapse_timer:
            self.root.after_cancel(self.collapse_timer)
            self.collapse_timer = None
            
        if self.login_expanded:
            self.is_compact = False
            # Collapse todo list if it is expanded
            if self.todo_expanded:
                self.toggle_todo_list()
                
            if not hasattr(self, "login_frame"):
                self.setup_login_ui()
                
            self.login_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self.email_entry.focus_set()
        else:
            if hasattr(self, "login_frame"):
                self.login_frame.pack_forget()
                
        self.update_layout()
        return "break"

    def select_workspace(self):
        folder = filedialog.askdirectory(title="Select Orbit Workspace", parent=self.root)
        if folder:
            config = load_orbit_config()
            config["workspace"] = folder

            save_orbit_config(config)
            self.refresh()

    def clear_workspace(self):
        config = load_orbit_config()
        if "workspace" in config:
            del config["workspace"]
        save_orbit_config(config)
        self.refresh()

    def toggle_compact(self, event=None):
        self.is_compact = not self.is_compact
        if self.is_compact:
            if self.todo_expanded:
                self.toggle_todo_list()
            if self.login_expanded:
                self.toggle_login_expansion()
        self.update_layout()
        return "break"

    def auto_collapse(self):
        self.is_compact = True
        if self.todo_expanded:
            self.toggle_todo_list()
        if self.login_expanded:
            self.toggle_login_expansion()
        self.update_layout()

    def set_transacting(self, active: bool):
        self.is_transacting = active
        if active:
            try:
                self.status_line.configure(bg="#13F300")
            except Exception:
                pass
        else:
            try:
                self.status_line.configure(bg="#ff4600")
            except Exception:
                pass

    def run_blink_loop(self):
        if getattr(self, "is_transacting", False):
            self.blink_state = not self.blink_state
            # Alternate between green and badge background
            color = "#13F300" if self.blink_state else "#ff4600"
            try:
                self.status_line.configure(bg=color)
            except Exception:
                return
        else:
            try:
                self.status_line.configure(bg="#ff4600")
            except Exception:
                return
        self.root.after(400, self.run_blink_loop)

    def toggle_todo_list(self, event=None):
        self.todo_expanded = not self.todo_expanded
        
        if self.collapse_timer:
            self.root.after_cancel(self.collapse_timer)
            self.collapse_timer = None
            
        if self.todo_expanded:
            self.is_compact = False
            # Create the Todo Frame if it doesn't exist yet
            if not hasattr(self, "todo_frame"):
                self.setup_todo_ui()
                
            # Pack the Todo Frame at the top of the window
            self.todo_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self.refresh_todo_list()
        else:
            if hasattr(self, "todo_frame"):
                self.todo_frame.pack_forget()
                
        self.update_layout()
        return "break"

    def setup_todo_ui(self):
        self.todo_frame = tk.Frame(self.root, bg=self.bg_color, bd=0)
        
        # Header title for tasks
        header_frame = tk.Frame(self.todo_frame, bg=self.bg_color)
        header_frame.pack(fill=tk.X, padx=10, pady=(8, 2))
        
        tk.Label(
            header_frame, text="Orbit Tasks",
            font=("Segoe UI", 9, "bold") if sys.platform == "win32" else ("SF Pro Text", 10, "bold"),
            fg=self.accent_color, bg=self.bg_color
        ).pack(side=tk.LEFT)
        
        tk.Label(
            header_frame, text="Click to Toggle • Double-click for Reminder",
            font=("Segoe UI", 7) if sys.platform == "win32" else ("SF Pro Text", 8),
            fg="#585b79", bg=self.bg_color
        ).pack(side=tk.RIGHT)
        
        # Task Input Frame - Packed at side=tk.BOTTOM FIRST to ensure it is never hidden by canvas expand
        input_frame = tk.Frame(self.todo_frame, bg=self.bg_color)
        input_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(2, 8))
        
        self.todo_entry = tk.Entry(
            input_frame,
            bg=self.hover_color,
            fg=self.fg_color,
            insertbackground=self.fg_color,
            font=("Segoe UI", 9) if sys.platform == "win32" else ("SF Pro Text", 10),
            bd=1,
            relief=tk.FLAT
        )
        self.todo_entry.insert(0, "Add a task...")
        self.todo_entry.bind("<FocusIn>", lambda e: self._clear_placeholder(self.todo_entry, "Add a task..."))
        self.todo_entry.bind("<FocusOut>", lambda e: self._add_placeholder(self.todo_entry, "Add a task..."))
        self.todo_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.todo_entry.bind("<Return>", lambda e: self.add_todo_item())
        
        # Plus Button (Circle button style)
        add_btn = tk.Label(
            input_frame,
            text="+",
            font=("Segoe UI", 9, "bold"),
            fg=self.bg_color,
            bg=self.accent_color,
            cursor="hand2",
            padx=7,
            pady=2,
            bd=0
        )
        add_btn.pack(side=tk.RIGHT)
        add_btn.bind("<Button-1>", lambda e: self.add_todo_item())
        
        # Task Container Canvas (Scrollable) - Packed after input_frame
        self.todo_canvas = tk.Canvas(self.todo_frame, bg=self.bg_color, bd=0, highlightthickness=0)
        self.todo_scrollbar = tk.Scrollbar(self.todo_frame, orient="vertical", command=self.todo_canvas.yview, width=6, bd=0, elementborderwidth=0)
        self.todo_list_frame = tk.Frame(self.todo_canvas, bg=self.bg_color)
        
        self.todo_canvas.create_window((0, 0), window=self.todo_list_frame, anchor="nw", tags="self.todo_list_frame")
        self.todo_canvas.configure(yscrollcommand=self.todo_scrollbar.set)
        
        self.todo_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=(10, 0), pady=2)
        self.todo_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 4))
        
        # Bind canvas resize to match list frame width
        self.todo_canvas.bind("<Configure>", lambda e: self.todo_canvas.itemconfig("self.todo_list_frame", width=e.width))
        
        # Update scrollregion on configure
        self.todo_list_frame.bind("<Configure>", lambda e: self.todo_canvas.configure(scrollregion=self.todo_canvas.bbox("all")))
        
        # Mousewheel scroll support
        def _on_mousewheel(event):
            self.todo_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.todo_canvas.bind("<Enter>", lambda e: self.todo_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.todo_canvas.bind("<Leave>", lambda e: self.todo_canvas.unbind_all("<MouseWheel>"))

    def _clear_placeholder(self, entry, placeholder):
        if entry.get() == placeholder:
            entry.delete(0, tk.END)

    def _add_placeholder(self, entry, placeholder):
        if not entry.get().strip():
            entry.insert(0, placeholder)

    def refresh_todo_list(self):
        # Clear existing rows
        for widget in self.todo_list_frame.winfo_children():
            widget.destroy()
            
        todos = load_todos()
        for idx, t in enumerate(todos):
            # Row container (Premium Card styling)
            row = tk.Frame(self.todo_list_frame, bg=self.hover_color, bd=0)
            row.pack(fill=tk.X, pady=2, padx=(0, 4))
            
            # Single click toggles status. Double click opens the Set Reminder dialog directly.
            row.bind("<Button-1>", lambda e, i=idx: [self.toggle_todo_item(i), "break"][1])
            row.bind("<Double-Button-1>", lambda e, i=idx: [self.set_reminder(i), "break"][1])
            
            # Checkbox indicator (☑️ for checked, ⚪ for unchecked)
            status_char = "☑️" if t.get("done") else "⚪"
            status_fg = self.accent_color if t.get("done") else self.fg_color
            
            chk = tk.Label(
                row, text=status_char, font=("Segoe UI", 10), 
                fg=status_fg, bg=self.hover_color, cursor="hand2"
            )
            chk.pack(side=tk.LEFT, padx=(8, 6))
            chk.bind("<Button-1>", lambda e, i=idx: [self.toggle_todo_item(i), "break"][1])
            chk.bind("<Double-Button-1>", lambda e, i=idx: [self.set_reminder(i), "break"][1])
            
            # Text label
            text_fg = "#585b79" if t.get("done") else self.fg_color
            text_font = ("Segoe UI", 9, "overstrike") if t.get("done") else ("Segoe UI", 9)
            lbl = tk.Label(
                row, text=t["text"], font=text_font, fg=text_fg, 
                bg=self.hover_color, anchor="w", justify=tk.LEFT, cursor="hand2"
            )
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4)
            lbl.bind("<Button-1>", lambda e, i=idx: [self.toggle_todo_item(i), "break"][1])
            lbl.bind("<Double-Button-1>", lambda e, i=idx: [self.set_reminder(i), "break"][1])
            
            # Yellow Bell Icon & Reminder Badge if present
            if t.get("due"):
                due_lbl = tk.Label(
                    row, text=f"🔔 {t['due']}", font=("Segoe UI", 8),
                    fg="#ffd700", bg=self.hover_color, cursor="hand2"
                )
                due_lbl.pack(side=tk.RIGHT, padx=6)
                due_lbl.bind("<Button-1>", lambda e, i=idx: [self.set_reminder(i), "break"][1])
                due_lbl.bind("<Double-Button-1>", lambda e, i=idx: [self.set_reminder(i), "break"][1])
                
            # Styled Delete cross on hover
            del_btn = tk.Label(
                row, text="×", font=("Segoe UI", 11, "bold"), 
                fg="#585b79", bg=self.hover_color, cursor="hand2"
            )
            del_btn.pack(side=tk.RIGHT, padx=6)
            
            # Bind hover coloring for delete button
            del_btn.bind("<Enter>", lambda e, btn=del_btn: btn.configure(fg=self.offline_color))
            del_btn.bind("<Leave>", lambda e, btn=del_btn: btn.configure(fg="#585b79"))
            del_btn.bind("<Button-1>", lambda e, i=idx: self.delete_todo_item(i))

    def add_todo_item(self):
        text = self.todo_entry.get().strip()
        
        if text == "Add a task..." or not text:
            return
            
        todos = load_todos()
        todos.append({"text": text, "done": False, "due": ""})
        save_todos(todos)
        
        # Clear input field and restore placeholder if unfocused
        self.todo_entry.delete(0, tk.END)
        self.todo_entry.insert(0, "Add a task...")
        
        # Shift focus away so placeholders show
        self.root.focus_set()
        
        self.refresh_todo_list()

    def set_reminder(self, index):
        todos = load_todos()
        if 0 <= index < len(todos):
            current_val = todos[index].get("due", "")
            def on_save(new_due):
                todos[index]["due"] = new_due
                save_todos(todos)
                self.refresh_todo_list()
            ReminderDialog(self.root, self.theme, current_val, on_save)

    def toggle_todo_item(self, index):
        todos = load_todos()
        if 0 <= index < len(todos):
            todos[index]["done"] = not todos[index]["done"]
            save_todos(todos)
            self.refresh_todo_list()

    def delete_todo_item(self, index):
        todos = load_todos()
        if 0 <= index < len(todos):
            del todos[index]
            save_todos(todos)
            self.refresh_todo_list()

    def logout(self):
        config = load_orbit_config()
        if "token" in config:
            del config["token"]
        save_orbit_config(config)
        self.country_code = ""
        self.refresh()



    def _check_connection(self) -> bool:
        # Check if Orbit config specifies a server to ping
        config = load_orbit_config()
        server = config.get("server")
        
        if server:
            # Try parsing hostname from server URL
            try:
                from urllib.parse import urlparse
                parsed = urlparse(server)
                host = parsed.hostname or server
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                
                # Check connection to Gravity server specifically
                with socket.create_connection((host, port), timeout=2.0):
                    return True
            except Exception:
                pass
                
        # General internet ping fallback
        for host in ["1.1.1.1", "8.8.8.8", "github.com"]:
            try:
                with socket.create_connection((host, 53 if "1" in host or "8" in host else 443), timeout=2.0):
                    return True
            except Exception:
                continue
        return False

    def _calculate_codebase_tokens(self, workspace_path: str, update_callback) -> tuple[int, int]:
        total_tokens = 0
        total_bytes = 0
        file_count = 0
        
        # Ignored directories
        ignore_dirs = {
            ".git", ".rokct", ".venv", "venv", "env", "__pycache__", 
            "node_modules", "dist", "build", ".next", ".cache", "out",
            "target", "bin", "obj", "ios", "android", ".expo", ".output",
            "logs", "temp", "tmp", "coverage"
        }
        
        # Allowed file extensions
        allowed_extensions = {
            ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", 
            ".json", ".md", ".toml", ".yaml", ".yml", ".txt", ".ini"
        }
        
        # Load tiktoken encoding if available
        encoding = None
        if HAS_TIKTOKEN:
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                pass
                
        # Load file tokens cache
        cache_file = os.path.join(CONFIG_DIR, "file_tokens_cache.json")
        file_cache = {}
        if os.path.isfile(cache_file):
            try:
                with open(cache_file, "r") as f:
                    file_cache = json.load(f)
            except Exception:
                pass
                
        new_file_cache = {}
        
        # Scheduling: Calculate for 5 minutes, then sleep for 30 minutes
        last_break_time = time.time()
        
        try:
            for root_dir, dirs, files in os.walk(workspace_path):
                if getattr(self, "cancel_calculation", False):
                    break
                # Filter out ignored directories in-place
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
                
                for file in files:
                    if getattr(self, "cancel_calculation", False):
                        break
                    
                    # The cycle starts immediately. Calculate for 1 minute (60s) first, then sleep for 30 minutes (1800s),
                    # then wake up and calculate for 5 minutes (300s), sleep for 30 minutes (1800s), etc.
                    current_time = time.time()
                    is_initial_phase = not getattr(self, "_calculation_started_cycle", False)
                    limit_time = 60.0 if is_initial_phase else 300.0
                    
                    if (current_time - last_break_time) > limit_time:
                        # Save current state of cache before sleeping
                        try:
                            with open(cache_file, "w") as f:
                                json.dump(new_file_cache, f, indent=2)
                        except Exception:
                            pass
                        for _ in range(1800):
                            if getattr(self, "cancel_calculation", False):
                                break
                            time.sleep(1.0)
                        last_break_time = time.time()
                        self._calculation_started_cycle = True
                        
                    ext = os.path.splitext(file)[1].lower()
                    if ext not in allowed_extensions:
                        continue
                        
                    file_path = os.path.join(root_dir, file)
                    
                    # Skip files that are too large (e.g., lock files or generated datasets)
                    try:
                        sz = os.path.getsize(file_path)
                        if sz > 1_000_000: # 1MB limit
                            continue
                            
                        mtime = os.path.getmtime(file_path)
                        
                        # Check cache
                        cached_entry = file_cache.get(file_path)
                        if cached_entry and cached_entry.get("mtime") == mtime and cached_entry.get("size") == sz:
                            toks = cached_entry.get("tokens", 0)
                            new_file_cache[file_path] = cached_entry
                        else:
                            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                                
                            if encoding:
                                toks = len(encoding.encode(content))
                            else:
                                toks = len(content) // 4
                                
                            new_file_cache[file_path] = {
                                "mtime": mtime,
                                "size": sz,
                                "tokens": toks
                            }
                            
                        total_tokens += toks
                        total_bytes += sz
                        file_count += 1
                        
                        # Yield CPU to prevent lagging: sleep 10 milliseconds every 500 files
                        if file_count % 500 == 0:
                            time.sleep(0.01)
                            update_callback(total_tokens, total_bytes, False)
                    except Exception:
                        pass
        except Exception:
            pass
            
        # Save updated cache on finish
        try:
            with open(cache_file, "w") as f:
                json.dump(new_file_cache, f, indent=2)
        except Exception:
            pass
            
        update_callback(total_tokens, total_bytes, True)
        return total_tokens, total_bytes

    def _detect_changes(self, workspace_path: str):
        import hashlib
        import difflib
        
        # Ignored directories
        ignore_dirs = {
            ".git", ".rokct", ".venv", "venv", "env", "__pycache__", 
            "node_modules", "dist", "build", ".next", ".cache", "out",
            "target", "bin", "obj", "ios", "android", ".expo", ".output",
            "logs", "temp", "tmp", "coverage"
        }
        allowed_extensions = {
            ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", 
            ".json", ".md", ".toml", ".yaml", ".yml", ".txt", ".ini"
        }
        
        baseline = load_baseline_snapshot()
        
        # Compute current files snapshot
        current_snapshot = {}
        for root_dir, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in allowed_extensions:
                    continue
                file_path = os.path.join(root_dir, file)
                rel_path = os.path.relpath(file_path, workspace_path).replace("\\", "/")
                
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    lines = content.splitlines()
                    
                    hasher = hashlib.sha256()
                    hasher.update(content.encode("utf-8"))
                    file_hash_val = hasher.hexdigest()
                    
                    current_snapshot[rel_path] = {
                        "hash": file_hash_val,
                        "lines": lines,
                        "content": content
                    }
                except Exception:
                    pass
                    
        # If baseline is empty, initialize it to prevent showing all files as added on first run
        if not baseline:
            init_baseline = {}
            for rel_path, data in current_snapshot.items():
                init_baseline[rel_path] = {
                    "hash": data["hash"],
                    "lines": data["lines"]
                }
            save_baseline_snapshot(init_baseline)
            self.pending_changes = []
            return

        # Compare and calculate diffs
        changes = []
        
        # 1. Added and Modified files
        for rel_path, curr_data in current_snapshot.items():
            base_data = baseline.get(rel_path)
            if not base_data:
                additions = len(curr_data["lines"])
                changes.append({
                    "path": rel_path,
                    "type": "added",
                    "additions": additions,
                    "deletions": 0,
                    "content": curr_data["content"]
                })
            elif base_data["hash"] != curr_data["hash"]:
                base_lines = base_data.get("lines", [])
                curr_lines = curr_data["lines"]
                
                diff = list(difflib.ndiff(base_lines, curr_lines))
                additions = sum(1 for line in diff if line.startswith("+ "))
                deletions = sum(1 for line in diff if line.startswith("- "))
                
                changes.append({
                    "path": rel_path,
                    "type": "modified",
                    "additions": additions,
                    "deletions": deletions,
                    "content": curr_data["content"]
                })
                
        # 2. Deleted files
        for rel_path, base_data in baseline.items():
            if rel_path not in current_snapshot:
                deletions = len(base_data.get("lines", []))
                changes.append({
                    "path": rel_path,
                    "type": "deleted",
                    "additions": 0,
                    "deletions": deletions,
                    "content": ""
                })
                
        self.pending_changes = changes

    def start_http_server(self):
        def run_server():
            server_address = ('127.0.0.1', 49998)
            class ReuseHTTPServer(HTTPServer):
                allow_reuse_address = True
            try:
                httpd = ReuseHTTPServer(server_address, OrbitHTTPRequestHandler)
                httpd.serve_forever()
            except Exception as e:
                pass
        threading.Thread(target=run_server, daemon=True).start()

    def handle_chrome_data(self, data):
        self.chrome_extension_connected = True
        self.chrome_data = data
        self.root.after(0, self.update_layout_from_chrome)

    def update_layout_from_chrome(self):
        self.update_layout()
        if self.net_expanded:
            self.refresh_net_list()

    def toggle_net_panel(self, event=None):
        self.net_expanded = not self.net_expanded
        if self.collapse_timer:
            self.root.after_cancel(self.collapse_timer)
            self.collapse_timer = None
            
        if self.net_expanded:
            self.is_compact = False
            # Collapse other panels
            if self.todo_expanded:
                self.toggle_todo_list()
            if self.login_expanded:
                self.toggle_login_expansion()
                
            if not hasattr(self, "net_frame"):
                self.setup_net_ui()
            self.net_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self.refresh_net_list()
        else:
            if hasattr(self, "net_frame"):
                self.net_frame.pack_forget()
                
        self.update_layout()
        return "break"

    def setup_net_ui(self):
        self.net_frame = tk.Frame(self.root, bg=self.bg_color, bd=0)
        
        # Header title for network
        header_frame = tk.Frame(self.net_frame, bg=self.bg_color)
        header_frame.pack(fill=tk.X, padx=10, pady=(8, 2))
        
        tk.Label(
            header_frame, text="Network Monitor",
            font=("Segoe UI", 9, "bold") if sys.platform == "win32" else ("SF Pro Text", 10, "bold"),
            fg=self.accent_color, bg=self.bg_color
        ).pack(side=tk.LEFT)
        
        self.net_total_lbl = tk.Label(
            header_frame, text="OS: -- | Ext: --",
            font=("Segoe UI", 7) if sys.platform == "win32" else ("SF Pro Text", 8),
            fg="#585b79", bg=self.bg_color
        )
        self.net_total_lbl.pack(side=tk.RIGHT)
        
        # Scrollable Canvas
        self.net_canvas = tk.Canvas(self.net_frame, bg=self.bg_color, bd=0, highlightthickness=0)
        self.net_scrollbar = tk.Scrollbar(self.net_frame, orient="vertical", command=self.net_canvas.yview, width=6, bd=0, elementborderwidth=0)
        self.net_list_frame = tk.Frame(self.net_canvas, bg=self.bg_color)
        
        self.net_canvas.create_window((0, 0), window=self.net_list_frame, anchor="nw", tags="self.net_list_frame")
        self.net_canvas.configure(yscrollcommand=self.net_scrollbar.set)
        
        self.net_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=(10, 0), pady=2)
        self.net_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 4))
        
        self.net_canvas.bind("<Configure>", lambda e: self.net_canvas.itemconfig("self.net_list_frame", width=e.width))
        self.net_list_frame.bind("<Configure>", lambda e: self.net_canvas.configure(scrollregion=self.net_canvas.bbox("all")))
        
        def _on_mousewheel(event):
            self.net_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.net_canvas.bind("<Enter>", lambda e: self.net_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.net_canvas.bind("<Leave>", lambda e: self.net_canvas.unbind_all("<MouseWheel>"))

    def refresh_net_list(self):
        # Clear existing items
        for widget in self.net_list_frame.winfo_children():
            widget.destroy()
            
        # 1. Fetch OS-wide network stats
        try:
            counters = psutil.net_io_counters()
            os_total = counters.bytes_sent + counters.bytes_recv
            def fmt(b):
                if b >= 1073741824: return f"{b/1073741824:.1f} GB"
                if b >= 1048576: return f"{b/1048576:.1f} MB"
                if b >= 1024: return f"{b/1024:.1f} KB"
                return f"{b} B"
            os_str = fmt(os_total)
        except Exception:
            os_str = "Error"
            
        # 2. Fetch Chrome extension data
        domains = self.chrome_data.get("dataUsage", {})
        chrome_total = sum(d.get("totalSize", 0) for d in domains.values())
        chrome_str = fmt(chrome_total)
        
        self.net_total_lbl.configure(text=f"OS: {os_str} | Chrome: {chrome_str}")
        
        # Sort domains by data size
        sorted_domains = sorted(domains.items(), key=lambda x: x[1].get("totalSize", 0), reverse=True)
        
        # ROKCT standard app data listing
        row = tk.Frame(self.net_list_frame, bg=self.hover_color, bd=0)
        row.pack(fill=tk.X, pady=2, padx=(0, 4))
        tk.Label(row, text="🖥️ Total OS Network", font=("Segoe UI", 9, "bold"), fg=self.fg_color, bg=self.hover_color).pack(side=tk.LEFT, padx=8, pady=4)
        tk.Label(row, text=os_str, font=("Segoe UI", 9, "bold"), fg=self.accent_color, bg=self.hover_color).pack(side=tk.RIGHT, padx=8)

        row2 = tk.Frame(self.net_list_frame, bg=self.hover_color, bd=0)
        row2.pack(fill=tk.X, pady=2, padx=(0, 4))
        tk.Label(row2, text="🌐 Chrome Total", font=("Segoe UI", 9, "bold"), fg=self.fg_color, bg=self.hover_color).pack(side=tk.LEFT, padx=8, pady=4)
        tk.Label(row2, text=chrome_str, font=("Segoe UI", 9, "bold"), fg=self.accent_color, bg=self.hover_color).pack(side=tk.RIGHT, padx=8)

        # Show detailed Chrome sites if they exist
        for domain, d_info in sorted_domains[:10]: # Top 10 sites
            size = d_info.get("totalSize", 0)
            if size == 0: continue
            
            d_row = tk.Frame(self.net_list_frame, bg=self.bg_color, bd=0)
            d_row.pack(fill=tk.X, pady=1, padx=(10, 4))
            
            lbl_domain = tk.Label(d_row, text=f"• {domain}", font=("Segoe UI", 8), fg="#a6adc8", bg=d_row.cget("bg"), anchor="w")
            lbl_domain.pack(side=tk.LEFT, padx=4, pady=2)
            
            lbl_size = tk.Label(d_row, text=fmt(size), font=("Segoe UI", 8), fg=self.fg_color, bg=d_row.cget("bg"))
            lbl_size.pack(side=tk.RIGHT, padx=4)

    def toggle_changes_panel(self, event=None):
        self.changes_expanded = not self.changes_expanded
        if self.collapse_timer:
            self.root.after_cancel(self.collapse_timer)
            self.collapse_timer = None
            
        if self.changes_expanded:
            self.is_compact = False
            # Collapse other panels
            if self.todo_expanded:
                self.toggle_todo_list()
            if self.login_expanded:
                self.toggle_login_expansion()
            if self.net_expanded:
                self.toggle_net_panel()
                
            if not hasattr(self, "changes_frame"):
                self.setup_changes_ui()
            self.changes_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self.refresh_changes_list()
        else:
            if hasattr(self, "changes_frame"):
                self.changes_frame.pack_forget()
                
        self.update_layout()
        return "break"

    def setup_changes_ui(self):
        self.changes_frame = tk.Frame(self.root, bg=self.bg_color, bd=0)
        
        # Header title for changes
        header_frame = tk.Frame(self.changes_frame, bg=self.bg_color)
        header_frame.pack(fill=tk.X, padx=10, pady=(8, 2))
        
        tk.Label(
            header_frame, text="Pending Changes",
            font=("Segoe UI", 9, "bold") if sys.platform == "win32" else ("SF Pro Text", 10, "bold"),
            fg=self.accent_color, bg=self.bg_color
        ).pack(side=tk.LEFT)
        
        self.changes_total_lbl = tk.Label(
            header_frame, text="-- files",
            font=("Segoe UI", 7) if sys.platform == "win32" else ("SF Pro Text", 8),
            fg="#585b79", bg=self.bg_color
        )
        self.changes_total_lbl.pack(side=tk.RIGHT)
        
        # Scrollable Canvas
        self.changes_canvas = tk.Canvas(self.changes_frame, bg=self.bg_color, bd=0, highlightthickness=0)
        self.changes_scrollbar = tk.Scrollbar(self.changes_frame, orient="vertical", command=self.changes_canvas.yview, width=6, bd=0, elementborderwidth=0)
        self.changes_list_frame = tk.Frame(self.changes_canvas, bg=self.bg_color)
        
        self.changes_canvas.create_window((0, 0), window=self.changes_list_frame, anchor="nw", tags="self.changes_list_frame")
        self.changes_canvas.configure(yscrollcommand=self.changes_scrollbar.set)
        
        self.changes_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=(10, 0), pady=2)
        self.changes_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 4))
        
        self.changes_canvas.bind("<Configure>", lambda e: self.changes_canvas.itemconfig("self.changes_list_frame", width=e.width))
        self.changes_list_frame.bind("<Configure>", lambda e: self.changes_canvas.configure(scrollregion=self.changes_canvas.bbox("all")))
        
        def _on_mousewheel(event):
            self.changes_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.changes_canvas.bind("<Enter>", lambda e: self.changes_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.changes_canvas.bind("<Leave>", lambda e: self.changes_canvas.unbind_all("<MouseWheel>"))

    def refresh_changes_list(self):
        # Clear existing items
        for widget in self.changes_list_frame.winfo_children():
            widget.destroy()
            
        changes = getattr(self, "pending_changes", [])
        self.changes_total_lbl.configure(text=f"{len(changes)} files")
        
        if not changes:
            lbl = tk.Label(self.changes_list_frame, text="No changes detected", font=("Segoe UI", 8), fg="#585b79", bg=self.bg_color)
            lbl.pack(fill=tk.X, pady=10)
            return
            
        for change in changes:
            row = tk.Frame(self.changes_list_frame, bg=self.bg_color, bd=0)
            row.pack(fill=tk.X, pady=1, padx=(0, 4))
            
            if change["type"] == "added":
                indicator_color = "#a6e3a1"
                indicator_symbol = "+"
            elif change["type"] == "deleted":
                indicator_color = "#f38ba8"
                indicator_symbol = "-"
            else:
                indicator_color = "#fab387"
                indicator_symbol = "~"
                
            ind_lbl = tk.Label(row, text=indicator_symbol, font=("Segoe UI", 9, "bold"), fg=indicator_color, bg=self.bg_color, width=2)
            ind_lbl.pack(side=tk.LEFT, padx=(2, 4))
            
            path_lbl = tk.Label(row, text=change["path"], font=("Segoe UI", 8), fg=self.fg_color, bg=self.bg_color, anchor="w")
            path_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            stats_str = f"+{change['additions']} -{change['deletions']}"
            stats_lbl = tk.Label(row, text=stats_str, font=("Segoe UI", 8), fg="#585b79", bg=self.bg_color)
            stats_lbl.pack(side=tk.RIGHT, padx=4)

    def _reset_baseline(self, workspace_path: str):
        import hashlib
        ignore_dirs = {
            ".git", ".rokct", ".venv", "venv", "env", "__pycache__", 
            "node_modules", "dist", "build", ".next", ".cache", "out",
            "target", "bin", "obj", "ios", "android", ".expo", ".output",
            "logs", "temp", "tmp", "coverage"
        }
        allowed_extensions = {
            ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", 
            ".json", ".md", ".toml", ".yaml", ".yml", ".txt", ".ini"
        }
        new_baseline = {}
        for root_dir, dirs, files in os.walk(workspace_path):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in allowed_extensions:
                    continue
                file_path = os.path.join(root_dir, file)
                rel_path = os.path.relpath(file_path, workspace_path).replace("\\", "/")
                
                try:
                     with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                         content = f.read()
                     lines = content.splitlines()
                     hasher = hashlib.sha256()
                     hasher.update(content.encode("utf-8"))
                     file_hash_val = hasher.hexdigest()
                     
                     new_baseline[rel_path] = {
                         "hash": file_hash_val,
                         "lines": lines
                     }
                except Exception:
                     pass
        save_baseline_snapshot(new_baseline)

    def orbit_push(self):
        config = load_orbit_config()
        server = config.get("server")
        token = config.get("token")
        workspace_path = config.get("workspace")
        
        if not token or not server:
            messagebox.showerror("Push Error", "Please login to Gravity first.", parent=self.root)
            return
            
        if not workspace_path or not os.path.isdir(workspace_path):
            messagebox.showerror("Push Error", "Please set a valid workspace directory first.", parent=self.root)
            return
            
        if not self.pending_changes:
            messagebox.showinfo("Push", "No changes to push.", parent=self.root)
            return
            
        # Confirm push
        if not messagebox.askyesno("Confirm Push", f"Are you sure you want to push {len(self.pending_changes)} modified files to Gravity?", parent=self.root):
            return
            
        self.set_transacting(True)
        
        # Build changes payload
        payload_changes = []
        for change in self.pending_changes:
            payload_changes.append({
                "path": change["path"],
                "content": change["content"],
                "type": change["type"]
            })
            
        import urllib.request
        import urllib.error
        
        push_url = f"{server}/gravity/v1/workspace/push"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        
        push_payload = json.dumps({
            "changes": payload_changes,
            "message": f"Orbit sync update: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        }).encode("utf-8")
        
        def do_push_thread():
            try:
                req = urllib.request.Request(push_url, data=push_payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=15) as response:
                    res_data = json.loads(response.read().decode())
                    
                if not res_data.get("status"):
                    raise Exception(res_data.get("message", "Unknown error occurred on Gravity"))
                    
                self.root.after(0, lambda: self.handle_push_success(workspace_path))
            except urllib.error.HTTPError as e:
                try:
                    err_data = json.loads(e.read().decode())
                    msg = err_data.get("detail", e.reason)
                except Exception:
                    msg = e.reason
                self.root.after(0, lambda: self.handle_push_error(f"Push failed: {msg}"))
            except Exception as e:
                self.root.after(0, lambda: self.handle_push_error(f"Failed to connect to Gravity: {str(e)}"))
                
        threading.Thread(target=do_push_thread, daemon=True).start()

    def handle_push_success(self, workspace_path):
        self.set_transacting(False)
        self._reset_baseline(workspace_path)
        self.pending_changes = []
        if self.changes_expanded:
            self.toggle_changes_panel()
        self.refresh()
        messagebox.showinfo("Push Success", "Workspace successfully pushed to Gravity!", parent=self.root)

    def handle_push_error(self, error_msg):
        self.set_transacting(False)
        messagebox.showerror("Push Error", error_msg, parent=self.root)


def run_widget():
    # Single instance lock using a TCP socket
    lock_port = 49999
    
    # Try to connect to existing instance to tell it to shut down
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(("127.0.0.1", lock_port))
        s.sendall(b"EXIT")
        s.close()
        # Give the older instance a moment to exit
        time.sleep(0.5)
    except Exception:
        pass

    # Now bind to the lock port as the primary instance
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server_socket.bind(("127.0.0.1", lock_port))
        server_socket.listen(1)
        server_socket.setblocking(False)
    except Exception:
        # If port binding still fails, another instance is actively running and refusing to exit
        sys.exit(0)

    root = tk.Tk()
    app = TokenStatusWidget(root)

    # Listen for shutdown signals on the lock port
    def check_instance_socket():
        try:
            conn, addr = server_socket.accept()
            msg = conn.recv(1024)
            if b"EXIT" in msg:
                conn.close()
                server_socket.close()
                root.destroy()
                return
            conn.close()
        except BlockingIOError:
            pass
        except Exception:
            pass
        root.after(500, check_instance_socket)

    root.after(500, check_instance_socket)
    
    try:
        root.mainloop()
    finally:
        try:
            server_socket.close()
        except Exception:
            pass


if __name__ == "__main__":
    run_widget()
