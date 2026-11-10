"""Read one complete persisted engine event through the application repository port."""
import json
import sys
from pathlib import Path

from insight.bootstrap import Application
from insight.entrypoints.cli import json_default

app = Application(Path(sys.argv[1]))
try:
    with app.queries.tx(None) as repo:
        events = repo.events(sys.argv[2])
    event = next((item for item in events if item["sequence"] == int(sys.argv[3])), None)
    print(json.dumps(event, ensure_ascii=False, default=json_default))
finally:
    app.close()
