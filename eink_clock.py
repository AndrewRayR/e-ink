#!/usr/bin/env python3
"""
E-ink Display Clock and Menu System for Raspberry Pi 3A
with Waveshare 2.13" V4 Display
"""

import sys
import os
import time
import json
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import threading
import requests
from urllib.parse import quote

# Keyboard input handling
try:
    import tty
    import termios
except ImportError:
    print("Error: This script requires Unix/Linux terminal support")
    sys.exit(1)

# Waveshare e-ink library
try:
    from waveshare_epd import epd2in13_V4
except ImportError:
    print("Warning: Waveshare library not found. Running in demo mode.")
    epd2in13_V4 = None


class Display:
    """Handle e-ink display operations"""
    def __init__(self, settings_manager):
        self.width = 250  # Landscape
        self.height = 122
        self.epd = None
        self.demo_mode = epd2in13_V4 is None
        self.settings_manager = settings_manager
        
        if not self.demo_mode:
            try:
                self.epd = epd2in13_V4.EPD()
                self.epd.init()
                self.epd.Clear(0xFF)
            except Exception as e:
                print(f"Display init error: {e}. Running in demo mode.")
                self.demo_mode = True
    
    def get_colors(self):
        """Get foreground and background colors based on dark mode setting"""
        dark_mode = self.settings_manager.get_setting('dark_mode', True)
        if dark_mode:
            return 255, 0  # white foreground, black background
        else:
            return 0, 255  # black foreground, white background
    
    def show(self, image, partial=False):
        """Display image on e-ink screen"""
        if self.demo_mode:
            image.save('/tmp/eink_preview.png')
            print("Demo mode: Image saved to /tmp/eink_preview.png")
            return
        
        try:
            if partial:
                self.epd.displayPartial(self.epd.getbuffer(image))
            else:
                self.epd.display(self.epd.getbuffer(image))
        except Exception as e:
            print(f"Display error: {e}")
    
    def clear(self):
        """Clear the display"""
        if not self.demo_mode:
            self.epd.Clear(0xFF)
    
    def sleep(self):
        """Put display to sleep"""
        if not self.demo_mode:
            self.epd.sleep()


class KeyboardInput:
    """Handle keyboard input in non-blocking way"""
    def __init__(self):
        self.key_buffer = []
        self.running = True
        self.thread = threading.Thread(target=self._read_keys, daemon=True)
        self.thread.start()
    
    def _read_keys(self):
        """Background thread to read keyboard input"""
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            while self.running:
                if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                    char = sys.stdin.read(1)
                    
                    # Handle escape sequences (arrow keys, etc)
                    if char == '\x1b':
                        next_chars = sys.stdin.read(2)
                        if next_chars == '[A':
                            self.key_buffer.append('UP')
                        elif next_chars == '[B':
                            self.key_buffer.append('DOWN')
                        elif next_chars == '[C':
                            self.key_buffer.append('RIGHT')
                        elif next_chars == '[D':
                            self.key_buffer.append('LEFT')
                        else:
                            self.key_buffer.append('ESC')
                    elif char == '\r' or char == '\n':
                        self.key_buffer.append('ENTER')
                    elif char == '\x7f':  # Backspace
                        self.key_buffer.append('BACKSPACE')
                    else:
                        self.key_buffer.append(char)
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    
    def get_key(self):
        """Get next key from buffer"""
        if self.key_buffer:
            return self.key_buffer.pop(0)
        return None
    
    def stop(self):
        """Stop keyboard reading thread"""
        self.running = False


# Import select for keyboard reading
import select


class SettingsManager:
    """Manage application settings"""
    def __init__(self):
        self.settings_dir = Path.home() / "eink_notes"
        self.settings_dir.mkdir(exist_ok=True)
        self.settings_file = self.settings_dir / "settings.json"
        self.settings = self._load_settings()
    
    def _load_settings(self):
        """Load settings from file"""
        defaults = {
            'dark_mode': True,
            'clock_format': 12,  # 12 or 24
            'date_format': 'long',  # 'long', 'short', 'iso'
            'refresh_mode': 'partial',  # 'partial' or 'full'
            'auto_sleep': 0,  # 0 = never, minutes otherwise
            'show_seconds': False,
            'zip_code': ''
        }
        
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r') as f:
                    loaded = json.load(f)
                    defaults.update(loaded)
            except:
                pass
        
        return defaults
    
    def _save_settings(self):
        """Save settings to file"""
        with open(self.settings_file, 'w') as f:
            json.dump(self.settings, f, indent=2)
    
    def get_setting(self, key, default=None):
        """Get a setting value"""
        return self.settings.get(key, default)
    
    def set_setting(self, key, value):
        """Set a setting value"""
        self.settings[key] = value
        self._save_settings()
    
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        self.settings = {
            'dark_mode': True,
            'clock_format': 12,
            'date_format': 'long',
            'refresh_mode': 'partial',
            'auto_sleep': 0,
            'show_seconds': False,
            'zip_code': ''
        }
        self._save_settings()


class NotesManager:
    """Manage notes storage and retrieval"""
    def __init__(self):
        self.notes_dir = Path.home() / "eink_notes"
        self.notes_dir.mkdir(exist_ok=True)
        self.notes_file = self.notes_dir / "notes.json"
        self.notes = self._load_notes()
    
    def _load_notes(self):
        """Load notes from file"""
        if self.notes_file.exists():
            try:
                with open(self.notes_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_notes(self):
        """Save notes to file"""
        with open(self.notes_file, 'w') as f:
            json.dump(self.notes, f, indent=2)
    
    def create_note(self, title, content):
        """Create a new note"""
        note = {
            'id': len(self.notes) + 1,
            'title': title,
            'content': content,
            'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.notes.append(note)
        self._save_notes()
        return note
    
    def get_notes(self):
        """Get all notes"""
        return self.notes
    
    def get_note(self, note_id):
        """Get specific note by ID"""
        for note in self.notes:
            if note['id'] == note_id:
                return note
        return None
    
    def update_note(self, note_id, title, content):
        """Update existing note"""
        for note in self.notes:
            if note['id'] == note_id:
                note['title'] = title
                note['content'] = content
                self._save_notes()
                return True
        return False
    
    def delete_note(self, note_id):
        """Delete a note"""
        self.notes = [n for n in self.notes if n['id'] != note_id]
        self._save_notes()


class App:
    """Base class for all apps"""
    def __init__(self, display, keyboard, notes_manager, settings_manager):
        self.display = display
        self.keyboard = keyboard
        self.notes_manager = notes_manager
        self.settings_manager = settings_manager
        self.running = True
    
    def create_image(self):
        """Create image with correct colors based on dark mode"""
        fg, bg = self.display.get_colors()
        return Image.new('1', (self.display.width, self.display.height), bg), fg
    
    def draw_text_centered(self, draw, text, y, font, size=20, fill=None):
        """Draw centered text"""
        if fill is None:
            fill, _ = self.display.get_colors()
        
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        except:
            fnt = ImageFont.load_default()
        
        bbox = draw.textbbox((0, 0), text, font=fnt)
        text_width = bbox[2] - bbox[0]
        x = (self.display.width - text_width) // 2
        draw.text((x, y), text, font=fnt, fill=fill)
    
    def run(self):
        """Override this method in subclasses"""
        pass


class ClockApp(App):
    """Digital clock display with 7-segment style font"""
    def __init__(self, display, keyboard, notes_manager, settings_manager):
        super().__init__(display, keyboard, notes_manager, settings_manager)
        self.last_update = None
    
    def draw_7segment_digit(self, draw, digit, x, y, seg_width=4, seg_length=20, fill=0):
        """Draw a single 7-segment digit"""
        # 7-segment layout:
        #  aaa
        # f   b
        #  ggg
        # e   c
        #  ddd
        
        segments = {
            '0': [1,1,1,1,1,1,0],
            '1': [0,1,1,0,0,0,0],
            '2': [1,1,0,1,1,0,1],
            '3': [1,1,1,1,0,0,1],
            '4': [0,1,1,0,0,1,1],
            '5': [1,0,1,1,0,1,1],
            '6': [1,0,1,1,1,1,1],
            '7': [1,1,1,0,0,0,0],
            '8': [1,1,1,1,1,1,1],
            '9': [1,1,1,1,0,1,1],
            ' ': [0,0,0,0,0,0,0],
        }
        
        if digit not in segments:
            return
        
        seg = segments[digit]
        w = seg_width
        l = seg_length
        
        # Segment positions
        # a (top)
        if seg[0]:
            draw.rectangle([x+w, y, x+w+l, y+w], fill=fill)
        # b (top right)
        if seg[1]:
            draw.rectangle([x+w+l, y+w, x+w+l+w, y+w+l], fill=fill)
        # c (bottom right)
        if seg[2]:
            draw.rectangle([x+w+l, y+w+l+w, x+w+l+w, y+w+l+w+l], fill=fill)
        # d (bottom)
        if seg[3]:
            draw.rectangle([x+w, y+w+l+w+l, x+w+l, y+w+l+w+l+w], fill=fill)
        # e (bottom left)
        if seg[4]:
            draw.rectangle([x, y+w+l+w, x+w, y+w+l+w+l], fill=fill)
        # f (top left)
        if seg[5]:
            draw.rectangle([x, y+w, x+w, y+w+l], fill=fill)
        # g (middle)
        if seg[6]:
            draw.rectangle([x+w, y+w+l, x+w+l, y+w+l+w], fill=fill)
    
    def draw_7segment_time(self, draw, time_str, x, y, fill=0):
        """Draw time string with 7-segment digits"""
        digit_width = 30
        colon_width = 10
        
        current_x = x
        for char in time_str:
            if char == ':':
                # Draw colon
                draw.rectangle([current_x+3, y+15, current_x+7, y+19], fill=fill)
                draw.rectangle([current_x+3, y+35, current_x+7, y+39], fill=fill)
                current_x += colon_width
            else:
                self.draw_7segment_digit(draw, char, current_x, y, fill=fill)
                current_x += digit_width
    
    def run(self):
        """Main clock loop"""
        while self.running:
            now = datetime.now()
            
            # Check update interval based on show_seconds setting
            show_seconds = self.settings_manager.get_setting('show_seconds', False)
            if show_seconds:
                current_time = now.strftime('%H:%M:%S')
            else:
                current_time = now.strftime('%H:%M')
            
            # Only update display when time changes
            if current_time != self.last_update:
                image, fg = self.create_image()
                draw = ImageDraw.Draw(image)
                
                # Get date format
                date_format = self.settings_manager.get_setting('date_format', 'long')
                if date_format == 'long':
                    date_str = now.strftime('%a, %b %d, %Y')
                elif date_format == 'short':
                    date_str = now.strftime('%m/%d/%Y')
                else:  # iso
                    date_str = now.strftime('%Y-%m-%d')
                
                # Draw date at top (bigger)
                self.draw_text_centered(draw, date_str, 5, None, 18, fg)
                
                # Draw time with 7-segment display
                clock_format = self.settings_manager.get_setting('clock_format', 12)
                if clock_format == 12:
                    if show_seconds:
                        time_str = now.strftime('%I:%M:%S')
                    else:
                        time_str = now.strftime('%I:%M')
                    # Remove leading zero from hour
                    if time_str[0] == '0':
                        time_str = ' ' + time_str[1:]
                else:
                    if show_seconds:
                        time_str = now.strftime('%H:%M:%S')
                    else:
                        time_str = now.strftime('%H:%M')
                
                # Calculate starting x position to center the time
                char_count = len(time_str)
                time_width = char_count * 30 - 20
                if clock_format == 12:
                    start_x = (self.display.width - time_width) // 2 - 20
                else:
                    start_x = (self.display.width - time_width) // 2
                
                self.draw_7segment_time(draw, time_str, start_x, 35, fg)
                
                # Draw AM/PM to the right of the time (only for 12-hour format)
                if clock_format == 12:
                    ampm = now.strftime('%p')
                    try:
                        ampm_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
                    except:
                        ampm_font = ImageFont.load_default()
                    draw.text((start_x + time_width + 10, 50), ampm, font=ampm_font, fill=fg)
                
                # Display on screen
                refresh_mode = self.settings_manager.get_setting('refresh_mode', 'partial')
                self.display.show(image, partial=(refresh_mode == 'partial'))
                self.last_update = current_time
            
            # Check for any keypress to go to main menu
            key = self.keyboard.get_key()
            if key:
                return 'main_menu'
            
            # Sleep interval based on show_seconds
            if show_seconds:
                time.sleep(0.5)
            else:
                time.sleep(1)


class MainMenuApp(App):
    """Main menu with 8 app slots (2 rows x 4 columns)"""
    def __init__(self, display, keyboard, notes_manager, settings_manager):
        super().__init__(display, keyboard, notes_manager, settings_manager)
        self.selected = 0  # 0-7 for the 8 apps
        
        # Define apps (icons will be drawn graphically)
        self.apps = [
            {'num': 1, 'name': 'Clock', 'icon_type': 'clock'},
            {'num': 2, 'name': 'Notes', 'icon_type': 'notes'},
            {'num': 3, 'name': '?', 'icon_type': 'placeholder'},
            {'num': 4, 'name': '?', 'icon_type': 'placeholder'},
            {'num': 5, 'name': '?', 'icon_type': 'placeholder'},
            {'num': 6, 'name': '?', 'icon_type': 'placeholder'},
            {'num': 7, 'name': 'Weather', 'icon_type': 'weather'},
            {'num': 8, 'name': 'Settings', 'icon_type': 'settings'},
        ]
    
    def draw_clock_icon(self, draw, x, y, size=20, fill=0):
        """Draw a simple clock icon"""
        center_x = x + size // 2
        center_y = y + size // 2
        radius = size // 2
        
        # Clock circle
        draw.ellipse([x, y, x + size, y + size], outline=fill, width=2)
        
        # Hour hand (pointing to 3)
        draw.line([center_x, center_y, center_x + radius - 5, center_y], fill=fill, width=2)
        
        # Minute hand (pointing to 12)
        draw.line([center_x, center_y, center_x, center_y - radius + 3], fill=fill, width=2)
    
    def draw_notes_icon(self, draw, x, y, size=20, fill=0):
        """Draw a simple notepad/paper icon"""
        # Paper outline
        draw.rectangle([x, y, x + size, y + size + 4], outline=fill, width=2)
        
        # Lines on paper
        line_y = y + 6
        for i in range(3):
            draw.line([x + 3, line_y, x + size - 3, line_y], fill=fill, width=1)
            line_y += 5
    
    def draw_weather_icon(self, draw, x, y, size=20, fill=0):
        """Draw a cloud/sun weather icon"""
        # Sun rays
        center_x = x + size // 2
        center_y = y + size // 2
        ray_length = 3
        draw.line([center_x - size//3, center_y - size//3, center_x - size//3 - ray_length, center_y - size//3 - ray_length], fill=fill, width=1)
        draw.line([center_x + size//3, center_y - size//3, center_x + size//3 + ray_length, center_y - size//3 - ray_length], fill=fill, width=1)
        
        # Cloud
        draw.ellipse([x, y + size//3, x + size//2, y + size//2 + size//3], outline=fill, width=2)
        draw.ellipse([x + size//3, y + size//4, x + size - size//6, y + size//2 + size//3], outline=fill, width=2)
    
    def draw_settings_icon(self, draw, x, y, size=20, fill=0):
        """Draw a cog/gear settings icon"""
        center_x = x + size // 2
        center_y = y + size // 2
        inner_radius = size // 4
        outer_radius = size // 2
        
        # Draw simplified cog with 6 teeth
        import math
        for i in range(6):
            angle = i * 60 * math.pi / 180
            # Outer tooth
            x1 = center_x + int(outer_radius * math.cos(angle))
            y1 = center_y + int(outer_radius * math.sin(angle))
            x2 = center_x + int(inner_radius * math.cos(angle))
            y2 = center_y + int(inner_radius * math.sin(angle))
            draw.line([x2, y2, x1, y1], fill=fill, width=2)
        
        # Center circle
        draw.ellipse([center_x - inner_radius, center_y - inner_radius, 
                     center_x + inner_radius, center_y + inner_radius], outline=fill, width=2)
        # Outer circle
        draw.ellipse([center_x - outer_radius + 2, center_y - outer_radius + 2,
                     center_x + outer_radius - 2, center_y + outer_radius - 2], outline=fill, width=1)
    
    def draw_placeholder_icon(self, draw, x, y, size=20, fill=0):
        """Draw a question mark icon"""
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        except:
            fnt = ImageFont.load_default()
        
        draw.text((x, y), "?", font=fnt, fill=fill)
    
    def draw_menu(self):
        """Draw the main menu"""
        image, fg = self.create_image()
        draw = ImageDraw.Draw(image)
        
        # Title
        self.draw_text_centered(draw, "MAIN MENU", 2, None, 14, fg)
        
        # Draw grid (2 rows x 4 cols)
        cell_width = self.display.width // 4
        cell_height = (self.display.height - 20) // 2
        
        for i, app in enumerate(self.apps):
            row = i // 4
            col = i % 4
            
            x = col * cell_width
            y = 20 + row * cell_height
            
            # Highlight selected app
            if i == self.selected:
                draw.rectangle([x+2, y+2, x+cell_width-2, y+cell_height-2], outline=fg, width=2)
            
            # Draw app number
            try:
                fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            except:
                fnt = ImageFont.load_default()
            
            draw.text((x+5, y+5), str(app['num']), font=fnt, fill=fg)
            
            # Draw app icon in center
            icon_size = 20
            icon_x = x + (cell_width - icon_size) // 2
            icon_y = y + (cell_height - icon_size) // 2 - 5
            
            if app['icon_type'] == 'clock':
                self.draw_clock_icon(draw, icon_x, icon_y, icon_size, fg)
            elif app['icon_type'] == 'notes':
                self.draw_notes_icon(draw, icon_x, icon_y, icon_size, fg)
            elif app['icon_type'] == 'weather':
                self.draw_weather_icon(draw, icon_x, icon_y, icon_size, fg)
            elif app['icon_type'] == 'settings':
                self.draw_settings_icon(draw, icon_x, icon_y, icon_size, fg)
            else:
                self.draw_placeholder_icon(draw, icon_x, icon_y, icon_size, fg)
        
        self.display.show(image)
    
    def run(self):
        """Main menu loop"""
        self.draw_menu()
        
        while self.running:
            key = self.keyboard.get_key()
            
            if not key:
                time.sleep(0.1)
                continue
            
            # Handle WASD navigation
            if key == 'w':
                if self.selected >= 4:
                    self.selected -= 4
                    self.draw_menu()
            elif key == 's':
                if self.selected < 4:
                    self.selected += 4
                    self.draw_menu()
            elif key == 'a':
                if self.selected % 4 != 0:
                    self.selected -= 1
                    self.draw_menu()
            elif key == 'd':
                if self.selected % 4 != 3:
                    self.selected += 1
                    self.draw_menu()
            
            # Handle number key direct selection
            elif key in '12345678':
                self.selected = int(key) - 1
                self.draw_menu()
            
            # Handle Enter key to launch app
            elif key == 'ENTER':
                app_num = self.selected + 1
                if app_num == 1:
                    return 'clock'
                elif app_num == 2:
                    return 'notes_menu'
                elif app_num == 7:
                    return 'weather'
                elif app_num == 8:
                    return 'settings'
                else:
                    # Placeholder apps - show message
                    image, fg = self.create_image()
                    draw = ImageDraw.Draw(image)
                    self.draw_text_centered(draw, f"App {app_num}", 40, None, 16, fg)
                    self.draw_text_centered(draw, "Coming Soon!", 65, None, 14, fg)
                    self.display.show(image)
                    time.sleep(2)
                    self.draw_menu()
            
            # ESC to go back to clock
            elif key == 'ESC':
                return 'clock'


class NotesMenuApp(App):
    """Notes app menu"""
    def __init__(self, display, keyboard, notes_manager, settings_manager):
        super().__init__(display, keyboard, notes_manager, settings_manager)
        self.selected = 0
        self.options = [
            '1. Create New Note',
            '2. View/Edit Notes'
        ]
    
    def draw_menu(self):
        """Draw notes menu"""
        image, fg = self.create_image()
        draw = ImageDraw.Draw(image)
        
        self.draw_text_centered(draw, "NOTES", 5, None, 16, fg)
        
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            fnt = ImageFont.load_default()
        
        for i, option in enumerate(self.options):
            y = 35 + i * 30
            
            # Highlight selected
            if i == self.selected:
                draw.text((10, y), '>', font=fnt, fill=fg)
            
            draw.text((25, y), option, font=fnt, fill=fg)
        
        self.display.show(image)
    
    def run(self):
        """Notes menu loop"""
        self.draw_menu()
        
        while self.running:
            key = self.keyboard.get_key()
            
            if not key:
                time.sleep(0.1)
                continue
            
            if key == 'w' and self.selected > 0:
                self.selected -= 1
                self.draw_menu()
            elif key == 's' and self.selected < len(self.options) - 1:
                self.selected += 1
                self.draw_menu()
            elif key in '12':
                self.selected = int(key) - 1
                self.draw_menu()
            elif key == 'ENTER':
                if self.selected == 0:
                    return 'create_note'
                else:
                    return 'view_notes'
            elif key == 'ESC':
                return 'main_menu'


class CreateNoteApp(App):
    """Create a new note"""
    def __init__(self, display, keyboard, notes_manager, settings_manager):
        super().__init__(display, keyboard, notes_manager, settings_manager)
    
    def get_text_input(self, prompt, max_length=50):
        """Get text input from keyboard"""
        text = ""
        
        while True:
            # Draw input screen
            image, fg = self.create_image()
            draw = ImageDraw.Draw(image)
            
            try:
                fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except:
                fnt = ImageFont.load_default()
            
            draw.text((5, 5), prompt, font=fnt, fill=fg)
            
            # Show current text with cursor
            display_text = text + "_"
            # Wrap text if too long
            if len(display_text) > 30:
                line1 = display_text[:30]
                line2 = display_text[30:60]
                draw.text((5, 30), line1, font=fnt, fill=fg)
                draw.text((5, 45), line2, font=fnt, fill=fg)
            else:
                draw.text((5, 30), display_text, font=fnt, fill=fg)
            
            # Bottom instructions - split left and right
            draw.text((5, 105), "ENTER=Done", font=fnt, fill=fg)
            draw.text((165, 105), "ESC=Cancel", font=fnt, fill=fg)
            
            self.display.show(image)
            
            # Wait for key
            while True:
                key = self.keyboard.get_key()
                if key:
                    break
                time.sleep(0.05)
            
            if key == 'ENTER':
                return text
            elif key == 'ESC':
                return None
            elif key == 'BACKSPACE' and len(text) > 0:
                text = text[:-1]
            elif key and len(key) == 1 and len(text) < max_length:
                text += key
    
    def run(self):
        """Create note flow"""
        # Get title
        title = self.get_text_input("Note Title:", 40)
        if title is None:
            return 'notes_menu'
        
        # Get content
        content = self.get_text_input("Note Content:", 200)
        if content is None:
            return 'notes_menu'
        
        # Save note
        self.notes_manager.create_note(title, content)
        
        # Show success message
        image, fg = self.create_image()
        draw = ImageDraw.Draw(image)
        self.draw_text_centered(draw, "Note Saved!", 50, None, 16, fg)
        self.display.show(image)
        time.sleep(1.5)
        
        return 'notes_menu'


class ViewNotesApp(App):
    """View and edit notes list"""
    def __init__(self, display, keyboard, notes_manager, settings_manager):
        super().__init__(display, keyboard, notes_manager, settings_manager)
        self.selected = 0
        self.scroll_offset = 0
    
    def draw_notes_list(self):
        """Draw list of notes"""
        notes = self.notes_manager.get_notes()
        
        image, fg = self.create_image()
        draw = ImageDraw.Draw(image)
        
        if not notes:
            self.draw_text_centered(draw, "No notes yet", 50, None, 14, fg)
            self.display.show(image)
            return
        
        self.draw_text_centered(draw, "YOUR NOTES", 2, None, 12, fg)
        
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        except:
            fnt = ImageFont.load_default()
        
        # Show up to 5 notes at a time
        visible_notes = 5
        start_idx = self.scroll_offset
        end_idx = min(start_idx + visible_notes, len(notes))
        
        for i in range(start_idx, end_idx):
            note = notes[i]
            y = 20 + (i - start_idx) * 18
            
            # Highlight selected
            if i == self.selected:
                draw.text((5, y), '>', font=fnt, fill=fg)
            
            # Truncate title if too long
            title = note['title']
            if len(title) > 25:
                title = title[:22] + "..."
            
            draw.text((15, y), f"{i+1}. {title}", font=fnt, fill=fg)
        
        # Show scroll indicators
        if start_idx > 0:
            draw.text((230, 20), "^", font=fnt, fill=fg)
        if end_idx < len(notes):
            draw.text((230, 95), "v", font=fnt, fill=fg)
        
        draw.text((5, 105), "ENTER=View ESC=Back", font=fnt, fill=fg)
        
        self.display.show(image)
    
    def view_note(self, note):
        """Display a single note"""
        while True:
            image, fg = self.create_image()
            draw = ImageDraw.Draw(image)
            
            try:
                fnt_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
                fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            except:
                fnt_title = fnt = ImageFont.load_default()
            
            # Title
            title = note['title']
            if len(title) > 30:
                title = title[:27] + "..."
            draw.text((5, 2), title, font=fnt_title, fill=fg)
            
            # Content (wrap text)
            content = note['content']
            y = 18
            line_height = 12
            chars_per_line = 35
            
            for i in range(0, len(content), chars_per_line):
                if y > 90:
                    draw.text((5, y), "...", font=fnt, fill=fg)
                    break
                line = content[i:i+chars_per_line]
                draw.text((5, y), line, font=fnt, fill=fg)
                y += line_height
            
            draw.text((5, 108), "ESC=Back", font=fnt, fill=fg)
            
            self.display.show(image)
            
            # Wait for ESC
            while True:
                key = self.keyboard.get_key()
                if key == 'ESC':
                    return
                time.sleep(0.1)
    
    def run(self):
        """View notes loop"""
        notes = self.notes_manager.get_notes()
        
        if not notes:
            # Show empty message
            image, fg = self.create_image()
            draw = ImageDraw.Draw(image)
            self.draw_text_centered(draw, "No notes yet", 45, None, 14, fg)
            self.draw_text_centered(draw, "Press ESC to go back", 70, None, 12, fg)
            self.display.show(image)
            
            while True:
                key = self.keyboard.get_key()
                if key == 'ESC':
                    return 'notes_menu'
                time.sleep(0.1)
        
        self.draw_notes_list()
        
        while self.running:
            key = self.keyboard.get_key()
            
            if not key:
                time.sleep(0.1)
                continue
            
            if key == 'w' and self.selected > 0:
                self.selected -= 1
                if self.selected < self.scroll_offset:
                    self.scroll_offset = self.selected
                self.draw_notes_list()
            elif key == 's' and self.selected < len(notes) - 1:
                self.selected += 1
                if self.selected >= self.scroll_offset + 5:
                    self.scroll_offset = self.selected - 4
                self.draw_notes_list()
            elif key.isdigit():
                num = int(key)
                if 1 <= num <= len(notes):
                    self.selected = num - 1
                    self.draw_notes_list()
            elif key == 'ENTER':
                note = notes[self.selected]
                self.view_note(note)
                self.draw_notes_list()
            elif key == 'ESC':
                return 'notes_menu'


class WeatherApp(App):
    """Display weather information"""
    def __init__(self, display, keyboard, notes_manager, settings_manager):
        super().__init__(display, keyboard, notes_manager, settings_manager)
    
    def get_weather(self, zip_code):
        """Fetch weather data from wttr.in"""
        try:
            # Using wttr.in - no API key needed
            url = f"http://wttr.in/{zip_code}?format=j1"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Weather fetch error: {e}")
        return None
    
    def run(self):
        """Display weather"""
        zip_code = self.settings_manager.get_setting('zip_code', '')
        
        if not zip_code:
            # No zip code set
            image, fg = self.create_image()
            draw = ImageDraw.Draw(image)
            self.draw_text_centered(draw, "No ZIP Code Set", 30, None, 14, fg)
            self.draw_text_centered(draw, "Configure in Settings", 55, None, 12, fg)
            self.draw_text_centered(draw, "Press ESC to go back", 80, None, 10, fg)
            self.display.show(image)
            
            while True:
                key = self.keyboard.get_key()
                if key == 'ESC':
                    return 'main_menu'
                time.sleep(0.1)
        
        # Show loading message
        image, fg = self.create_image()
        draw = ImageDraw.Draw(image)
        self.draw_text_centered(draw, "Loading Weather...", 50, None, 14, fg)
        self.display.show(image)
        
        # Fetch weather
        weather_data = self.get_weather(zip_code)
        
        if not weather_data:
            # Error fetching weather
            image, fg = self.create_image()
            draw = ImageDraw.Draw(image)
            self.draw_text_centered(draw, "Weather Error", 30, None, 14, fg)
            self.draw_text_centered(draw, "Check connection/ZIP", 55, None, 11, fg)
            self.draw_text_centered(draw, "Press ESC to go back", 80, None, 10, fg)
            self.display.show(image)
            
            while True:
                key = self.keyboard.get_key()
                if key == 'ESC':
                    return 'main_menu'
                time.sleep(0.1)
        
        # Display weather
        while True:
            image, fg = self.create_image()
            draw = ImageDraw.Draw(image)
            
            try:
                fnt_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
                fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            except:
                fnt_title = fnt = ImageFont.load_default()
            
            # Parse weather data
            current = weather_data['current_condition'][0]
            today = weather_data['weather'][0]
            
            # Title
            location = weather_data['nearest_area'][0]['areaName'][0]['value']
            draw.text((5, 2), f"Weather: {location}", font=fnt_title, fill=fg)
            
            # Current conditions
            temp_f = current['temp_F']
            feels_like = current['FeelsLikeF']
            condition = current['weatherDesc'][0]['value']
            humidity = current['humidity']
            wind_mph = current['windspeedMiles']
            
            y = 20
            draw.text((5, y), f"Now: {temp_f}F (feels {feels_like}F)", font=fnt, fill=fg)
            y += 12
            draw.text((5, y), f"{condition}", font=fnt, fill=fg)
            y += 12
            draw.text((5, y), f"Humidity: {humidity}%", font=fnt, fill=fg)
            y += 12
            draw.text((5, y), f"Wind: {wind_mph} mph", font=fnt, fill=fg)
            
            # Today's forecast
            y += 15
            high = today['maxtempF']
            low = today['mintempF']
            draw.text((5, y), f"Today: High {high}F / Low {low}F", font=fnt, fill=fg)
            
            # Tomorrow's forecast
            if len(weather_data['weather']) > 1:
                tomorrow = weather_data['weather'][1]
                y += 12
                tom_high = tomorrow['maxtempF']
                tom_low = tomorrow['mintempF']
                tom_cond = tomorrow['hourly'][4]['weatherDesc'][0]['value']
                draw.text((5, y), f"Tomorrow: {tom_high}F/{tom_low}F", font=fnt, fill=fg)
            
            draw.text((5, 108), "ESC=Back", font=fnt, fill=fg)
            
            self.display.show(image)
            
            # Wait for ESC
            key = self.keyboard.get_key()
            if key == 'ESC':
                return 'main_menu'
            time.sleep(0.1)


class SettingsApp(App):
    """Settings menu"""
    def __init__(self, display, keyboard, notes_manager, settings_manager):
        super().__init__(display, keyboard, notes_manager, settings_manager)
        self.selected = 0
        self.options = [
            'Dark/Light Mode',
            'Clock Format',
            'Date Format',
            'Refresh Mode',
            'Auto-Sleep Timer',
            'Show Seconds',
            'ZIP Code',
            'Display Info',
            'Factory Reset'
        ]
    
    def draw_menu(self):
        """Draw settings menu"""
        image, fg = self.create_image()
        draw = ImageDraw.Draw(image)
        
        self.draw_text_centered(draw, "SETTINGS", 2, None, 14, fg)
        
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        except:
            fnt = ImageFont.load_default()
        
        # Show settings with current values
        start_idx = max(0, self.selected - 4)
        end_idx = min(len(self.options), start_idx + 6)
        
        for i in range(start_idx, end_idx):
            y = 20 + (i - start_idx) * 15
            
            # Highlight selected
            prefix = '>' if i == self.selected else ' '
            
            # Get current value
            option = self.options[i]
            value = ""
            
            if option == 'Dark/Light Mode':
                value = "Dark" if self.settings_manager.get_setting('dark_mode', True) else "Light"
            elif option == 'Clock Format':
                value = f"{self.settings_manager.get_setting('clock_format', 12)}hr"
            elif option == 'Date Format':
                value = self.settings_manager.get_setting('date_format', 'long').capitalize()
            elif option == 'Refresh Mode':
                value = self.settings_manager.get_setting('refresh_mode', 'partial').capitalize()
            elif option == 'Auto-Sleep Timer':
                mins = self.settings_manager.get_setting('auto_sleep', 0)
                value = "Never" if mins == 0 else f"{mins}m"
            elif option == 'Show Seconds':
                value = "On" if self.settings_manager.get_setting('show_seconds', False) else "Off"
            elif option == 'ZIP Code':
                zip_code = self.settings_manager.get_setting('zip_code', '')
                value = zip_code if zip_code else "Not Set"
            
            text = f"{prefix}{i+1}. {option}: {value}"
            if len(text) > 38:
                text = text[:35] + "..."
            draw.text((5, y), text, font=fnt, fill=fg)
        
        draw.text((5, 108), "ENTER=Edit ESC=Back", font=fnt, fill=fg)
        
        self.display.show(image)
    
    def toggle_setting(self, setting_name):
        """Toggle or edit a setting"""
        if setting_name == 'Dark/Light Mode':
            current = self.settings_manager.get_setting('dark_mode', True)
            self.settings_manager.set_setting('dark_mode', not current)
        
        elif setting_name == 'Clock Format':
            current = self.settings_manager.get_setting('clock_format', 12)
            self.settings_manager.set_setting('clock_format', 24 if current == 12 else 12)
        
        elif setting_name == 'Date Format':
            formats = ['long', 'short', 'iso']
            current = self.settings_manager.get_setting('date_format', 'long')
            idx = formats.index(current) if current in formats else 0
            next_idx = (idx + 1) % len(formats)
            self.settings_manager.set_setting('date_format', formats[next_idx])
        
        elif setting_name == 'Refresh Mode':
            current = self.settings_manager.get_setting('refresh_mode', 'partial')
            self.settings_manager.set_setting('refresh_mode', 'full' if current == 'partial' else 'partial')
        
        elif setting_name == 'Auto-Sleep Timer':
            timers = [0, 5, 10, 30, 60]
            current = self.settings_manager.get_setting('auto_sleep', 0)
            idx = timers.index(current) if current in timers else 0
            next_idx = (idx + 1) % len(timers)
            self.settings_manager.set_setting('auto_sleep', timers[next_idx])
        
        elif setting_name == 'Show Seconds':
            current = self.settings_manager.get_setting('show_seconds', False)
            self.settings_manager.set_setting('show_seconds', not current)
        
        elif setting_name == 'ZIP Code':
            # Get ZIP code input
            zip_code = self.get_text_input("Enter ZIP Code:", 10)
            if zip_code:
                self.settings_manager.set_setting('zip_code', zip_code)
        
        elif setting_name == 'Display Info':
            self.show_display_info()
        
        elif setting_name == 'Factory Reset':
            self.factory_reset()
    
    def get_text_input(self, prompt, max_length=50):
        """Get text input from keyboard"""
        text = ""
        
        while True:
            image, fg = self.create_image()
            draw = ImageDraw.Draw(image)
            
            try:
                fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except:
                fnt = ImageFont.load_default()
            
            draw.text((5, 5), prompt, font=fnt, fill=fg)
            display_text = text + "_"
            draw.text((5, 30), display_text, font=fnt, fill=fg)
            draw.text((5, 105), "ENTER=Done", font=fnt, fill=fg)
            draw.text((165, 105), "ESC=Cancel", font=fnt, fill=fg)
            
            self.display.show(image)
            
            while True:
                key = self.keyboard.get_key()
                if key:
                    break
                time.sleep(0.05)
            
            if key == 'ENTER':
                return text
            elif key == 'ESC':
                return None
            elif key == 'BACKSPACE' and len(text) > 0:
                text = text[:-1]
            elif key and len(key) == 1 and len(text) < max_length:
                text += key
    
    def show_display_info(self):
        """Show system information"""
        image, fg = self.create_image()
        draw = ImageDraw.Draw(image)
        
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        except:
            fnt = ImageFont.load_default()
        
        self.draw_text_centered(draw, "DISPLAY INFO", 2, None, 14, fg)
        
        y = 25
        # Resolution
        draw.text((5, y), f"Resolution: {self.display.width}x{self.display.height}", font=fnt, fill=fg)
        y += 15
        
        # Number of notes
        note_count = len(self.notes_manager.get_notes())
        draw.text((5, y), f"Notes Saved: {note_count}", font=fnt, fill=fg)
        y += 15
        
        # Demo mode
        mode = "Demo Mode" if self.display.demo_mode else "Hardware Mode"
        draw.text((5, y), f"Display: {mode}", font=fnt, fill=fg)
        y += 15
        
        # Uptime (simplified)
        draw.text((5, y), f"Python: {sys.version.split()[0]}", font=fnt, fill=fg)
        
        draw.text((5, 108), "ESC=Back", font=fnt, fill=fg)
        
        self.display.show(image)
        
        while True:
            key = self.keyboard.get_key()
            if key == 'ESC':
                return
            time.sleep(0.1)
    
    def factory_reset(self):
        """Confirm and perform factory reset"""
        image, fg = self.create_image()
        draw = ImageDraw.Draw(image)
        
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        except:
            fnt = ImageFont.load_default()
        
        self.draw_text_centered(draw, "FACTORY RESET?", 20, None, 14, fg)
        draw.text((15, 50), "This will delete ALL notes", font=fnt, fill=fg)
        draw.text((15, 65), "and reset all settings!", font=fnt, fill=fg)
        draw.text((5, 95), "ENTER=Confirm", font=fnt, fill=fg)
        draw.text((150, 95), "ESC=Cancel", font=fnt, fill=fg)
        
        self.display.show(image)
        
        while True:
            key = self.keyboard.get_key()
            if key == 'ENTER':
                # Perform reset
                self.notes_manager.notes = []
                self.notes_manager._save_notes()
                self.settings_manager.reset_to_defaults()
                
                # Show confirmation
                image, fg = self.create_image()
                draw = ImageDraw.Draw(image)
                self.draw_text_centered(draw, "Reset Complete!", 50, None, 14, fg)
                self.display.show(image)
                time.sleep(2)
                return
            elif key == 'ESC':
                return
            time.sleep(0.1)
    
    def run(self):
        """Settings menu loop"""
        self.draw_menu()
        
        while self.running:
            key = self.keyboard.get_key()
            
            if not key:
                time.sleep(0.1)
                continue
            
            if key == 'w' and self.selected > 0:
                self.selected -= 1
                self.draw_menu()
            elif key == 's' and self.selected < len(self.options) - 1:
                self.selected += 1
                self.draw_menu()
            elif key.isdigit():
                num = int(key)
                if 1 <= num <= len(self.options):
                    self.selected = num - 1
                    self.draw_menu()
            elif key == 'ENTER':
                self.toggle_setting(self.options[self.selected])
                self.draw_menu()
            elif key == 'ESC':
                return 'main_menu'


def main():
    """Main application loop"""
    print("Starting E-ink Clock & Menu System...")
    print("Press any key while clock is showing to access Main Menu")
    
    # Initialize components
    settings_manager = SettingsManager()
    display = Display(settings_manager)
    keyboard = KeyboardInput()
    notes_manager = NotesManager()
    
    # Start with clock
    current_app = 'clock'
    
    try:
        while True:
            if current_app == 'clock':
                app = ClockApp(display, keyboard, notes_manager, settings_manager)
                current_app = app.run()
            elif current_app == 'main_menu':
                app = MainMenuApp(display, keyboard, notes_manager, settings_manager)
                current_app = app.run()
            elif current_app == 'notes_menu':
                app = NotesMenuApp(display, keyboard, notes_manager, settings_manager)
                current_app = app.run()
            elif current_app == 'create_note':
                app = CreateNoteApp(display, keyboard, notes_manager, settings_manager)
                current_app = app.run()
            elif current_app == 'view_notes':
                app = ViewNotesApp(display, keyboard, notes_manager, settings_manager)
                current_app = app.run()
            elif current_app == 'weather':
                app = WeatherApp(display, keyboard, notes_manager, settings_manager)
                current_app = app.run()
            elif current_app == 'settings':
                app = SettingsApp(display, keyboard, notes_manager, settings_manager)
                current_app = app.run()
            
            # Small delay between app transitions
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        keyboard.stop()
        display.sleep()
        print("Goodbye!")


if __name__ == '__main__':
    main()
