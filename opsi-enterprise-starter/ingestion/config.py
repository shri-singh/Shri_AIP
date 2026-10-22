from pathlib import Path
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)

def env(name, default=''):
    return os.environ.get(name, default)

def integer(name, default):
    return int(env(name, str(default)))

BUCKET = env('OPSI_ARCHIVE_BUCKET')
REGION = env('AWS_REGION','us-west-2')
TENANT = env('OPSI_TENANT_ID','default-lab')
STATE_PATH = Path(env('WORKER_STATE_DB','.state/checkpoints.sqlite3'))
BATCH_SIZE = integer('INGEST_BATCH_SIZE',500)
