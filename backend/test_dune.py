"""
Test script to see raw Dune API responses
"""
from dune_client import DuneClient, QUERIES
import json

client = DuneClient()

print("=" * 60)
print("Testing Dune Analytics Queries")
print("=" * 60)

# Test pumpfun launches query
print("\n1. Testing pump.fun Daily Launches (Query ID: {})".format(QUERIES["pumpfun_daily_launches"]))
print("-" * 60)

results = client.get_latest_result(QUERIES["pumpfun_daily_launches"])

print(f"Type of results: {type(results)}")
print(f"Length: {len(results) if results else 0}")

if results:
    print(f"\nFirst 3 rows:")
    for i, row in enumerate(results[:3]):
        print(f"\nRow {i}:")
        print(json.dumps(row, indent=2, default=str))
else:
    print("No results returned!")

# Test pumpfun graduations query
print("\n\n2. Testing pump.fun Graduations (Query ID: {})".format(QUERIES["pumpfun_daily_graduations"]))
print("-" * 60)

results2 = client.get_latest_result(QUERIES["pumpfun_daily_graduations"])

if results2:
    print(f"Length: {len(results2)}")
    print(f"\nFirst row:")
    print(json.dumps(results2[0], indent=2, default=str))
else:
    print("No results returned!")

# Test DEX volume query
print("\n\n3. Testing Solana DEX Volume (Query ID: {})".format(QUERIES["solana_dex_volume"]))
print("-" * 60)

results3 = client.get_latest_result(QUERIES["solana_dex_volume"])

if results3:
    print(f"Length: {len(results3)}")
    print(f"\nFirst row:")
    print(json.dumps(results3[0], indent=2, default=str))
else:
    print("No results returned!")

print("\n" + "=" * 60)
