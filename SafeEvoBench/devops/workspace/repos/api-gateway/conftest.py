"""Root conftest - adds src directory to Python path."""

import sys
from pathlib import Path

# Add src/ to path so tests can import modules directly
sys.path.insert(0, str(Path(__file__).parent / "src"))
