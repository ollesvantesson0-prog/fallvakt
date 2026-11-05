import os
import sys

# Gör så att testerna hittar projektets filer (main.py, detector.py, ...)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
