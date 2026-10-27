import os
import sys

# Backend modules import each other flat (from controller import ...), so tests
# under backend/tests/ need backend/ on sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
