"""
DexScreener API Client for fetching Solana token data
"""

import requests
import time

DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"

class DexScreenerClient:
    def __init__(self):
        self.base_url = DEXSCREENER_API

    def get_token_info(self, token_address):
        """
        Get token information from DexScreener
        Returns token data including price, mcap, volume, etc.
        """
        try:
            url = f"{self.base_url}/tokens/{token_address}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()

            if not data or 'pairs' not in data or len(data['pairs']) == 0:
                return None

            # Get the most liquid pair (usually first one)
            pair = data['pairs'][0]

            return {
                "address": token_address,
                "name": pair.get("baseToken", {}).get("name", "Unknown"),
                "symbol": pair.get("baseToken", {}).get("symbol", "Unknown"),
                "price_usd": float(pair.get("priceUsd", 0)),
                "price_native": float(pair.get("priceNative", 0)),
                "mcap": float(pair.get("fdv", 0)) if pair.get("fdv") else 0,
                "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                "pair_address": pair.get("pairAddress"),
                "dex": pair.get("dexId", "unknown"),
                "chain": pair.get("chainId", "solana"),
            }

        except Exception as e:
            print(f"[DEXSCREENER] Error fetching token {token_address}: {e}")
            return None

    def validate_token(self, token_address, min_mcap=200000):
        """
        Validate if a token is eligible for custom bets
        Returns (is_valid, token_data, error_message)
        """
        token_data = self.get_token_info(token_address)

        if not token_data:
            return False, None, "Token not found on DexScreener"

        mcap = token_data.get("mcap", 0)

        if mcap < min_mcap:
            return False, token_data, f"Market cap too low: ${mcap:,.0f} (minimum: ${min_mcap:,.0f})"

        # Additional checks
        liquidity = token_data.get("liquidity_usd", 0)
        if liquidity < 1000:  # At least $1k liquidity
            return False, token_data, f"Insufficient liquidity: ${liquidity:,.0f}"

        return True, token_data, None

    def get_multiple_tokens(self, token_addresses):
        """
        Get information for multiple tokens
        Note: DexScreener allows batch requests
        """
        results = {}

        # DexScreener supports comma-separated addresses
        if len(token_addresses) <= 30:  # API limit
            try:
                addresses_str = ",".join(token_addresses)
                url = f"{self.base_url}/tokens/{addresses_str}"
                response = requests.get(url, timeout=10)
                response.raise_for_status()

                data = response.json()

                if data and 'pairs' in data:
                    for pair in data['pairs']:
                        token_addr = pair.get("baseToken", {}).get("address")
                        if token_addr:
                            results[token_addr] = {
                                "name": pair.get("baseToken", {}).get("name", "Unknown"),
                                "symbol": pair.get("baseToken", {}).get("symbol", "Unknown"),
                                "price_usd": float(pair.get("priceUsd", 0)),
                                "mcap": float(pair.get("fdv", 0)) if pair.get("fdv") else 0,
                            }

            except Exception as e:
                print(f"[DEXSCREENER] Error fetching multiple tokens: {e}")
        else:
            # Fall back to individual requests
            for addr in token_addresses:
                token_data = self.get_token_info(addr)
                if token_data:
                    results[addr] = token_data
                time.sleep(0.1)  # Rate limiting

        return results


if __name__ == "__main__":
    # Test the client
    client = DexScreenerClient()

    # Test with a known pump.fun token (example)
    test_ca = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC for testing

    print("Testing DexScreener Client...")
    print("-" * 60)

    token_data = client.get_token_info(test_ca)
    if token_data:
        print(f"Token: {token_data['name']} ({token_data['symbol']})")
        print(f"Price: ${token_data['price_usd']}")
        print(f"Market Cap: ${token_data['mcap']:,.0f}")
        print(f"24h Volume: ${token_data['volume_24h']:,.0f}")
        print(f"Liquidity: ${token_data['liquidity_usd']:,.0f}")
    else:
        print("Token not found")

    print("\n" + "-" * 60)
    print("\nTesting validation (200k mcap minimum)...")
    is_valid, data, error = client.validate_token(test_ca, min_mcap=200000)
    print(f"Valid: {is_valid}")
    if error:
        print(f"Error: {error}")
