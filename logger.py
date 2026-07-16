import logging
import os

LOG_FOLDER = "logs"
LOG_FILE = "scanner.log"

os.makedirs(LOG_FOLDER, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_FOLDER, LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s"
)

logger = logging.getLogger("StockScanner")