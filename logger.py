"""Configuração centralizada de logging / Centralized logging configuration"""
import logging
import sys

LOG_FILE = "run.log"
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_file: str = LOG_FILE, level: int = logging.INFO) -> logging.Logger:
    """Configura o logger raiz para gravar em stdout e em arquivo / Configures the root logger to write to stdout and a file"""
    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return root
