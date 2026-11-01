"""MediaRescue V2 — Windows photo/video signature recovery GUI."""
import ctypes
import io
import os
import queue
import string
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from carver import scan, copy_hit


def available_volumes():
    if sys.platform != 'win32': return []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [c + ':\\' for i, c in enumerate(string.ascii_uppercase) if mask & (1 << i)]


def volume_size(root):
    free = ctypes.c_ulonglong()
    total = ctypes.c_ulonglong()
    avail = ctypes.c_ulonglong()
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(root),
                                                      ctypes.byref(avail), ctypes.byref(total), ctypes.byref(free))
    if not ok: raise ctypes.WinError()
    return total.value


def normalize_volume_path(root):
    return '\\\\.\\' + root[:2]


class App:
    def __init__(self, master):
        self.root = master
        master.title('MediaRescue V2 — Deleted Photo & Video Recovery')
        master.geometry('1050x690')
        master.minsize(850, 550)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.hits = []
        self.running = False
        self.source = None
        self.source_root = None
        self.source_size = None
        self.mode = tk.StringVar(value='volume')
        self.volume = tk.StringVar()
        self.imgfile = tk.StringVar()
        self.status = tk.StringVar(value='Select a source, then click Scan.')
        self.build()
        master.after(100, self.drain_events)

    def build(self):
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill='x')
        ttk.Label(top, text='MediaRescue V2', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(top, text='Read-only signature scan • JPEG / PNG / MP4 / MOV • Windows administrator permissions required for drive scans').pack(anchor='w')
        pick = ttk.LabelFrame(self.root, text='Scan source', padding=10)
        pick.pack(fill='x', padx=12)
        row = ttk.Frame(pick); row.pack(fill='x')
        ttk.Radiobutton(row, text='Drive / volume', variable=self.mode, value='volume').pack(side='left')
        volumes = available_volumes()
        self.volume.set(volumes[0] if volumes else '')
        ttk.Combobox(row, textvariable=self.volume, values=volumes, width=10, state='readonly').pack(side='left', padx=10)
        ttk.Radiobutton(row, text='Disk image (.img / .dd / .bin)', variable=self.mode, value='image').pack(side='left', padx=(20, 0))
        ttk.Entry(row, textvariable=self.imgfile, width=38).pack(side='left', padx=8, fill='x', expand=True)
        ttk.Button(row, text='Browse…', command=self.browse_image).pack(side='left')
        controls = ttk.Frame(self.root, padding=(12, 10)); controls.pack(fill='x')
        self.scan_btn = ttk.Button(controls, text='Start deep scan', command=self.start_scan)
        self.scan_btn.pack(side='left')
        ttk.Button(controls, text='Cancel', command=self.cancel).pack(side='left', padx=8)
        self.recover_btn = ttk.Button(controls, text='Recover selected to folder…', command=self.recover)
        self.recover_btn.pack(side='right')
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(fill='x', padx=12)
        ttk.Label(self.root, textvariable=self.status, padding=(12, 5)).pack(anchor='w')
        center = ttk.Panedwindow(self.root, orient='horizontal')
        center.pack(fill='both', expand=True, padx=12, pady=6)
        left = ttk.Frame(center)
        center.add(left, weight=4)
        self.tree = ttk.Treeview(left, columns=('type', 'size', 'offset'), show='headings', selectmode='extended')
        for name, label, width in [('type', 'Type', 95), ('size', 'Size', 115), ('offset', 'Disk offset', 160)]:
            self.tree.heading(name, text=label); self.tree.column(name, width=width, anchor='w')
        self.tree.pack(side='left', fill='both', expand=True)
        sc = ttk.Scrollbar(left, command=self.tree.yview)
        sc.pack(side='right', fill='y'); self.tree.configure(yscrollcommand=sc.set)
        self.tree.bind('<<TreeviewSelect>>', self.preview)
        right = ttk.LabelFrame(center, text='Preview / details', padding=12)
        center.add(right, weight=2)
        self.preview_label = ttk.Label(right, text='Select a result to preview.', anchor='center', justify='center')
        self.preview_label.pack(fill='both', expand=True)
        self.details = ttk.Label(right, text='', wraplength=220, justify='left')
        self.details.pack(anchor='w')
        self.photo = None
        ttk.Label(self.root, text=('CAUTION: Scan a drive only if you own it or have permission. Do not install, save, or recover files to the affected drive. '
                                   'An SSD with TRIM enabled may contain no recoverable deleted data.'),
                  wraplength=990, foreground='#8b4513', padding=12).pack(fill='x')

    def browse_image(self):
        path = filedialog.askopenfilename(title='Choose a raw disk image', filetypes=[('Raw images', '*.img *.dd *.bin'), ('All files', '*.*')])
        if path: self.imgfile.set(path); self.mode.set('image')

    def source_config(self):
        if self.mode.get() == 'image':
            path = self.imgfile.get().strip()
            if not os.path.isfile(path): raise ValueError('Choose an existing disk image.')
            return path, os.path.getsize(path), None
        drive = self.volume.get()
        if not drive: raise ValueError('Choose a drive.')
        if sys.platform != 'win32': raise ValueError('Volume scanning is supported on Windows.')
        return normalize_volume_path(drive), volume_size(drive), drive

    def start_scan(self):
        if self.running: return
        try: source, size, root = self.source_config()
        except Exception as e: messagebox.showerror('Source error', str(e)); return
        if not messagebox.askokcancel('Read-only scan', 'The scan reads raw storage and can take a long time. It does not change source data. Continue?'):
            return
        self.source, self.source_size, self.source_root = source, size, root
        self.stop.clear(); self.hits.clear()
        for child in self.tree.get_children(): self.tree.delete(child)
        self.progress['value'] = 0
        self.status.set('Scanning…')
        self.running = True
        self.scan_btn.state(['disabled'])
        threading.Thread(target=self.do_scan, daemon=True).start()

    def do_scan(self):
        try:
            for hit in scan(self.source, self.source_size, self.stop,
                            lambda done, total: self.events.put(('progress', done, total))):
                self.events.put(('hit', hit))
            self.events.put(('done', 'Scan canceled.' if self.stop.is_set() else 'Scan complete.'))
        except Exception as e:
            self.events.put(('error', str(e)))

    def cancel(self):
        if self.running: self.stop.set(); self.status.set('Cancellation requested…')

    def drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == 'hit':
                    hit = event[1]; i = len(self.hits); self.hits.append(hit)
                    self.tree.insert('', 'end', iid=str(i), values=(hit.extension.upper(), f'{hit.length / 1024 / 1024:.2f} MB', f'0x{hit.offset:X}'))
                elif kind == 'progress':
                    self.progress['value'] = 100 * event[1] / max(event[2], 1)
                    self.status.set(f'Scanning {event[1] / 1024**3:.2f} of {event[2] / 1024**3:.2f} GiB • {len(self.hits)} candidates')
                elif kind in ('done', 'error'):
                    self.running = False; self.scan_btn.state(['!disabled'])
                    self.status.set(event[1] + f' {len(self.hits)} candidate(s).')
                    if kind == 'error': messagebox.showerror('Scan error', event[1] + '\nTry Run as administrator, or scan a raw disk image.')
                elif kind == 'recover_done':
                    self.running = False; self.scan_btn.state(['!disabled'])
                    self.status.set(event[1]); messagebox.showinfo('Recovery', event[1])
                elif kind == 'recover_error':
                    self.running = False; self.scan_btn.state(['!disabled'])
                    self.status.set(event[1]); messagebox.showerror('Recovery error', event[1])
        except queue.Empty: pass
        self.root.after(100, self.drain_events)

    def preview(self, _evt=None):
        selected = self.tree.selection()
        if not selected: return
        hit = self.hits[int(selected[0])]
        self.photo = None
        self.details.configure(text=f'{hit.kind} • {hit.length:,} bytes\nOffset: {hit.offset:,}\n{hit.note}\n\nPreview is best-effort; a candidate may be damaged.')
        if hit.kind != 'Photo':
            self.preview_label.configure(image='', text='Video preview not available.\nRecover the file to inspect.')
            return
        try:
            from PIL import Image, ImageTk
            if hit.length > 60 * 1024 * 1024: raise ValueError('Photo too large to preview safely.')
            with open(self.source, 'rb', buffering=0) as f:
                f.seek(hit.offset); blob = f.read(hit.length)
            with Image.open(io.BytesIO(blob)) as im:
                im.thumbnail((280, 260))
                self.photo = ImageTk.PhotoImage(im.copy())
            self.preview_label.configure(image=self.photo, text='')
        except Exception:
            self.preview_label.configure(image='', text='Preview unavailable\n(possibly damaged file)')

    def recover(self):
        if self.running: messagebox.showwarning('Busy', 'Cancel or finish the scan before recovering.'); return
        selected = list(self.tree.selection())
        if not selected: messagebox.showinfo('Select files', 'Select one or more scan results.'); return
        folder = filedialog.askdirectory(title='Choose a DIFFERENT drive for recovered files')
        if not folder: return
        if self.source_root and os.path.splitdrive(os.path.abspath(folder))[0].lower() == self.source_root[:2].lower():
            messagebox.showerror('Unsafe destination', 'Choose a different drive to avoid overwriting deleted data.'); return
        if self.mode.get() == 'image' and os.path.abspath(self.source).lower() == os.path.abspath(folder).lower():
            messagebox.showerror('Unsafe destination', 'Use another folder.'); return
        if not messagebox.askyesno('Confirm recovery', f'Recover {len(selected)} candidate(s) to:\n{folder}\n\nFiles may be incomplete or corrupt. Proceed?'):
            return
        self.stop.clear(); self.running=True; self.scan_btn.state(['disabled'])
        threading.Thread(target=self.do_recover, args=(selected, folder), daemon=True).start()

    def do_recover(self, ids, folder):
        count = 0; errors=[]
        for id in ids:
            if self.stop.is_set(): break
            hit = self.hits[int(id)]
            name = f'recovered_{hit.offset:016X}.{hit.extension}'
            try: copy_hit(self.source, hit, os.path.join(folder, name), self.stop); count += 1
            except Exception as e: errors.append(f'{name}: {e}')
        summary = f'Saved {count} of {len(ids)} candidate(s) to {folder}.'
        if errors: summary += '\nErrors (first 5):\n' + '\n'.join(errors[:5])
        self.events.put(('recover_done', summary))


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
