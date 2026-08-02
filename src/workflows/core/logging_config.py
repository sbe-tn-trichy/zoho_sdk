import logging
import sys

def setup_logging(level=logging.INFO):
    """
    Configures a basic console logging handler for the application scripts.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
