"""
Project Veronica — Main Entry Point.
Distributed Edge-IoT Classroom Capture & Digital Lectern System.
"""
import os
import sys

# Add modules directory to sys.path so all imports resolve seamlessly
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, "modules")

if MODULES_DIR not in sys.path:
    sys.path.insert(0, MODULES_DIR)

from main import main

if __name__ == "__main__":
    main()
