import argparse
from pathlib import Path

from cloud_status_core import collect_report, format_report, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Check cloud experiment status over SSH.")
    parser.add_argument(
        "--config",
        default="yun_gpu_checker_config.example.json",
        help="Path to JSON config file.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    cfg = load_config(config_path)
    report = collect_report(cfg)
    print(format_report(report))


if __name__ == "__main__":
    main()
