import logging
from logging.handlers import RotatingFileHandler

def setup_logging(verbose: bool = False, log_file=None):
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(RotatingFileHandler(log_file, maxBytes=1<<20, backupCount=2))
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
