"""
Dune Analytics Client for fetching on-chain metrics
Supports pump.fun and other on-chain data
"""

import requests
import os
from datetime import datetime, timedelta, timezone
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DUNE_API_KEY = os.environ.get('DUNE_API_KEY', '')
DUNE_API_BASE = "https://api.dune.com/api/v1"

# Dune query IDs for different metrics
QUERIES = {
    "pumpfun_daily_launches": 3979030,
    "pumpfun_daily_graduations": 3979025,
}

class DuneClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or DUNE_API_KEY
        self.headers = {
            "X-Dune-API-Key": self.api_key,
            "Content-Type": "application/json"
        }

    def execute_query(self, query_id, params=None):
        """Execute a Dune query and return the execution ID"""
        url = f"{DUNE_API_BASE}/query/{query_id}/execute"

        payload = {}
        if params:
            payload["query_parameters"] = params

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("execution_id")
        except Exception as e:
            print(f"[DUNE] Error executing query {query_id}: {e}")
            return None

    def get_execution_status(self, execution_id):
        """Get the status of a query execution"""
        url = f"{DUNE_API_BASE}/execution/{execution_id}/status"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[DUNE] Error getting execution status: {e}")
            return None

    def get_execution_results(self, execution_id):
        """Get the results of a completed query execution"""
        url = f"{DUNE_API_BASE}/execution/{execution_id}/results"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[DUNE] Error getting execution results: {e}")
            return None

    def run_query(self, query_id, params=None, max_wait=120):
        """Execute query and wait for results"""
        print(f"[DUNE] Executing query {query_id}...")

        # Execute the query
        execution_id = self.execute_query(query_id, params)
        if not execution_id:
            return None

        print(f"[DUNE] Execution ID: {execution_id}")

        # Poll for results
        start_time = time.time()
        while time.time() - start_time < max_wait:
            status_data = self.get_execution_status(execution_id)

            if not status_data:
                time.sleep(2)
                continue

            state = status_data.get("state")
            print(f"[DUNE] Query state: {state}")

            if state == "QUERY_STATE_COMPLETED":
                results = self.get_execution_results(execution_id)
                return results.get("result", {}).get("rows", [])
            elif state == "QUERY_STATE_FAILED":
                print(f"[DUNE] Query failed")
                return None

            time.sleep(2)

        print(f"[DUNE] Query timed out after {max_wait}s")
        return None

    def get_latest_result(self, query_id):
        """Get the latest cached result without executing"""
        url = f"{DUNE_API_BASE}/query/{query_id}/results"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("result", {}).get("rows", [])
        except Exception as e:
            print(f"[DUNE] Error getting latest result: {e}")
            return None


# Metric-specific functions
def get_pumpfun_daily_stats(date=None):
    """Get pump.fun stats for a specific date (defaults to yesterday)"""
    if date is None:
        date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    client = DuneClient()

    # For demo purposes - in production, you'd have separate queries
    # or a single parameterized query
    results = client.get_latest_result(QUERIES["pumpfun_daily_launches"])

    if not results:
        return None

    # Parse results - structure depends on your Dune query
    # Get graduations from separate query
    grad_results = client.get_latest_result(QUERIES["pumpfun_daily_graduations"])

    tokens_launched = results[0].get("tokens_launched_24h", 0) if results else 0
    tokens_graduated = grad_results[0].get("withdraw_token_last_24h", 0) if grad_results else 0

    # Calculate graduation rate
    graduation_rate = (tokens_graduated / tokens_launched * 100) if tokens_launched > 0 else 0

    return {
        "tokens_launched": tokens_launched,
        "tokens_graduated": tokens_graduated,
        "graduation_rate": round(graduation_rate, 2),
        "date": str(date)
    }




# Prediction categories configuration
PREDICTION_CATEGORIES = {
    "pumpfun_launches": {
        "name": "pump.fun Token Launches",
        "description": "Total tokens launched on pump.fun in 24 hours",
        "icon": "🚀",
        "fetch_function": lambda: get_pumpfun_daily_stats(),
        "metric_key": "tokens_launched"
    },
    "pumpfun_graduations": {
        "name": "pump.fun Graduations",
        "description": "Tokens that graduated on pump.fun in 24 hours",
        "icon": "🎓",
        "fetch_function": lambda: get_pumpfun_daily_stats(),
        "metric_key": "tokens_graduated"
    },
}


if __name__ == "__main__":
    # Test the client
    print("Testing Dune Analytics Client...")

    client = DuneClient()

    # Test getting latest result
    print("\nFetching pump.fun stats...")
    stats = get_pumpfun_daily_stats()
    print(f"Results: {stats}")
