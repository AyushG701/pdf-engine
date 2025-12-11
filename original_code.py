
# proper working version

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import fitz  # PyMuPDF
import pytesseract
import io
import sys
import os
from pathlib import Path
import re

# ==========================================
# CONFIGURATION
# ==========================================
TESSERACT_CMD = r'C:\Program Files\Tesseract-OCR\tesseract.exe' if os.name == 'nt' else None

if TESSERACT_CMD and os.path.exists(TESSERACT_CMD):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

class UltimatePDFEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Ultimate PDF Editor (ACORD Optimized)")
        self.root.geometry("1400x900")
        
        # Core State
        self.pdf_path = None
        self.pdf_doc = None
        self.current_page = 0
        self.zoom_level = 1.5
        self.edits = []  # Store edits: {page, rect, old_text, new_text, lines_data, manual_mode}
        
        # Drawing State
        self.selection_active = False
        self.rect_start = None
        self.rect_id = None
        
        self.setup_ui()

    def setup_ui(self):
        # --- Layout ---
        main_container = tk.Frame(self.root, bg="#2c3e50")
        main_container.pack(fill=tk.BOTH, expand=True)

        # --- Sidebar ---
        sidebar = tk.Frame(main_container, width=350, bg="#ecf0f1")
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        sidebar.pack_propagate(False)

        # Header
        tk.Label(sidebar, text="📄 PDF Editor Pro", font=("Segoe UI", 16, "bold"), bg="#ecf0f1", fg="#2c3e50").pack(pady=20)
        
        # Controls
        tk.Button(sidebar, text="📂 Open PDF", command=self.open_pdf, 
                 bg="#3498db", fg="white", font=("Segoe UI", 11), pady=8).pack(fill=tk.X, padx=15, pady=5)
        
        self.btn_select = tk.Button(sidebar, text="Target Text Area", command=self.toggle_selection,
                 bg="#95a5a6", fg="white", font=("Segoe UI", 11), pady=8, state=tk.DISABLED)
        self.btn_select.pack(fill=tk.X, padx=15, pady=5)
        
        # Instructions
        instructions = tk.Label(sidebar, text="Instructions:\n"
                                             "1. Select text area with mouse\n"
                                             "2. Edit text (preserves line breaks)\n"
                                             "3. Add multiple replacements\n"
                                             "4. Save modified PDF",
                               bg="#ecf0f1", justify=tk.LEFT, font=("Segoe UI", 9))
        instructions.pack(pady=15, padx=15, anchor="w")
        
        # Edit Queue
        tk.Label(sidebar, text="Pending Edits:", bg="#ecf0f1", font=("Segoe UI", 10, "bold")).pack(pady=(10,5), padx=15, anchor="w")
        
        # Scrollable frame for listbox
        list_frame = tk.Frame(sidebar)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(list_frame, font=("Consolas", 9), bg="white", 
                                 yscrollcommand=scrollbar.set, height=15, width=40)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)
        
        tk.Button(sidebar, text=" Remove Selected", command=self.remove_edit, bg="#e74c3c", fg="white").pack(fill=tk.X, padx=15, pady=5)

        # Save
        self.btn_save = tk.Button(sidebar, text="💾 Save PDF", command=self.save_pdf,
                 bg="#27ae60", fg="white", font=("Segoe UI", 12, "bold"), pady=10, state=tk.DISABLED)
        self.btn_save.pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=20)

        # --- Viewer Area ---
        viewer_frame = tk.Frame(main_container, bg="#bdc3c7")
        viewer_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = tk.Frame(viewer_frame, bg="#34495e", height=40)
        toolbar.pack(fill=tk.X)
        
        tk.Button(toolbar, text="◀ Prev", command=self.prev_page, bg="#34495e", fg="white", bd=0).pack(side=tk.LEFT, padx=10)
        self.lbl_page = tk.Label(toolbar, text="Page 0/0", bg="#34495e", fg="white")
        self.lbl_page.pack(side=tk.LEFT, padx=10)
        tk.Button(toolbar, text="Next ▶", command=self.next_page, bg="#34495e", fg="white", bd=0).pack(side=tk.LEFT, padx=10)
        
        tk.Button(toolbar, text="🔍+", command=self.zoom_in, bg="#34495e", fg="white", bd=0).pack(side=tk.RIGHT, padx=10)
        tk.Button(toolbar, text="🔍-", command=self.zoom_out, bg="#34495e", fg="white", bd=0).pack(side=tk.RIGHT, padx=10)
        tk.Label(toolbar, text=f"Zoom: {int(self.zoom_level*100)}%", bg="#34495e", fg="white").pack(side=tk.RIGHT, padx=10)

        # Canvas with Scrollbars
        self.canvas_frame = tk.Frame(viewer_frame)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        v_scroll = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL)
        h_scroll = tk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL)
        
        self.canvas = tk.Canvas(self.canvas_frame, bg="#7f8c8d",
                              yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set,
                              cursor="arrow")
        
        v_scroll.config(command=self.canvas.yview)
        h_scroll.config(command=self.canvas.xview)
        
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Events
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)

    # ================= Logic =================

    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if path:
            self.pdf_path = path
            self.pdf_doc = fitz.open(path)
            self.current_page = 0
            self.edits = []
            self.listbox.delete(0, tk.END)
            self.btn_select.config(state=tk.NORMAL)
            self.btn_save.config(state=tk.DISABLED)
            self.render_page()

    def render_page(self):
        if not self.pdf_doc: return
        
        page = self.pdf_doc[self.current_page]
        mat = fitz.Matrix(self.zoom_level, self.zoom_level)
        pix = page.get_pixmap(matrix=mat)
        
        # Convert to PIL
        img_data = pix.tobytes("png")  # Use png instead of ppm for better quality
        img = Image.open(io.BytesIO(img_data))
        self.photo = ImageTk.PhotoImage(img)
        
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.canvas.config(scrollregion=self.canvas.bbox(tk.ALL))
        self.lbl_page.config(text=f"Page {self.current_page + 1} of {len(self.pdf_doc)}")
        
        # Redraw edit boxes with proper multi-line indicators
        for edit in self.edits:
            if edit['page'] == self.current_page:
                r = edit['rect']
                # Scale rect to zoom
                x0, y0, x1, y1 = [c * self.zoom_level for c in r]
                color = "red" if edit.get('manual_mode', False) else "#3498db"
                width = 3 if edit.get('multi_line', False) else 2
                
                # Draw the selection rectangle
                self.canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=width)
                
                # Add line indicators for multi-line edits
                if edit.get('multi_line', False) and 'lines_data' in edit:
                    for line in edit['lines_data']:
                        ly0 = (line['y0'] + 2) * self.zoom_level
                        ly1 = (line['y1'] - 2) * self.zoom_level
                        self.canvas.create_line(x0, ly0, x1, ly0, fill=color, dash=(2,2))
                        self.canvas.create_line(x0, ly1, x1, ly1, fill=color, dash=(2,2))

    def toggle_selection(self):
        self.selection_active = not self.selection_active
        if self.selection_active:
            self.btn_select.config(bg="#e67e22", text="Cancel Selection")
            self.canvas.config(cursor="cross")
        else:
            self.btn_select.config(bg="#95a5a6", text="Target Text Area")
            self.canvas.config(cursor="arrow")
            if self.rect_id:
                self.canvas.delete(self.rect_id)
                self.rect_id = None
                self.rect_start = None

    def on_mouse_down(self, event):
        if not self.selection_active: return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        self.rect_start = (x, y)
        if self.rect_id: self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(x, y, x, y, outline="#2980b9", width=2, dash=(4,4))

    def on_mouse_drag(self, event):
        if not self.selection_active or not self.rect_start: return
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect_id, self.rect_start[0], self.rect_start[1], cur_x, cur_y)

    def on_mouse_up(self, event):
        if not self.selection_active or not self.rect_start: return
        
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        
        # Convert canvas coords to PDF coords
        x0 = min(self.rect_start[0], end_x) / self.zoom_level
        y0 = min(self.rect_start[1], end_y) / self.zoom_level
        x1 = max(self.rect_start[0], end_x) / self.zoom_level
        y1 = max(self.rect_start[1], end_y) / self.zoom_level

        # Don't register tiny accidental clicks
        if abs(x1 - x0) < 5 or abs(y1 - y0) < 5:
            self.canvas.delete(self.rect_id)
            self.toggle_selection()
            return

        rect = fitz.Rect(x0, y0, x1, y1)
        self.handle_detection(rect)
        
        self.canvas.delete(self.rect_id)
        self.rect_id = None
        self.rect_start = None
        # Don't toggle selection off - let user make multiple selections

    def handle_detection(self, rect):
        page = self.pdf_doc[self.current_page]
        detected_text = ""
        detection_source = "Unknown"
        lines_data = []  # Store line position data for multi-line text
        
        # STRATEGY 1: Check for Form Widgets (Common in ACORD)
        for widget in page.widgets():
            if widget.rect.intersects(rect):
                if widget.field_value:
                    detected_text = str(widget.field_value)
                    detection_source = "Form Field"
                    lines_data = [{'text': detected_text, 'y0': rect.y0, 'y1': rect.y1}]
                    break
        
        # STRATEGY 2: Get text with line information (most accurate for multi-line)
        if not detected_text:
            # Get text as dictionary to preserve line structure
            text_dict = page.get_text("dict", clip=rect)
            
            if "blocks" in text_dict and text_dict["blocks"]:
                # Extract all text lines with their positions
                all_lines = []
                for block in text_dict["blocks"]:
                    if "lines" in block:
                        for line in block["lines"]:
                            line_text = ""
                            line_y0 = line["bbox"][1]
                            line_y1 = line["bbox"][3]
                            
                            for span in line["spans"]:
                                line_text += span["text"]
                            
                            if line_text.strip():
                                all_lines.append({
                                    'text': line_text.strip(),
                                    'y0': line_y0,
                                    'y1': line_y1
                                })
                
                # Sort lines by vertical position
                all_lines.sort(key=lambda x: x['y0'])
                
                if all_lines:
                    detected_text = "\n".join([line['text'] for line in all_lines])
                    detection_source = "Multi-line Text"
                    lines_data = all_lines
                    print(f"Detected multi-line text with {len(all_lines)} lines")

        # STRATEGY 3: Fallback to words method if no structured text found
        if not detected_text:
            words = page.get_text("words", clip=rect)
            if words:
                # Group words by line using y-coordinate clustering
                lines = {}
                for w in words:
                    y_pos = round((w[1] + w[3]) / 2, 1)  # Average y position
                    if y_pos not in lines:
                        lines[y_pos] = []
                    lines[y_pos].append(w[4])
                
                # Sort lines by y position
                sorted_y = sorted(lines.keys())
                line_texts = [" ".join(lines[y]) for y in sorted_y]
                
                detected_text = "\n".join(line_texts)
                detection_source = "Word Clusters"
                
                # Create line data for positioning
                for i, y in enumerate(sorted_y):
                    if i < len(words):
                        w = words[i]
                        lines_data.append({
                            'text': line_texts[i],
                            'y0': w[1],
                            'y1': w[3]
                        })

        # STRATEGY 4: OCR (If it's an image/scan)
        if not detected_text:
            try:
                zoom = 3  # Higher zoom for better OCR
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, clip=rect)
                img_data = pix.tobytes("png")
                pil_img = Image.open(io.BytesIO(img_data))
                
                # Configure Tesseract to preserve line breaks
                ocr_text = pytesseract.image_to_string(pil_img, config='--psm 6').strip()
                if ocr_text:
                    detected_text = ocr_text
                    detection_source = "OCR (Scan)"
                    # Split OCR text into lines
                    ocr_lines = ocr_text.split('\n')
                    line_height = (rect.y1 - rect.y0) / max(1, len(ocr_lines))
                    
                    for i, line in enumerate(ocr_lines):
                        if line.strip():
                            lines_data.append({
                                'text': line.strip(),
                                'y0': rect.y0 + i * line_height,
                                'y1': rect.y0 + (i + 1) * line_height
                            })
            except Exception as e:
                print(f"OCR Failed: {e}")

        # Open Dialog with multi-line support
        self.open_edit_dialog(detected_text, detection_source, rect, lines_data)

    def open_edit_dialog(self, old_text, source, rect, lines_data):
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Text - Multi-line Support")
        dialog.geometry("600x500")
        dialog.grab_set()
        dialog.attributes('-topmost', True)

        # Main frame with padding
        main_frame = tk.Frame(dialog, padx=20, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(main_frame, text=f"Source: {source}", fg="#7f8c8d", font=("Segoe UI", 9)).pack(anchor="w", pady=(0,10))

        # Old text section
        tk.Label(main_frame, text="Current Text:", anchor="w", font=("Segoe UI", 10, "bold")).pack(fill=tk.X, anchor="w")
        old_frame = tk.Frame(main_frame)
        old_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        old_scroll = tk.Scrollbar(old_frame)
        old_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        old_text_widget = tk.Text(old_frame, height=6, font=("Segoe UI", 10), 
                                 yscrollcommand=old_scroll.set, wrap=tk.WORD,
                                 bg="#f8f9fa", relief=tk.SOLID, borderwidth=1)
        old_text_widget.pack(fill=tk.BOTH, expand=True)
        old_scroll.config(command=old_text_widget.yview)
        
        old_text_widget.insert("1.0", old_text if old_text else "[No text detected]")
        old_text_widget.config(state="disabled")

        # New text section - with explicit multi-line support
        tk.Label(main_frame, text="✏️ New Text (Press Enter for new line):", anchor="w", 
                font=("Segoe UI", 10, "bold"), fg="#2196F3").pack(fill=tk.X, anchor="w", pady=(10, 5))
        new_frame = tk.Frame(main_frame)
        new_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        new_scroll = tk.Scrollbar(new_frame)
        new_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        new_text_widget = tk.Text(new_frame, height=8, font=("Segoe UI", 10), 
                                 yscrollcommand=new_scroll.set, wrap=tk.WORD,
                                 bg="white", relief=tk.SOLID, borderwidth=1)
        new_text_widget.pack(fill=tk.BOTH, expand=True)
        new_scroll.config(command=new_text_widget.yview)
        
        # Pre-fill with detected text (maintaining line breaks)
        if old_text and old_text != "[No text detected]":
            new_text_widget.insert("1.0", old_text)
        new_text_widget.focus()
        
        # Add placeholder hint for multi-line editing
        hint_label = tk.Label(main_frame, text=" Hint: Press Enter for new line • Tab for indentation", 
                             font=("Segoe UI", 8), fg="#7f8c8d", anchor="w")
        hint_label.pack(fill=tk.X, pady=(0, 10))

        # Button frame
        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        
        status_var = tk.StringVar()
        status_label = tk.Label(btn_frame, textvariable=status_var, fg="green", font=("Segoe UI", 9))
        status_label.pack(side=tk.LEFT, padx=5)

        def submit(event=None):
            new_text = new_text_widget.get("1.0", tk.END).strip()
            if not new_text:
                status_var.set(" New text cannot be empty!")
                status_label.config(fg="red")
                return
            
            # Count lines to determine if this is multi-line
            lines = new_text.split('\n')
            is_multi_line = len(lines) > 1
            
            # Create edit entry with full line data
            edit_entry = {
                "page": self.current_page,
                "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
                "old_text": old_text if old_text else "[Manual Entry]",
                "new_text": new_text,
                "manual_mode": not old_text or old_text == "[No text detected]",
                "multi_line": is_multi_line,
                "lines_data": lines_data if lines_data else []
            }
            
            self.edits.append(edit_entry)
            
            # Format display text for listbox
            display_text = new_text
            if len(display_text) > 50:
                # Show preview with line indicators
                lines_preview = display_text.split('\n')
                if len(lines_preview) > 3:
                    display_text = "\n".join(lines_preview[:3]) + "...\n[+" + str(len(lines_preview)-3) + " more lines]"
                else:
                    display_text = "\n".join(lines_preview)
            
            # Add to listbox with proper formatting
            item_index = self.listbox.size()
            display_label = f"Pg {self.current_page+1}: {('¶ ' if is_multi_line else '')}{display_text[:30]}..."
            if len(display_text) > 30:
                display_label += f" ({len(lines)} lines)" if is_multi_line else ""
            
            self.listbox.insert(tk.END, display_label)
            self.listbox.itemconfig(tk.END, 
                                  fg="red" if edit_entry['manual_mode'] else "#2980b9",
                                  bg="#fffacd" if is_multi_line else "#ffffff")
            
            self.btn_save.config(state=tk.NORMAL)
            self.render_page()
            dialog.destroy()

        submit_btn = tk.Button(btn_frame, text=" Apply Change", command=submit, 
                             bg="#27ae60", fg="white", font=("Segoe UI", 10, "bold"),
                             padx=15, pady=5)
        submit_btn.pack(side=tk.RIGHT, padx=5)
        
        cancel_btn = tk.Button(btn_frame, text=" Cancel", command=dialog.destroy,
                              bg="#95a5a6", fg="white", font=("Segoe UI", 10),
                              padx=15, pady=5)
        cancel_btn.pack(side=tk.RIGHT, padx=5)

        # Add keyboard shortcuts
        dialog.bind('<Return>', lambda e: new_text_widget.insert(tk.INSERT, '\n'))
        dialog.bind('<Control-Return>', submit)  # Ctrl+Enter to submit
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        
        # Set focus to new text widget
        new_text_widget.focus_set()

    def remove_edit(self):
        sel = self.listbox.curselection()
        if not sel: return
        idx = sel[0]
        self.listbox.delete(idx)
        self.edits.pop(idx)
        
        if not self.edits:
            self.btn_save.config(state=tk.DISABLED)
        self.render_page()

    def save_pdf(self):
        if not self.edits:
            messagebox.showwarning("No Changes", "There are no changes to save!")
            return
            
        save_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            initialfile=f"modified_{Path(self.pdf_path).name}"
        )
        
        if not save_path:
            return

        try:
            # Create a fresh copy of the document
            doc = fitz.open(self.pdf_path)
            
            # Group edits by page for efficiency
            edits_by_page = {}
            for edit in self.edits:
                page_num = edit['page']
                if page_num not in edits_by_page:
                    edits_by_page[page_num] = []
                edits_by_page[page_num].append(edit)
            
            # Process each page
            total_edits = 0
            for page_num, page_edits in edits_by_page.items():
                page = doc[page_num]
                
                # Process each edit on this page
                for edit in page_edits:
                    total_edits += 1
                    rect = fitz.Rect(edit['rect'])
                    
                    # 1. Clean the Area - more aggressive cleaning for multi-line text
                    clean_rect = fitz.Rect(rect.x0-3, rect.y0-3, rect.x1+3, rect.y1+3)
                    
                    # Remove form fields first
                    for widget in page.widgets():
                        if widget.rect.intersects(clean_rect):
                            page.delete_widget(widget)
                    
                    # Use redaction for thorough cleaning
                    page.add_redact_annot(clean_rect, fill=(1, 1, 1), text="", fontsize=0)
                    page.apply_redactions()
                    
                    # 2. Insert New Text with precise multi-line positioning
                    new_text = edit['new_text']
                    lines = new_text.split('\n')
                    
                    # If we have line positioning data from detection, use it
                    if edit.get('multi_line', False) and edit.get('lines_data'):
                        lines_data = edit['lines_data']
                        
                        # Match detected lines with new lines (or create new positions if needed)
                        for i, line in enumerate(lines):
                            if i < len(lines_data) and line.strip():
                                # Use detected line position
                                line_rect = lines_data[i]
                                y_pos = line_rect['y0'] + (line_rect['y1'] - line_rect['y0']) * 0.8  # 80% down the line height
                                
                                # Calculate appropriate font size based on line height
                                line_height = line_rect['y1'] - line_rect['y0']
                                fontsize = max(6, min(line_height * 0.8, 14))
                                
                                page.insert_text(
                                    (rect.x0 + 1, y_pos),
                                    line.strip(),
                                    fontsize=fontsize,
                                    fontname="helv",  # Helvetica
                                    color=(0, 0, 0)
                                )
                    else:
                        # Single line or no position data - center vertically
                        if len(lines) == 1:
                            y_pos = rect.y0 + (rect.y1 - rect.y0) * 0.8  # 80% down the box height
                            fontsize = max(6, min((rect.y1 - rect.y0) * 0.8, 14))
                            
                            page.insert_text(
                                (rect.x0 + 1, y_pos),
                                lines[0].strip(),
                                fontsize=fontsize,
                                fontname="helv",
                                color=(0, 0, 0)
                            )
                        else:
                            # Multi-line without position data - distribute evenly
                            line_height = (rect.y1 - rect.y0) / max(1, len(lines))
                            fontsize = max(6, min(line_height * 0.8, 12))
                            
                            for i, line in enumerate(lines):
                                if not line.strip():
                                    continue
                                    
                                y_pos = rect.y0 + (i + 0.8) * line_height
                                page.insert_text(
                                    (rect.x0 + 1, y_pos),
                                    line.strip(),
                                    fontsize=fontsize,
                                    fontname="helv",
                                    color=(0, 0, 0)
                                )
            
            # Save with maximum optimization
            doc.save(save_path, garbage=4, deflate=True, clean=True, linear=True)
            doc.close()
            
            messagebox.showinfo("Success", f"PDF saved successfully!\n\n"
                                          f" {save_path}\n"
                                          f" {total_edits} edits applied across {len(edits_by_page)} pages\n"
                                          f" Original quality preserved with formatting")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save PDF:\n{str(e)}\n\n"
                                         f"Try saving to a different location or with a simpler filename.")

    # Navigation
    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.render_page()

    def next_page(self):
        if self.pdf_doc and self.current_page < len(self.pdf_doc) - 1:
            self.current_page += 1
            self.render_page()

    def zoom_in(self):
        if self.zoom_level < 4.0:
            self.zoom_level += 0.25
            self.render_page()
            self.update_toolbar_zoom()

    def zoom_out(self):
        if self.zoom_level > 0.5:
            self.zoom_level -= 0.25
            self.render_page()
            self.update_toolbar_zoom()
    
    def update_toolbar_zoom(self):
        # Find the zoom label in the toolbar and update it
        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Frame):  # toolbar frame
                        for grandchild in child.winfo_children():
                            if isinstance(grandchild, tk.Label) and "Zoom:" in grandchild.cget("text"):
                                grandchild.config(text=f"Zoom: {int(self.zoom_level*100)}%")
                                return

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = UltimatePDFEditor(root)
        root.mainloop()
    except Exception as e:
        messagebox.showerror("Critical Error", f"Application crashed:\n{str(e)}")
        sys.exit(1)