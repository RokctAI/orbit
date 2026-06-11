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



class LoginDialog(tk.Toplevel):
    def __init__(self, parent, theme, on_success):
        super().__init__(parent)
        self.theme = theme
        self.on_success = on_success
        
        self.title("Orbit Login")
        self.configure(bg=self.theme["bg_color"])
        self.resizable(False, False)
        
        # Center dialog
        w, h = 320, 200
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        
        # Always on top & modal focus
        self.attributes("-topmost", True)
        self.transient(parent)
        self.grab_set()
        
        # UI Elements
        tk.Label(
            self, text="Connect to Gravity Server",
            font=("Segoe UI", 11, "bold"), fg=self.theme["accent_color"], bg=self.theme["bg_color"]
        ).pack(pady=(12, 8))
        
        # Server URL Frame
        sf = tk.Frame(self, bg=self.theme["bg_color"])
        sf.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(sf, text="Server URL:", font=("Segoe UI", 9), fg=self.theme["fg_color"], bg=self.theme["bg_color"], width=10, anchor="w").pack(side=tk.LEFT)
        self.server_entry = tk.Entry(sf, bg=self.theme["hover_color"], fg=self.theme["fg_color"], insertbackground=self.theme["fg_color"], bd=1, relief=tk.FLAT)
        self.server_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Configured server fallback
        config = load_orbit_config()
        if config.get("server"):
            self.server_entry.insert(0, config["server"])
        else:
            self.server_entry.insert(0, "http://")
            
        # API Token Frame
        tf = tk.Frame(self, bg=self.theme["bg_color"])
        tf.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(tf, text="API Token:", font=("Segoe UI", 9), fg=self.theme["fg_color"], bg=self.theme["bg_color"], width=10, anchor="w").pack(side=tk.LEFT)
        self.token_entry = tk.Entry(tf, show="*", bg=self.theme["hover_color"], fg=self.theme["fg_color"], insertbackground=self.theme["fg_color"], bd=1, relief=tk.FLAT)
        self.token_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if config.get("token"):
            self.token_entry.insert(0, config["token"])
            
        # Button bar
        bf = tk.Frame(self, bg=self.theme["bg_color"])
        bf.pack(pady=15)
        
        btn_conn = tk.Button(
            bf, text="Connect", font=("Segoe UI", 9, "bold"),
            bg=self.theme["accent_color"], fg=self.theme["bg_color"],
            activebackground=self.theme["accent_color"], activeforeground=self.theme["bg_color"],
            bd=0, padx=14, pady=4, relief=tk.FLAT, cursor="hand2", command=self.submit
        )
        btn_conn.pack(side=tk.LEFT, padx=6)
        
        btn_cancel = tk.Button(
            bf, text="Cancel", font=("Segoe UI", 9),
            bg=self.theme["hover_color"], fg=self.theme["fg_color"],
            activebackground=self.theme["hover_color"], activeforeground=self.theme["fg_color"],
            bd=0, padx=14, pady=4, relief=tk.FLAT, cursor="hand2", command=self.destroy
        )
        btn_cancel.pack(side=tk.LEFT, padx=6)

    def submit(self):
        server = self.server_entry.get().strip()
        token = self.token_entry.get().strip()
        if not server or not token:
            messagebox.showerror("Error", "Both Server URL and API Token are required.", parent=self)
            return
        
        config = load_orbit_config()
        config["server"] = server.rstrip("/")
        config["token"] = token
        save_orbit_config(config)
        
        self.on_success()
        self.destroy()


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
        self.is_compact = True
        self.collapse_timer = None
        self.todo_expanded = False
        self.todo_height = 180
        self._prev_todo_expanded = False
        self.original_y = None # Track the position of the widget before expanding todo
        self._calculation_started_cycle = False
        
        # Build layout UI
        self.setup_ui()
        
        # Interaction events
        self.setup_events()
        
        # Start initial async update after 30 seconds startup grace period
        self.root.after(30000, self.refresh)
        
        # Start auto-update scheduler
        self.schedule_auto_refresh()
        
        # Start blinking corner triangle loop
        self.blink_state = True
        self.run_blink_loop()

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
            text="Tokens: ...",
            font=("Segoe UI", 9) if sys.platform == "win32" else ("SF Pro Text", 10),
            fg=self.fg_color,
            bg=self.bg_color
        )
        self.token_label.pack(side=tk.LEFT)
        
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
                w.bind("<Double-Button-1>", self.toggle_todo_list)
            else:
                w.bind("<Double-Button-1>", self.toggle_compact)
            
        # Specific hover and click events for buttons
        self.login_btn.bind("<Button-1>", lambda e: self.show_login_dialog())
        self.login_btn.bind("<Enter>", lambda e: [self.on_enter(e), self.login_btn.configure(fg=self.fg_color)])
        self.login_btn.bind("<Leave>", lambda e: [self.on_leave(e), self.login_btn.configure(fg=self.accent_color)])
        
        self.logout_btn.bind("<Button-1>", lambda e: self.logout())
        self.logout_btn.bind("<Enter>", lambda e: [self.on_enter(e), self.logout_btn.configure(fg=self.fg_color)])
        self.logout_btn.bind("<Leave>", lambda e: [self.on_leave(e), self.logout_btn.configure(fg=self.accent_color)])
        
        self.workspace_btn.bind("<Button-1>", lambda e: self.select_workspace())
        self.workspace_btn.bind("<Enter>", lambda e: [self.on_enter(e), self.workspace_btn.configure(fg=self.fg_color)])
        self.workspace_btn.bind("<Leave>", lambda e: [self.on_leave(e), self.workspace_btn.configure(fg=self.accent_color)])
        
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
        self.sep_label1.configure(bg=self.bg_color)
        self.token_label.configure(bg=self.bg_color)
        self.close_btn.configure(bg=self.bg_color)
        
        # Trigger auto-collapse to compact mode in 10 seconds (only if todo list is not expanded)
        if self.collapse_timer:
            self.root.after_cancel(self.collapse_timer)
            self.collapse_timer = None
        if not self.todo_expanded:
            self.collapse_timer = self.root.after(10000, self.auto_collapse)



    def on_token_click(self, event):
        if self.is_updating:
            self.cancel_calculation = True
            self.token_label.configure(text="Canceling...")
        else:
            self.start_drag(event)

    def start_drag(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def drag(self, event):
        # Calculate coordinate delta and move window
        x = self.root.winfo_x() - self.drag_x + event.x
        y = self.root.winfo_y() - self.drag_y + event.y
        self.root.geometry(f"+{x}+{y}")

    def end_drag(self, event):
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
        
        # 1. Check Internet and Server Status
        online = self._check_connection()
        
        # 2. Fetch country code and flag image if online (cached locally after first fetch)
        if online:
            if not self.country_code:
                try:
                    import urllib.request
                    req = urllib.request.Request("http://ip-api.com/json", headers={"User-Agent": "Orbit/1.0"})
                    with urllib.request.urlopen(req, timeout=3.0) as response:
                        data = json.loads(response.read().decode())
                        self.country_code = data.get("countryCode", "").lower()
                        if self.country_code:
                            # Save to config cache
                            config = load_orbit_config()
                            config["country_code"] = self.country_code
                            save_orbit_config(config)
                except Exception:
                    pass
            
            if self.country_code:
                # Ensure flags directory exists
                flags_dir = os.path.join(CONFIG_DIR, "flags")
                os.makedirs(flags_dir, exist_ok=True)
                self.flag_path = os.path.join(flags_dir, f"{self.country_code}.png")
                if not os.path.isfile(self.flag_path):
                    try:
                        import urllib.request
                        flag_url = f"https://flagcdn.com/w20/{self.country_code}.png"
                        req = urllib.request.Request(flag_url, headers={"User-Agent": "Orbit/1.0"})
                        with urllib.request.urlopen(req, timeout=4.0) as response:
                            with open(self.flag_path, "wb") as f:
                                f.write(response.read())
                    except Exception:
                        self.flag_path = None
            else:
                self.flag_path = None
        else:
            self.flag_path = None
                
        # 3. Count Tokens and Size of current workspace
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
            elif tokens >= 1_000_000:
                tokens_str = f"{tokens / 1_000_000:.2f}M"
            elif tokens >= 1_000:
                tokens_str = f"{tokens / 1_000:.1f}k"
            else:
                tokens_str = str(tokens)
                
            # Format size neatly
            if size_bytes >= 1_048_576:
                size_str = f"{size_bytes / 1_048_576:.1f} MB"
            elif size_bytes >= 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes} B"
                
            # Schedule GUI updates on the main thread safely
            self.root.after(0, self._apply_updates, online, tokens_str, size_str, is_done or was_canceled)
            
        self._calculate_codebase_tokens(workspace_dir, progress_callback)

    def _apply_updates(self, online, tokens_str, size_str, is_done=True):
        self.is_online = online
        self.tokens_str = tokens_str
        self.size_str = size_str
        
        # Cache token counts and sizes to configuration to persist across widget launches
        config = load_orbit_config()
        config["cached_tokens_str"] = tokens_str
        config["cached_size_str"] = size_str
        save_orbit_config(config)
        
        self.update_layout(is_done=is_done)

    def update_layout(self, is_done=True):
        # If this is a partial update during scanning, only update the token label text and adjust geometry width (no repacking)
        if not is_done:
            if self.is_compact:
                self.token_label.configure(text=f"{self.tokens_str} ({self.size_str.replace(' ', '')})")
            else:
                self.token_label.configure(text=f"Tokens: {self.tokens_str} ({self.size_str})")
                
            self.root.update_idletasks()
            new_width = self.main_frame.winfo_reqwidth() + 20
            if self.todo_expanded and hasattr(self, "todo_frame"):
                new_width = max(new_width, self.todo_frame.winfo_reqwidth() + 20)
                
            target_height = self.height + self.todo_height if self.todo_expanded else self.height
            curr_x = self.root.winfo_x()
            curr_y = self.root.winfo_y()
            old_width = self.root.winfo_width()
            
            new_x = curr_x
            if old_width > 1:
                screen_w = self.root.winfo_screenwidth()
                if curr_x + (old_width / 2) > (screen_w / 2):
                    new_x = curr_x - (new_width - old_width)
                    
            self.root.geometry(f"{new_width}x{target_height}+{new_x}+{curr_y}")
            return
            
        try:
            bg = self.brand_badge.cget("bg")
        except Exception:
            bg = "#ff4600"
            
        if self.is_online:
            if bg.lower() in ["#a6e3a1", "#13f300"] or bg.lower().startswith("#a") or bg.lower().startswith("#0") or bg.lower().startswith("#13"):
                color = "#ffffff"
            else:
                color = "#13F300"
        else:
            if bg.lower() in ["#ff4600", "#f38ba8"] or bg.lower().startswith("#f") or bg.lower().startswith("#e"):
                color = "#ffffff"
            else:
                color = self.offline_color
                
        self.status_line.configure(bg=color)
        
        # Clear packing for all dynamically ordered widgets to preserve strict sorting
        self.brand_badge.pack_forget()
        self.login_btn.pack_forget()
        self.logout_btn.pack_forget()
        self.workspace_btn.pack_forget()
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
            
        brand = "Orbit"
        
        if self.is_compact:
            # Compact Layout: Brand Name configured
            self.app_label.configure(text=brand)
            self.sep_label1.pack_forget()
            self.token_label.configure(text=f"{self.tokens_str} ({self.size_str.replace(' ', '')})")
            self.token_label.pack(side=tk.LEFT)
        else:
            # Expanded Layout
            if self.logged_in:
                self.app_label.configure(text=f"{brand} ({self.username})")
                self.logout_btn.pack(side=tk.LEFT, padx=(0, 4))
            else:
                self.app_label.configure(text=brand)  # Never show Guest text
                if not workspace_set:
                    self.workspace_btn.pack(side=tk.LEFT, padx=(0, 4))
                else:
                    self.login_btn.pack(side=tk.LEFT, padx=(0, 4))
                    
            # Repack separator and token/size display in expanded layout
            self.sep_label1.pack(side=tk.LEFT, padx=6)
            self.token_label.configure(text=f"Tokens: {self.tokens_str} ({self.size_str})")
            self.token_label.pack(side=tk.LEFT)
            
        # Ensure status indicator line stays on top of brand badge child elements
        self.status_line.lift()
            
        # Re-pack self.main_frame and set heights depending on expanded todo state
        if self.todo_expanded:
            self.main_frame.pack_forget()
            self.main_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=(0, 8), pady=0)
            self.main_frame.configure(height=self.height)
            self.main_frame.pack_propagate(False)
        else:
            self.main_frame.pack_forget()
            self.main_frame.pack(fill=tk.BOTH, expand=True, padx=(0, 8), pady=0)
            self.main_frame.pack_propagate(True)
            
        # Dynamically calculate and set window width
        self.root.update_idletasks()
        new_width = self.main_frame.winfo_reqwidth() + 20 # Add padding
        if self.todo_expanded and hasattr(self, "todo_frame"):
            new_width = max(new_width, self.todo_frame.winfo_reqwidth() + 20)
            
        target_height = self.height + self.todo_height if self.todo_expanded else self.height
        
        # Preserve position coordinates while adapting window geometry (upwards/downwards expansion)
        curr_x = self.root.winfo_x()
        curr_y = self.root.winfo_y()
        old_width = self.root.winfo_width()
        
        # Shift Y coordinate correctly during Todo toggle transitions to expand upwards and collapse back
        new_y = curr_y
        if self.todo_expanded:
            if not getattr(self, "_prev_todo_expanded", False):
                self.original_y = curr_y
                new_y = curr_y - self.todo_height
        else:
            if getattr(self, "_prev_todo_expanded", False):
                if getattr(self, "original_y", None) is not None:
                    new_y = self.original_y
                    self.original_y = None
                else:
                    new_y = curr_y + self.todo_height
                
        self._prev_todo_expanded = self.todo_expanded
        
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
            
        if config.get("token"):
            self.menu.add_command(label="Logout", command=self.logout)
        elif config.get("workspace"):
            self.menu.add_command(label="Login", command=self.show_login_dialog)
            
        self.menu.add_separator()
        self.menu.add_command(label="Exit Widget", command=self.root.destroy)

    def show_login_dialog(self):
        LoginDialog(self.root, self.theme, on_success=self.refresh)

    def select_workspace(self):
        folder = filedialog.askdirectory(title="Select Orbit Workspace", parent=self.root)
        if folder:
            config = load_orbit_config()
            config["workspace"] = folder

            save_orbit_config(config)
            self.refresh()

    def toggle_compact(self, event=None):
        self.is_compact = not self.is_compact
        if self.is_compact and self.todo_expanded:
            self.toggle_todo_list()
        self.update_layout()
        return "break"

    def auto_collapse(self):
        self.is_compact = True
        if self.todo_expanded:
            self.toggle_todo_list()
        self.update_layout()

    def run_blink_loop(self):
        self.blink_state = not self.blink_state
        
        # Read the current badge background color
        try:
            bg = self.brand_badge.cget("bg")
        except Exception:
            bg = "#ff4600"
            
        # Determine offline color
        if bg.lower() in ["#ff4600", "#f38ba8"] or bg.lower().startswith("#f") or bg.lower().startswith("#e"):
            offline_c = "#ffffff"  # Background is red/orange, use white
        else:
            offline_c = "#f38ba8"  # Use standard red
            
        # Determine online blink color
        if bg.lower() in ["#a6e3a1", "#13f300"] or bg.lower().startswith("#a") or bg.lower().startswith("#0") or bg.lower().startswith("#13"):
            online_c = "#ffffff"  # Background is green, use white
        else:
            online_c = "#13F300"  # Vibrant green
            
        if self.is_online:
            # Alternate between online color and badge background
            color = online_c if self.blink_state else bg
        else:
            color = offline_c
            
        try:
            self.status_line.configure(bg=color)
        except Exception:
            return
            
        self.root.after(800, self.run_blink_loop)

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
            
            # Double click gestures on row, bullet, or label toggles item status (returning break to prevent event propagation to root)
            row.bind("<Double-Button-1>", lambda e, i=idx: [self.toggle_todo_item(i), "break"][1])
            
            # Checkbox indicator (Unicode symbols: ● for checked, ○ for unchecked)
            status_char = "●" if t.get("done") else "○"
            status_color = self.accent_color if t.get("done") else self.fg_color
            
            chk = tk.Label(
                row, text=status_char, font=("Segoe UI", 11), 
                fg=status_color, bg=self.hover_color, cursor="hand2"
            )
            chk.pack(side=tk.LEFT, padx=(6, 6))
            chk.bind("<Button-1>", lambda e, i=idx: self.toggle_todo_item(i))
            chk.bind("<Double-Button-1>", lambda e, i=idx: [self.toggle_todo_item(i), "break"][1])
            
            # Text label
            text_fg = "#585b79" if t.get("done") else self.fg_color
            text_font = ("Segoe UI", 9, "overstrike") if t.get("done") else ("Segoe UI", 9)
            lbl = tk.Label(
                row, text=t["text"], font=text_font, fg=text_fg, 
                bg=self.hover_color, anchor="w", justify=tk.LEFT, cursor="hand2"
            )
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4)
            lbl.bind("<Button-1>", lambda e, i=idx: self.toggle_todo_item(i))
            lbl.bind("<Double-Button-1>", lambda e, i=idx: [self.toggle_todo_item(i), "break"][1])
            
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
                        
                        # Yield CPU to prevent lagging: sleep 10 milliseconds every 100 files
                        if file_count % 100 == 0:
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
