# Cloud GPU Checker

Cloud GPU Checker is a small SSH-based utility for people who run experiments on remote GPU servers and want to know what is actually happening.

I originally wrote it for my own paper experiments. `nvidia-smi` can tell me whether the GPU is busy, but it cannot answer the questions I actually care about:

- Which model is running right now?
- Which horizon or task is running?
- How many sub-runs have already finished?
- Did any result file already appear?
- Roughly how long is left for the current run and the whole batch?

This tool reads remote process info, launcher logs, per-run logs, and result folders together, then turns them into a report that is much closer to the real experiment status.

## What It Does

- Connects to a remote Linux server over SSH
- Reads experiment logs and result folders
- Shows current task, model, and horizon
- Lists finished sub-experiments with `MSE / MAE` when available
- Estimates remaining time for the current run and the whole batch
- Supports both CLI and Windows GUI
- Supports multiple saved server profiles

## Repository Structure

- `cloud_status_core.py`: shared status collection and report formatting logic
- `check_cloud_experiment_status.py`: CLI entry
- `check_cloud_experiment_status.ps1`: PowerShell launcher
- `cloud_gpu_checker_gui.py`: GUI entry
- `yun_gpu_checker_config.example.json`: example multi-profile config
- `docs/CSDN_post.md`: Chinese post draft for sharing

## Install

```bash
pip install -r requirements.txt
```

## Quick Start

1. Copy `yun_gpu_checker_config.example.json` to `yun_gpu_checker_config.json`
2. Fill in your SSH and experiment paths
3. Run either the CLI or GUI version

## CLI Usage

```bash
python check_cloud_experiment_status.py --config yun_gpu_checker_config.json
```

## PowerShell Usage

```powershell
powershell -ExecutionPolicy Bypass -File .\check_cloud_experiment_status.ps1
```

## GUI Usage

```bash
python cloud_gpu_checker_gui.py
```

## Build a Windows EXE

If you want to distribute the GUI to users who do not run Python directly, you can package it with PyInstaller:

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name "Cloud GPU Checker" cloud_gpu_checker_gui.py
```

The generated executable will be placed in the `dist/` directory.

## Example Config

```json
{
  "last_profile": "Example-Server",
  "profiles": {
    "Example-Server": {
      "host": "example.com",
      "port": "22",
      "user": "root",
      "password": "",
      "key_path": "",
      "run_root": "/workspace/experiments/project",
      "launcher_log": "/workspace/experiments/project/launcher.log",
      "log_root": "/workspace/experiments/project/logs",
      "plan_script": "/workspace/project/scripts/run_baseline.sh"
    }
  }
}
```

## Notes

- Do not commit real passwords or private keys
- Prefer `key_path` over password when possible
- The GUI writes `yun_gpu_checker_config.json` next to the executable or source entry
- This tool works best when your experiment scripts follow stable directory and logging conventions

## Why I Open-Sourced It

This started as a personal helper while running long batch experiments on cloud GPUs. After using it for real training jobs, I found it solved a very common annoyance: the gap between "the machine is running" and "I actually know what experiment is going on".

So I cleaned it up and released it as a small standalone tool. If it helps you, feel free to use it directly or adapt it for your own experiment pipeline.

## License

MIT
