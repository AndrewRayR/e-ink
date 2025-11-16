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
    def __init__(self):
        self.width = 250  # Landscape
        self.height = 122
        self.epd = None
        self.demo_mode = epd2in13_V4 is None
        
        if not self.demo_mode:
            try:
                self.epd = epd2in13_V4.EPD()
                self.epd.init()
                self.epd.Clear(0xFF)
            except Exception as e:
                print(f"Display init error: {e}. Running in demo mode.")
                self.demo_mode = True
    
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
    def __init__(self, display, keyboard, notes_manager):
        self.display = display
        self.keyboard = keyboard
        self.notes_manager = notes_manager
        self.running = True
    
    def draw_text_centered(self, draw, text, y, font, size=20):
        """Draw centered text"""
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        except:
            fnt = ImageFont.load_default()
        
        bbox = draw.textbbox((0, 0), text, font=fnt)
        text_width = bbox[2] - bbox[0]
        x = (self.display.width - text_width) // 2
        draw.text((x, y), text, font=fnt, fill=0)
    
    def run(self):
        """Override this method in subclasses"""
        pass


class ClockApp(App):
    """Digital clock display with 7-segment style font"""
    def __init__(self, display, keyboard, notes_manager):
        super().__init__(display, keyboard, notes_manager)
        self.last_minute = None
    
    def draw_7segment_digit(self, draw, digit, x, y, seg_width=4, seg_length=20):
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
            draw.rectangle([x+w, y, x+w+l, y+w], fill=0)
        # b (top right)
        if seg[1]:
            draw.rectangle([x+w+l, y+w, x+w+l+w, y+w+l], fill=0)
        # c (bottom right)
        if seg[2]:
            draw.rectangle([x+w+l, y+w+l+w, x+w+l+w, y+w+l+w+l], fill=0)
        # d (bottom)
        if seg[3]:
            draw.rectangle([x+w, y+w+l+w+l, x+w+l, y+w+l+w+l+w], fill=0)
        # e (bottom left)
        if seg[4]:
            draw.rectangle([x, y+w+l+w, x+w, y+w+l+w+l], fill=0)
        # f (top left)
        if seg[5]:
            draw.rectangle([x, y+w, x+w, y+w+l], fill=0)
        # g (middle)
        if seg[6]:
            draw.rectangle([x+w, y+w+l, x+w+l, y+w+l+w], fill=0)
    
    def draw_7segment_time(self, draw, time_str, x, y):
        """Draw time string with 7-segment digits"""
        digit_width = 30
        colon_width = 10
        
        current_x = x
        for char in time_str:
            if char == ':':
                # Draw colon
                draw.rectangle([current_x+3, y+15, current_x+7, y+19], fill=0)
                draw.rectangle([current_x+3, y+35, current_x+7, y+39], fill=0)
                current_x += colon_width
            else:
                self.draw_7segment_digit(draw, char, current_x, y)
                current_x += digit_width
    
    def run(self):
        """Main clock loop"""
        while self.running:
            now = datetime.now()
            current_minute = now.strftime('%H:%M')
            
            # Only update display when minute changes
            if current_minute != self.last_minute:
                image = Image.new('1', (self.display.width, self.display.height), 255)
                draw = ImageDraw.Draw(image)
                
                # Draw date at top
                date_str = now.strftime('%a, %b %d, %Y')
                self.draw_text_centered(draw, date_str, 5, None, 14)
                
                # Draw time with 7-segment display
                time_str = now.strftime('%I:%M')
                # Remove leading zero from hour
                if time_str[0] == '0':
                    time_str = ' ' + time_str[1:]
                
                # Calculate starting x position to center the time
                time_width = len(time_str) * 30 - 20  # Rough calculation
                start_x = (self.display.width - time_width) // 2
                self.draw_7segment_time(draw, time_str, start_x, 35)
                
                # Draw AM/PM
                ampm = now.strftime('%p')
                self.draw_text_centered(draw, ampm, 95, None, 16)
                
                # Display on screen (partial refresh)
                self.display.show(image, partial=True)
                self.last_minute = current_minute
            
            # Check for any keypress to go to main menu
            key = self.keyboard.get_key()
            if key:
                return 'main_menu'
            
            time.sleep(1)


class MainMenuApp(App):
    """Main menu with 8 app slots (2 rows x 4 columns)"""
    def __init__(self, display, keyboard, notes_manager):
        super().__init__(display, keyboard, notes_manager)
        self.selected = 0  # 0-7 for the 8 apps
        
        # Define apps
        self.apps = [
            {'num': 1, 'name': 'Clock', 'icon': '⏰'},
            {'num': 2, 'name': 'Notes', 'icon': '📝'},
            {'num': 3, 'name': '?', 'icon': '?'},
            {'num': 4, 'name': '?', 'icon': '?'},
            {'num': 5, 'name': '?', 'icon': '?'},
            {'num': 6, 'name': '?', 'icon': '?'},
            {'num': 7, 'name': '?', 'icon': '?'},
            {'num': 8, 'name': '?', 'icon': '?'},
        ]
    
    def draw_menu(self):
        """Draw the main menu"""
        image = Image.new('1', (self.display.width, self.display.height), 255)
        draw = ImageDraw.Draw(image)
        
        # Title
        self.draw_text_centered(draw, "MAIN MENU", 2, None, 14)
        
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
                draw.rectangle([x+2, y+2, x+cell_width-2, y+cell_height-2], outline=0, width=2)
            
            # Draw app number
            try:
                fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
            except:
                fnt = ImageFont.load_default()
            
            draw.text((x+5, y+5), str(app['num']), font=fnt, fill=0)
            
            # Draw app name
            try:
                fnt_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
            except:
                fnt_name = ImageFont.load_default()
            
            # Center the name in the cell
            name = app['name']
            bbox = draw.textbbox((0, 0), name, font=fnt_name)
            text_width = bbox[2] - bbox[0]
            text_x = x + (cell_width - text_width) // 2
            draw.text((text_x, y + cell_height - 20), name, font=fnt_name, fill=0)
        
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
                else:
                    # Placeholder apps - show message
                    image = Image.new('1', (self.display.width, self.display.height), 255)
                    draw = ImageDraw.Draw(image)
                    self.draw_text_centered(draw, f"App {app_num}", 40, None, 16)
                    self.draw_text_centered(draw, "Coming Soon!", 65, None, 14)
                    self.display.show(image)
                    time.sleep(2)
                    self.draw_menu()
            
            # ESC to go back to clock
            elif key == 'ESC':
                return 'clock'


class NotesMenuApp(App):
    """Notes app menu"""
    def __init__(self, display, keyboard, notes_manager):
        super().__init__(display, keyboard, notes_manager)
        self.selected = 0
        self.options = [
            '1. Create New Note',
            '2. View/Edit Notes'
        ]
    
    def draw_menu(self):
        """Draw notes menu"""
        image = Image.new('1', (self.display.width, self.display.height), 255)
        draw = ImageDraw.Draw(image)
        
        self.draw_text_centered(draw, "NOTES", 5, None, 16)
        
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            fnt = ImageFont.load_default()
        
        for i, option in enumerate(self.options):
            y = 35 + i * 30
            
            # Highlight selected
            if i == self.selected:
                draw.text((10, y), '>', font=fnt, fill=0)
            
            draw.text((25, y), option, font=fnt, fill=0)
        
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
    def __init__(self, display, keyboard, notes_manager):
        super().__init__(display, keyboard, notes_manager)
    
    def get_text_input(self, prompt, max_length=50):
        """Get text input from keyboard"""
        text = ""
        
        while True:
            # Draw input screen
            image = Image.new('1', (self.display.width, self.display.height), 255)
            draw = ImageDraw.Draw(image)
            
            try:
                fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except:
                fnt = ImageFont.load_default()
            
            draw.text((5, 5), prompt, font=fnt, fill=0)
            
            # Show current text with cursor
            display_text = text + "_"
            # Wrap text if too long
            if len(display_text) > 30:
                line1 = display_text[:30]
                line2 = display_text[30:60]
                draw.text((5, 30), line1, font=fnt, fill=0)
                draw.text((5, 45), line2, font=fnt, fill=0)
            else:
                draw.text((5, 30), display_text, font=fnt, fill=0)
            
            draw.text((5, 105), "ENTER=Done ESC=Cancel", font=fnt, fill=0)
            
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
        image = Image.new('1', (self.display.width, self.display.height), 255)
        draw = ImageDraw.Draw(image)
        self.draw_text_centered(draw, "Note Saved!", 50, None, 16)
        self.display.show(image)
        time.sleep(1.5)
        
        return 'notes_menu'


class ViewNotesApp(App):
    """View and edit notes list"""
    def __init__(self, display, keyboard, notes_manager):
        super().__init__(display, keyboard, notes_manager)
        self.selected = 0
        self.scroll_offset = 0
    
    def draw_notes_list(self):
        """Draw list of notes"""
        notes = self.notes_manager.get_notes()
        
        image = Image.new('1', (self.display.width, self.display.height), 255)
        draw = ImageDraw.Draw(image)
        
        if not notes:
            self.draw_text_centered(draw, "No notes yet", 50, None, 14)
            self.display.show(image)
            return
        
        self.draw_text_centered(draw, "YOUR NOTES", 2, None, 12)
        
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
                draw.text((5, y), '>', font=fnt, fill=0)
            
            # Truncate title if too long
            title = note['title']
            if len(title) > 25:
                title = title[:22] + "..."
            
            draw.text((15, y), f"{i+1}. {title}", font=fnt, fill=0)
        
        # Show scroll indicators
        if start_idx > 0:
            draw.text((230, 20), "^", font=fnt, fill=0)
        if end_idx < len(notes):
            draw.text((230, 95), "v", font=fnt, fill=0)
        
        draw.text((5, 105), "ENTER=View ESC=Back", font=fnt, fill=0)
        
        self.display.show(image)
    
    def view_note(self, note):
        """Display a single note"""
        while True:
            image = Image.new('1', (self.display.width, self.display.height), 255)
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
            draw.text((5, 2), title, font=fnt_title, fill=0)
            
            # Content (wrap text)
            content = note['content']
            y = 18
            line_height = 12
            chars_per_line = 35
            
            for i in range(0, len(content), chars_per_line):
                if y > 90:
                    draw.text((5, y), "...", font=fnt, fill=0)
                    break
                line = content[i:i+chars_per_line]
                draw.text((5, y), line, font=fnt, fill=0)
                y += line_height
            
            draw.text((5, 108), "ESC=Back", font=fnt, fill=0)
            
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
            image = Image.new('1', (self.display.width, self.display.height), 255)
            draw = ImageDraw.Draw(image)
            self.draw_text_centered(draw, "No notes yet", 45, None, 14)
            self.draw_text_centered(draw, "Press ESC to go back", 70, None, 12)
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


def main():
    """Main application loop"""
    print("Starting E-ink Clock & Menu System...")
    print("Press any key while clock is showing to access Main Menu")
    
    # Initialize components
    display = Display()
    keyboard = KeyboardInput()
    notes_manager = NotesManager()
    
    # Start with clock
    current_app = 'clock'
    
    try:
        while True:
            if current_app == 'clock':
                app = ClockApp(display, keyboard, notes_manager)
                current_app = app.run()
            elif current_app == 'main_menu':
                app = MainMenuApp(display, keyboard, notes_manager)
                current_app = app.run()
            elif current_app == 'notes_menu':
                app = NotesMenuApp(display, keyboard, notes_manager)
                current_app = app.run()
            elif current_app == 'create_note':
                app = CreateNoteApp(display, keyboard, notes_manager)
                current_app = app.run()
            elif current_app == 'view_notes':
                app = ViewNotesApp(display, keyboard, notes_manager)
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
