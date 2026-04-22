import json
import os
import sys
import threading
from pathlib import Path


def _prepare_tk_env() -> None:
    if not getattr(sys, "frozen", False):
        return
    base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    tcl_dir = base_dir / "tcl8.6"
    tk_dir = base_dir / "tk8.6"
    if tcl_dir.exists():
        os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
    if tk_dir.exists():
        os.environ.setdefault("TK_LIBRARY", str(tk_dir))


_prepare_tk_env()

from tkinter import BOTH, END, LEFT, RIGHT, TOP, VERTICAL, W, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from cloud_status_core import SSHConfig, collect_report, format_report


APP_TITLE = "Cloud GPU Checker"
DEFAULT_PROFILE_NAME = "Example-Server"


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path() -> Path:
    return app_base_dir() / "yun_gpu_checker_config.json"


def default_profile() -> dict[str, str]:
    return {
        "host": "",
        "port": "22",
        "user": "root",
        "password": "",
        "key_path": "",
        "run_root": "/workspace/experiments/project",
        "launcher_log": "/workspace/experiments/project/launcher.log",
        "log_root": "/workspace/experiments/project/logs",
        "plan_script": "/workspace/project/scripts/run_baseline.sh",
    }


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1020x820")

        self.config_path = config_path()
        self.profile_name_var = StringVar(value=DEFAULT_PROFILE_NAME)
        self.status_var = StringVar(value="Ready")
        self.vars = {key: StringVar(value=value) for key, value in default_profile().items()}
        self.profiles: dict[str, dict[str, str]] = {}

        self._load_profiles()
        self._build_ui()
        self._refresh_profile_dropdown()
        self._apply_selected_profile()

    def _load_profiles(self) -> None:
        if not self.config_path.exists():
            self.profiles = {DEFAULT_PROFILE_NAME: default_profile()}
            return

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            self.profiles = {DEFAULT_PROFILE_NAME: default_profile()}
            return

        self.profiles = data.get("profiles", {}) or {DEFAULT_PROFILE_NAME: default_profile()}
        last_profile = data.get("last_profile")
        if last_profile and last_profile in self.profiles:
            self.profile_name_var.set(last_profile)
        else:
            self.profile_name_var.set(next(iter(self.profiles.keys())))

    def _save_profiles(self) -> None:
        payload = {
            "last_profile": self.profile_name_var.get().strip() or "",
            "profiles": self.profiles,
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=BOTH, expand=True)

        profile_box = ttk.LabelFrame(outer, text="Instance Profiles", padding=10)
        profile_box.pack(fill="x", side=TOP)

        ttk.Label(profile_box, text="Current Profile").grid(row=0, column=0, sticky=W, padx=(0, 8), pady=4)
        self.profile_combo = ttk.Combobox(
            profile_box,
            textvariable=self.profile_name_var,
            state="readonly",
            width=40,
        )
        self.profile_combo.grid(row=0, column=1, sticky="w", pady=4)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_selected_profile())

        ttk.Button(profile_box, text="Add Profile", command=self._add_profile).grid(row=0, column=2, padx=(8, 0), pady=4)
        ttk.Button(profile_box, text="Save Profile", command=self._save_current_profile).grid(row=0, column=3, padx=(8, 0), pady=4)
        ttk.Button(profile_box, text="Delete Profile", command=self._delete_profile).grid(row=0, column=4, padx=(8, 0), pady=4)

        form = ttk.LabelFrame(outer, text="SSH / Experiment Info", padding=10)
        form.pack(fill="x", side=TOP, pady=(10, 0))

        fields = [
            ("host", "Host"),
            ("port", "Port"),
            ("user", "User"),
            ("password", "Password"),
            ("key_path", "Key Path"),
            ("run_root", "Run Root"),
            ("launcher_log", "Launcher Log"),
            ("log_root", "Log Root"),
            ("plan_script", "Plan Script"),
        ]

        for idx, (key, label) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=idx, column=0, sticky=W, padx=(0, 8), pady=4)
            entry = ttk.Entry(form, textvariable=self.vars[key], width=95, show="*" if key == "password" else "")
            entry.grid(row=idx, column=1, sticky="ew", pady=4)
            if key == "key_path":
                ttk.Button(form, text="Browse", command=self._browse_key).grid(row=idx, column=2, padx=(8, 0), pady=4)

        form.columnconfigure(1, weight=1)

        btn_row = ttk.Frame(outer, padding=(0, 10, 0, 10))
        btn_row.pack(fill="x", side=TOP)
        ttk.Button(btn_row, text="Check", command=self._run_check).pack(side=LEFT)
        ttk.Button(btn_row, text="Save Current Input", command=self._save_current_profile).pack(side=LEFT, padx=(8, 0))
        ttk.Button(btn_row, text="Copy Result", command=self._copy_result).pack(side=LEFT, padx=(8, 0))
        ttk.Label(btn_row, textvariable=self.status_var).pack(side=RIGHT)

        result_frame = ttk.LabelFrame(outer, text="Result", padding=8)
        result_frame.pack(fill=BOTH, expand=True)

        self.result_text = Text(result_frame, wrap="word", font=("Consolas", 10))
        scroll = ttk.Scrollbar(result_frame, orient=VERTICAL, command=self.result_text.yview)
        self.result_text.configure(yscrollcommand=scroll.set)
        self.result_text.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill="y")

    def _refresh_profile_dropdown(self) -> None:
        names = list(self.profiles.keys())
        self.profile_combo["values"] = names
        current = self.profile_name_var.get().strip()
        if current not in self.profiles and names:
            self.profile_name_var.set(names[0])

    def _apply_selected_profile(self) -> None:
        name = self.profile_name_var.get().strip()
        profile = self.profiles.get(name)
        if not profile:
            return
        merged = default_profile()
        merged.update(profile)
        for key, var in self.vars.items():
            var.set(str(merged.get(key, "")))

    def _collect_current_fields(self) -> dict[str, str]:
        return {key: var.get().strip() for key, var in self.vars.items()}

    def _save_current_profile(self) -> None:
        name = self.profile_name_var.get().strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "Please enter a profile name first.")
            return
        self.profiles[name] = self._collect_current_fields()
        self._refresh_profile_dropdown()
        self.profile_name_var.set(name)
        self._save_profiles()
        self.status_var.set(f"Saved profile: {name}")

    def _add_profile(self) -> None:
        base_name = "New-Profile"
        name = base_name
        idx = 2
        while name in self.profiles:
            name = f"{base_name}-{idx}"
            idx += 1
        self.profiles[name] = default_profile()
        self._refresh_profile_dropdown()
        self.profile_name_var.set(name)
        self._apply_selected_profile()
        self._save_profiles()
        self.status_var.set(f"Added profile: {name}")

    def _delete_profile(self) -> None:
        name = self.profile_name_var.get().strip()
        if name not in self.profiles:
            return
        if len(self.profiles) == 1:
            messagebox.showwarning(APP_TITLE, "Keep at least one profile.")
            return
        if not messagebox.askyesno(APP_TITLE, f"Delete profile '{name}'?"):
            return
        del self.profiles[name]
        next_name = next(iter(self.profiles.keys()))
        self.profile_name_var.set(next_name)
        self._refresh_profile_dropdown()
        self._apply_selected_profile()
        self._save_profiles()
        self.status_var.set(f"Deleted profile: {name}")

    def _browse_key(self) -> None:
        selected = filedialog.askopenfilename(title="Select private key")
        if selected:
            self.vars["key_path"].set(selected)

    def _build_config(self) -> SSHConfig:
        port_text = self.vars["port"].get().strip() or "22"
        return SSHConfig(
            host=self.vars["host"].get().strip(),
            port=int(port_text),
            user=self.vars["user"].get().strip() or "root",
            password=self.vars["password"].get().strip() or None,
            key_path=self.vars["key_path"].get().strip() or None,
            run_root=self.vars["run_root"].get().strip(),
            launcher_log=self.vars["launcher_log"].get().strip(),
            log_root=self.vars["log_root"].get().strip(),
            plan_script=self.vars["plan_script"].get().strip(),
        )

    def _copy_result(self) -> None:
        text = self.result_text.get("1.0", END).strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Result copied to clipboard")

    def _run_check(self) -> None:
        try:
            cfg = self._build_config()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Invalid config: {exc}")
            return

        profile_name = self.profile_name_var.get().strip() or DEFAULT_PROFILE_NAME
        self.profiles[profile_name] = self._collect_current_fields()
        self._save_profiles()

        if not cfg.host:
            messagebox.showwarning(APP_TITLE, "Please fill in Host first.")
            return

        self.status_var.set("Checking...")
        self.result_text.delete("1.0", END)
        self.result_text.insert(END, "Connecting and checking, please wait...\n")
        thread = threading.Thread(target=self._worker_check, args=(cfg,), daemon=True)
        thread.start()

    def _worker_check(self, cfg: SSHConfig) -> None:
        try:
            report = collect_report(cfg)
            text = format_report(report)
            self.root.after(0, lambda: self._update_result(text, "Check finished"))
        except Exception as exc:
            self.root.after(0, lambda: self._update_result(f"Check failed: {exc}", "Check failed"))

    def _update_result(self, text: str, status: str) -> None:
        self.result_text.delete("1.0", END)
        self.result_text.insert(END, text)
        self.status_var.set(status)


def main() -> None:
    root = Tk()
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
