import os
import sys
import logging


def configure_logging(name):
    base_dir = os.environ.get("DIST")
    if not base_dir:
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            filename=os.path.join(logs_dir, f"{name}.log"),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            encoding="utf-8",
        )

    return logging.getLogger(name)
