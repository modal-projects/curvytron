import os
from pathlib import Path

APP_NAME = "curvytron"
CURVYTRON_REPO = "https://github.com/Curvytron/curvytron"
CURVYTRON_COMMIT = "0051e59b173c244dfe30e539a227b01dc8216186"
CURVYTRON_DIR = "/curvytron"
CURVYTRON_PATCH = Path(__file__).with_name("curvytron.patch")
# Custom domain for the lobby, set at deploy time and forwarded to containers through `DOMAIN_ENV`.
LOBBY_DOMAIN = os.environ.get("CURVYTRON_DOMAIN") or None
DOMAIN_ENV = {"CURVYTRON_DOMAIN": LOBBY_DOMAIN} if LOBBY_DOMAIN else None

MINUTES = 60
PORT = 8020
ROOMS_PER_CONTAINER = 10
TARGET_ROOMS_PER_CONTAINER = 3
MAX_CONTAINERS = 10
BUFFER_CONTAINERS = 1
REGION = "us-east"
ASHBURN_METRO = [
    "us-east-1",  # AWS N. Virginia (where the us-east proxies run)
    "us-east4",  # GCP Ashburn
    "us-ashburn-1",  # OCI Ashburn
    "ASH",  # lat Ashburn (case-sensitive)
    "ashburn",  # rkd Ashburn
]
ROOM_IDLE_TIMEOUT = 5 * MINUTES
ROOM_NAME_MAX_LENGTH = 25
SESSION_QUEUE_TIMEOUT = 120
WARMUP_SESSION_IDLE_TIMEOUT = 5
ROOM_SCALEDOWN_WINDOW = 300
LOBBY_SCALEDOWN_WINDOW = 300
ROOMS_CACHE_TTL = 2
WARMUP_INTERVAL = 60
