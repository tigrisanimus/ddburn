#!/usr/bin/env python3
"""
ddburn - a tiny, safe frontend for dd.
Pick an ISO, pick a USB stick, burn it. That's it.

Safety features:
  - Only lists whole disks (never partitions)
  - Removable devices shown first; internal disks hidden unless you ask
  - Big red confirmation showing exactly what will be wiped
  - Progress bar parsed from dd's own output
"""

import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def require_root():
    """Re-launch with sudo/pkexec if we're not root (dd needs raw disk access)."""
    if os.geteuid() == 0:
        return
    for launcher in (["pkexec"], ["sudo"]):
        try:
            os.execvp(launcher[0], launcher + [sys.executable, os.path.abspath(__file__)])
        except FileNotFoundError:
            continue
    print("Need root to write to disks. Run with sudo.", file=sys.stderr)
    sys.exit(1)


def list_disks(include_internal=False):
    """Return [(device, size, model, removable), ...] for whole disks only."""
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,MODEL,RM,TYPE"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return []
    disks = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        removable = str(dev.get("rm", "0")) == "1"
        if not removable and not include_internal:
            continue
        disks.append((
            f"/dev/{dev['name']}",
            dev.get("size", "?").strip(),
            (dev.get("model") or "Unknown device").strip(),
            removable,
        ))
    # Removable first, then by name
    disks.sort(key=lambda d: (not d[3], d[0]))
    return disks


class DDBurn(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ddburn")
        self.resizable(False, False)
        self.iso_path = tk.StringVar()
        self.device = tk.StringVar()
        self.show_internal = tk.BooleanVar(value=False)
        self.burning = False
        self._build_ui()
        self.refresh_devices()

    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=8, pady=8)

        ttk.Label(frm, text="ISO image:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.iso_path, width=42, state="readonly").grid(
            row=0, column=1, **pad)
        ttk.Button(frm, text="Browse…", command=self.pick_iso).grid(
            row=0, column=2, **pad)

        ttk.Label(frm, text="Target device:").grid(row=1, column=0, sticky="w", **pad)
        self.dev_combo = ttk.Combobox(frm, textvariable=self.device,
                                      width=40, state="readonly")
        self.dev_combo.grid(row=1, column=1, **pad)
        ttk.Button(frm, text="Refresh", command=self.refresh_devices).grid(
            row=1, column=2, **pad)

        ttk.Checkbutton(frm, text="Show internal disks (dangerous)",
                        variable=self.show_internal,
                        command=self.refresh_devices).grid(
            row=2, column=1, sticky="w", **pad)

        self.warn = ttk.Label(frm, text="", foreground="red", wraplength=420,
                              font=("", 9, "bold"))
        self.warn.grid(row=3, column=0, columnspan=3, **pad)

        self.progress = ttk.Progressbar(frm, length=420, mode="determinate")
        self.progress.grid(row=4, column=0, columnspan=3, **pad)
        self.status = ttk.Label(frm, text="Idle")
        self.status.grid(row=5, column=0, columnspan=3, **pad)

        self.burn_btn = ttk.Button(frm, text="🔥 Burn to USB", command=self.burn)
        self.burn_btn.grid(row=6, column=0, columnspan=3, pady=12)

        self.dev_combo.bind("<<ComboboxSelected>>", lambda e: self.update_warn())

    def pick_iso(self):
        path = filedialog.askopenfilename(
            title="Select ISO image",
            filetypes=[("ISO images", "*.iso"), ("All files", "*.*")])
        if path:
            self.iso_path.set(path)

    def refresh_devices(self):
        disks = list_disks(include_internal=self.show_internal.get())
        self._disks = {f"{d[0]}  ({d[1]}, {d[2]})": d[0] for d in disks}
        self.dev_combo["values"] = list(self._disks.keys())
        if self.dev_combo["values"]:
            self.dev_combo.current(0)
        else:
            self.device.set("")
        self.update_warn()

    def update_warn(self):
        sel = self.device.get()
        dev = self._disks.get(sel, "")
        if dev:
            self.warn.config(
                text=f"⚠  ALL DATA on {dev} will be DESTROYED. Double-check it's your USB stick.")
        else:
            self.warn.config(text="")

    def burn(self):
        iso = self.iso_path.get()
        dev = self._disks.get(self.device.get(), "")
        if not iso or not os.path.isfile(iso):
            messagebox.showerror("No ISO", "Pick a valid ISO file first.")
            return
        if not dev:
            messagebox.showerror("No device", "Pick a target device first.")
            return
        if not re.fullmatch(r"/dev/(sd[a-z]+|nvme\d+n\d+|mmcblk\d+|vd[a-z]+)", dev):
            messagebox.showerror("Refusing", f"Doesn't look like a whole disk: {dev}")
            return
        ok = messagebox.askokcancel(
            "Last chance",
            f"Write\n{iso}\nto\n{dev}\n\nALL DATA ON {dev} WILL BE ERASED.\n\nAre you sure?",
            icon="warning")
        if not ok:
            return
        self.burning = True
        self.burn_btn.config(state="disabled")
        self.progress["value"] = 0
        threading.Thread(target=self._run_dd, args=(iso, dev), daemon=True).start()

    def _run_dd(self, iso, dev):
        total = os.path.getsize(iso)
        # dd status=progress prints "N bytes (...) copied" to stderr
        proc = subprocess.Popen(
            ["dd", f"if={iso}", f"of={dev}", "bs=4M", "status=progress", "conv=fsync"],
            stderr=subprocess.PIPE, text=True)
        pat = re.compile(r"(\d+) bytes")
        for line in proc.stderr:
            m = pat.search(line)
            if m:
                done = int(m.group(1))
                pct = min(100.0, done / total * 100)
                self.after(0, self._set_progress, pct,
                           f"{done/1e9:.2f} / {total/1e9:.2f} GB  ({pct:.0f}%)")
        proc.wait()
        if proc.returncode == 0:
            # Make sure everything hit the disk
            subprocess.run(["sync"], check=False)
            self.after(0, self._done, True, "Done! Safe to unplug.")
        else:
            self.after(0, self._done, False,
                       f"dd failed (exit {proc.returncode}).")

    def _set_progress(self, pct, text):
        self.progress["value"] = pct
        self.status.config(text=text)

    def _done(self, ok, text):
        self.burning = False
        self.burn_btn.config(state="normal")
        self.progress["value"] = 100 if ok else 0
        self.status.config(text=text)
        (messagebox.showinfo if ok else messagebox.showerror)("ddburn", text)


if __name__ == "__main__":
    require_root()
    try:
        app = DDBurn()
    except tk.TclError as e:
        print(f"Can't open GUI: {e}\nIs tkinter installed? (apt install python3-tk)",
              file=sys.stderr)
        sys.exit(1)
    app.mainloop()
