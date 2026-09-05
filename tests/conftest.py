"""Put scripts/ on the import path so both the action orchestrator and the release script import by name."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
