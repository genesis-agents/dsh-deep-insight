"""Render an evidence-linked original page into a separate, rebuildable UI cache."""
import json
import sys
from pathlib import Path
from insight.adapters.export.narrative import render_pdf_page
from insight.adapters.persistence.objects import atomic_write

source, target = Path(sys.argv[1]), Path(sys.argv[2])
target.parent.mkdir(parents=True, exist_ok=True)
atomic_write(target, render_pdf_page(source.read_bytes(), int(sys.argv[3]), target.parent))
print(json.dumps({"rendered": True}))
