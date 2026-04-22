import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import paramiko


RUN_LINE_RE = re.compile(r"^\[RUN\]\s+(?P<name>.+?)\s*$", re.MULTILINE)
METRIC_RE = re.compile(r"mse:(?P<mse>[0-9eE+\-.]+),\s*mae:(?P<mae>[0-9eE+\-.]+)")
EPOCH_RE = re.compile(r"Epoch:\s*(?P<epoch>\d+),\s*Steps:")
ITER_RE = re.compile(r"iters:\s*\d+,\s*epoch:\s*(?P<epoch>\d+)\s*\|\s*loss:")
LEFT_TIME_RE = re.compile(r"left time:\s*(?P<seconds>[0-9eE+\-.]+)s")
TESTING_RE = re.compile(r">+testing\s*:")
EPOCH_COST_RE = re.compile(r"Epoch:\s*(?P<epoch>\d+)\s*cost time:\s*(?P<seconds>[0-9eE+\-.]+)")
TRAIN_EPOCHS_RE = re.compile(r"--train_epochs\s+(?P<epochs>\d+)")


@dataclass
class SSHConfig:
    host: str
    port: int
    user: str
    password: str | None
    key_path: str | None
    run_root: str
    launcher_log: str
    log_root: str
    plan_script: str


def load_config(config_path: Path) -> SSHConfig:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if "profiles" in data:
        last_profile = data.get("last_profile") or next(iter(data["profiles"]))
        data = data["profiles"][last_profile]
    return SSHConfig(
        host=data["host"],
        port=int(data.get("port", 22)),
        user=data.get("user", "root"),
        password=data.get("password"),
        key_path=data.get("key_path"),
        run_root=data["run_root"],
        launcher_log=data["launcher_log"],
        log_root=data["log_root"],
        plan_script=data["plan_script"],
    )


def save_config(config_path: Path, cfg: SSHConfig | dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(cfg) if isinstance(cfg, SSHConfig) else cfg
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def connect_ssh(cfg: SSHConfig) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict[str, Any] = {
        "hostname": cfg.host,
        "port": cfg.port,
        "username": cfg.user,
        "timeout": 20,
        "banner_timeout": 20,
        "auth_timeout": 20,
    }
    if cfg.key_path:
        kwargs["key_filename"] = cfg.key_path
    if cfg.password:
        kwargs["password"] = cfg.password
    client.connect(**kwargs)
    return client


def exec_text(client: paramiko.SSHClient, command: str) -> str:
    stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0 and not out and err:
        return ""
    return out


def sftp_read_text(sftp: paramiko.SFTPClient, remote_path: str) -> str:
    try:
        with sftp.open(remote_path, "r") as handle:
            return handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def sftp_stat(sftp: paramiko.SFTPClient, remote_path: str):
    try:
        return sftp.stat(remote_path)
    except FileNotFoundError:
        return None


def parse_total_subexperiments(script_text: str) -> int | None:
    def parse_array(name: str) -> list[str]:
        match = re.search(rf"{name}=\((.*?)\)", script_text, re.DOTALL)
        if not match:
            return []
        return [item.strip() for item in match.group(1).replace("\n", " ").split() if item.strip()]

    models = parse_array("MODELS")
    horizons = parse_array("HORIZONS")

    if models and horizons:
        return len(models) * len(horizons)
    if models:
        return len(models)

    if horizons:
        weather_variant_calls = len(re.findall(r"^\s*run_weather_variant\s+", script_text, re.MULTILINE))
        if weather_variant_calls:
            return len(horizons) * weather_variant_calls

    epf_variant_calls = len(re.findall(r"^\s*run_epf_variant\s+", script_text, re.MULTILINE))
    if epf_variant_calls:
        return epf_variant_calls

    return None


def parse_run_name(run_name: str) -> dict[str, str]:
    parts = run_name.split("__")
    result = {
        "group": "",
        "dataset": "",
        "variant": "",
        "seq_len": "",
        "pred_len": "",
        "seed": "",
    }
    if len(parts) >= 6:
        result.update(
            {
                "group": parts[0],
                "dataset": parts[1],
                "variant": parts[2],
                "seq_len": parts[3].replace("sl", ""),
                "pred_len": parts[4].replace("pl", ""),
                "seed": parts[5].replace("seed", ""),
            }
        )
    return result


def summarize_log(log_text: str) -> dict[str, Any]:
    metrics = METRIC_RE.findall(log_text)
    epoch_matches = [int(m) for m in EPOCH_RE.findall(log_text)]
    iter_matches = [int(m) for m in ITER_RE.findall(log_text)]
    left_time_matches = [float(m) for m in LEFT_TIME_RE.findall(log_text)]
    epoch_costs = [float(seconds) for _, seconds in EPOCH_COST_RE.findall(log_text)]
    is_testing = bool(TESTING_RE.search(log_text))

    summary: dict[str, Any] = {
        "completed": False,
        "mse": None,
        "mae": None,
        "epoch_done": max(epoch_matches) if epoch_matches else None,
        "epoch_running": max(iter_matches) if iter_matches else None,
        "is_testing": is_testing,
        "latest_left_time_sec": left_time_matches[-1] if left_time_matches else None,
        "observed_epoch_cost_sec": sum(epoch_costs) if epoch_costs else None,
    }
    if metrics:
        mse, mae = metrics[-1]
        summary["completed"] = True
        summary["mse"] = mse
        summary["mae"] = mae
    return summary


def parse_gpu_table(raw: str) -> list[dict[str, str]]:
    rows = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 4:
            rows.append(
                {
                    "name": parts[0],
                    "gpu_util": parts[1],
                    "mem_used": parts[2],
                    "mem_total": parts[3],
                }
            )
    return rows


def summarize_process_lines(raw: str) -> list[str]:
    summary: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=4)
        if len(parts) < 5:
            continue
        pid, etime, pcpu, pmem, args = parts
        entry = summary.setdefault(
            args,
            {
                "count": 0,
                "pid": pid,
                "etime": etime,
                "pcpu": pcpu,
                "pmem": pmem,
                "args": args,
            },
        )
        entry["count"] += 1

    lines = []
    for entry in summary.values():
        prefix = f"{entry['count']}x" if entry["count"] > 1 else "1x"
        lines.append(
            f"{prefix} | pid {entry['pid']} | etime {entry['etime']} | cpu {entry['pcpu']}% | mem {entry['pmem']}% | {entry['args']}"
        )
    return lines


def parse_train_epochs_from_process(process_text: str) -> int | None:
    match = TRAIN_EPOCHS_RE.search(process_text)
    return int(match.group("epochs")) if match else None


def format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def collect_report(cfg: SSHConfig) -> dict[str, Any]:
    client = connect_ssh(cfg)
    sftp = client.open_sftp()
    now_ts = time.time()

    system_raw = exec_text(
        client,
        "hostname; echo '---UPTIME---'; uptime; echo '---FREE---'; free -h; "
        "echo '---GPU---'; nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null || true; "
        "echo '---PS---'; ps -eo pid,etime,%cpu,%mem,args | grep -E 'python -u run.py|bash scripts/cloud|nohup bash -lc' | grep -v grep || true",
    )

    plan_text = sftp_read_text(sftp, cfg.plan_script)
    launcher_text = sftp_read_text(sftp, cfg.launcher_log)
    total = parse_total_subexperiments(plan_text)
    launched = RUN_LINE_RE.findall(launcher_text)

    run_summaries = []
    for run_name in launched:
        log_path = f"{cfg.log_root.rstrip('/')}/{run_name}.log"
        log_text = sftp_read_text(sftp, log_path)
        parsed_name = parse_run_name(run_name)
        parsed_log = summarize_log(log_text)
        stat = sftp_stat(sftp, log_path)
        parsed_log["log_mtime"] = stat.st_mtime if stat else None
        run_summaries.append(
            {
                "run_name": run_name,
                "log_path": log_path,
                "name": parsed_name,
                "log": parsed_log,
            }
        )

    completed_runs = [item for item in run_summaries if item["log"]["completed"]]
    current_run = next((item for item in run_summaries if not item["log"]["completed"]), None)
    if current_run is None and run_summaries:
        current_run = run_summaries[-1]

    system_parts = system_raw.split("---UPTIME---")
    hostname = system_parts[0].strip() if system_parts else ""
    rest = system_parts[1] if len(system_parts) > 1 else ""
    uptime_part = rest.split("---FREE---")[0].strip() if "---FREE---" in rest else ""
    free_part = rest.split("---FREE---")[1].split("---GPU---")[0].strip() if "---GPU---" in rest else ""
    gpu_part = rest.split("---GPU---")[1].split("---PS---")[0].strip() if "---PS---" in rest else ""
    ps_part = rest.split("---PS---")[1].strip() if "---PS---" in rest else ""
    gpu_rows = parse_gpu_table(gpu_part)
    process_lines = summarize_process_lines(ps_part)

    avg_completed_runtime = None
    completed_runtimes = [
        item["log"]["observed_epoch_cost_sec"]
        for item in completed_runs
        if item["log"]["observed_epoch_cost_sec"] is not None
    ]
    if completed_runtimes:
        avg_completed_runtime = sum(completed_runtimes) / len(completed_runtimes)

    current_left_time = current_run["log"]["latest_left_time_sec"] if current_run else None
    train_epochs = parse_train_epochs_from_process(ps_part)
    stall_warning = None
    if current_run and not current_run["log"]["completed"]:
        log_mtime = current_run["log"].get("log_mtime")
        if log_mtime and now_ts - log_mtime > 900:
            stall_warning = (
                f"The current log has not been updated for {int((now_ts - log_mtime) // 60)} minutes. "
                "The job may be stuck."
            )

    total_remaining = None
    if total is not None:
        remaining_after_current = max(total - len(completed_runs) - (1 if current_run else 0), 0)
        if current_left_time is not None and avg_completed_runtime is not None:
            total_remaining = current_left_time + remaining_after_current * avg_completed_runtime
        elif avg_completed_runtime is not None:
            total_remaining = (total - len(completed_runs)) * avg_completed_runtime
        elif current_left_time is not None:
            total_remaining = current_left_time

    report = {
        "hostname": hostname,
        "config": asdict(cfg),
        "uptime": uptime_part,
        "memory": free_part,
        "gpus": gpu_rows,
        "process_snapshot": process_lines,
        "plan_total": total,
        "launched_count": len(run_summaries),
        "completed_count": len(completed_runs),
        "current_run": current_run,
        "completed_runs": completed_runs,
        "avg_completed_runtime_sec": avg_completed_runtime,
        "current_left_time_sec": current_left_time,
        "total_remaining_sec": total_remaining,
        "train_epochs": train_epochs,
        "stall_warning": stall_warning,
    }

    sftp.close()
    client.close()
    return report


def format_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Instance Overview")
    lines.append(f"Host: {report['hostname']}")
    cfg = report["config"]
    lines.append(f"Connection: {cfg['user']}@{cfg['host']}:{cfg['port']}")
    lines.append(f"Run Root: {cfg['run_root']}")
    if report["uptime"]:
        lines.append(f"Uptime: {report['uptime']}")

    lines.append("")
    lines.append("Resource Usage")
    gpus = report["gpus"]
    if gpus:
        for idx, row in enumerate(gpus, 1):
            lines.append(
                f"GPU{idx}: {row['name']} | Util {row['gpu_util']}% | Memory {row['mem_used']} MiB / {row['mem_total']} MiB"
            )
    else:
        lines.append("GPU: no nvidia-smi output detected")
    if report["memory"]:
        lines.append(report["memory"])

    lines.append("")
    lines.append("Current Run")
    current = report["current_run"]
    if current:
        name = current["name"]
        log = current["log"]
        lines.append(f"Task: {name['group']} / {name['dataset']}")
        lines.append(f"Model: {name['variant']}")
        lines.append(f"Horizon: pred_len={name['pred_len']}")
        if log["completed"]:
            lines.append("Stage: finished")
        elif log["is_testing"]:
            lines.append("Stage: testing")
        elif log["epoch_running"] is not None:
            epoch_done = log["epoch_done"] or max(log["epoch_running"] - 1, 0)
            lines.append(f"Stage: epoch {epoch_done} finished, continuing epoch {log['epoch_running']}")
        elif log["epoch_done"] is not None:
            lines.append(f"Stage: finished up to epoch {log['epoch_done']}")
        else:
            lines.append("Stage: started, but no epoch status parsed yet")
        if report["current_left_time_sec"] is not None:
            lines.append(f"Current sub-run ETA: {format_seconds(report['current_left_time_sec'])}")
        if report["stall_warning"]:
            lines.append(f"Warning: {report['stall_warning']}")
    else:
        lines.append("No running sub-experiment was parsed.")

    lines.append("")
    lines.append("Completed Runs")
    completed_runs = report["completed_runs"]
    if completed_runs:
        for item in completed_runs[-5:]:
            name = item["name"]
            log = item["log"]
            lines.append(
                f"{name['variant']} / {name['dataset']} / pred_len={name['pred_len']} finished | "
                f"MSE = {log['mse']} | MAE = {log['mae']}"
            )
    else:
        lines.append("No completed sub-experiment detected yet.")

    lines.append("")
    lines.append("Progress")
    total = report["plan_total"]
    launched_count = report["launched_count"]
    completed_count = report["completed_count"]
    running_index = min(completed_count + 1, total or launched_count or 0) if (total or launched_count) else 0
    lines.append(f"Planned total: {total if total is not None else 'unknown'}")
    lines.append(f"Completed: {completed_count} / {total if total is not None else launched_count}")
    lines.append(f"Launched: {launched_count} / {total if total is not None else launched_count}")
    if current:
        lines.append(f"Running index: {running_index} / {total if total is not None else launched_count}")
    if report["avg_completed_runtime_sec"] is not None:
        lines.append(f"Average finished sub-run time: {format_seconds(report['avg_completed_runtime_sec'])}")
    if report["total_remaining_sec"] is not None:
        lines.append(f"Whole batch ETA: {format_seconds(report['total_remaining_sec'])}")

    lines.append("")
    lines.append("Process Snapshot")
    if report["process_snapshot"]:
        lines.extend(report["process_snapshot"])
    else:
        lines.append("No matching process was detected.")

    return "\n".join(lines)
