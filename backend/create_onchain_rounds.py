"""
Manual script to create on-chain prediction rounds
Run this to create the first rounds for testing
"""

import sys
import os

# Add parent directory to path to import main modules
sys.path.insert(0, os.path.dirname(__file__))

from main import create_onchain_round
from dune_client import PREDICTION_CATEGORIES

print("=" * 60)
print("Creating On-Chain Prediction Rounds")
print("=" * 60)

for category_id in PREDICTION_CATEGORIES.keys():
    print(f"\n[*] Creating round for: {category_id}")
    create_onchain_round(category_id)
    print(f"[+] Round created successfully!")

print("\n" + "=" * 60)
print("All rounds created! Visit http://localhost:5173/onchain to test")
print("=" * 60)
