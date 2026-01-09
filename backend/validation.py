"""
Input validation utilities for PredictGram
Provides validation functions for all user inputs
"""

import re

# Constants
MAX_BET_AMOUNT = 100000
MIN_BET_AMOUNT = 1
MAX_USERNAME_LENGTH = 30
MIN_USERNAME_LENGTH = 3

def validate_bet_amount(amount):
    """
    Validate bet amount
    Returns: (is_valid, result_or_error)
    """
    try:
        amount = int(amount)
        if amount < MIN_BET_AMOUNT:
            return False, f"Minimum bet is {MIN_BET_AMOUNT} credits"
        if amount > MAX_BET_AMOUNT:
            return False, f"Maximum bet is {MAX_BET_AMOUNT} credits"
        return True, amount
    except (ValueError, TypeError):
        return False, "Invalid bet amount format"


def validate_username(username):
    """
    Validate username format
    Returns: (is_valid, result_or_error)
    """
    if not username or not isinstance(username, str):
        return False, "Username is required"

    username = username.strip()

    if len(username) < MIN_USERNAME_LENGTH:
        return False, f"Username must be at least {MIN_USERNAME_LENGTH} characters"

    if len(username) > MAX_USERNAME_LENGTH:
        return False, f"Username must be at most {MAX_USERNAME_LENGTH} characters"

    # Alphanumeric, underscore, hyphen only
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        return False, "Username can only contain letters, numbers, underscore, and hyphen"

    return True, username


def validate_direction(direction):
    """
    Validate bet direction
    Returns: (is_valid, result_or_error)
    """
    if direction not in ['up', 'down', 'higher', 'lower']:
        return False, "Direction must be 'up', 'down', 'higher', or 'lower'"
    return True, direction


def validate_solana_address(address):
    """
    Validate Solana token address format
    Returns: (is_valid, result_or_error)
    """
    if not address or not isinstance(address, str):
        return False, "Token address is required"

    address = address.strip()

    # Solana addresses are base58 encoded, typically 32-44 characters
    if len(address) < 32 or len(address) > 44:
        return False, "Invalid Solana address length"

    # Check if it's base58 (alphanumeric excluding 0OIl)
    if not re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', address):
        return False, "Invalid Solana address format"

    return True, address


def validate_crypto_symbol(symbol):
    """
    Validate cryptocurrency symbol
    Returns: (is_valid, result_or_error)
    """
    valid_symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'MATIC', 'XRP', 'ADA', 'DOGE', 'DOT', 'AVAX']

    if symbol not in valid_symbols:
        return False, f"Invalid crypto symbol. Must be one of: {', '.join(valid_symbols)}"

    return True, symbol


def validate_stock_symbol(symbol):
    """
    Validate stock symbol
    Returns: (is_valid, result_or_error)
    """
    valid_symbols = ['AAPL', 'GOOGL', 'AMZN', 'MSFT', 'TSLA', 'META', 'NVDA', 'NFLX']

    if symbol not in valid_symbols:
        return False, f"Invalid stock symbol. Must be one of: {', '.join(valid_symbols)}"

    return True, symbol


def validate_duration(duration):
    """
    Validate custom bet duration
    Returns: (is_valid, result_or_error)
    """
    valid_durations = [15, 30, 60]

    try:
        duration = int(duration)
        if duration not in valid_durations:
            return False, f"Duration must be one of: {', '.join(map(str, valid_durations))} minutes"
        return True, duration
    except (ValueError, TypeError):
        return False, "Invalid duration format"


def validate_onchain_category(category):
    """
    Validate on-chain prediction category
    Returns: (is_valid, result_or_error)
    """
    valid_categories = ['pumpfun_launches', 'pumpfun_graduations']

    if category not in valid_categories:
        return False, f"Invalid category. Must be one of: {', '.join(valid_categories)}"

    return True, category


def sanitize_string(text, max_length=1000):
    """
    Sanitize user input string
    Returns: sanitized string
    """
    if not text or not isinstance(text, str):
        return ""

    # Remove control characters and trim
    text = ''.join(char for char in text if ord(char) >= 32 or char == '\n')
    text = text.strip()

    # Limit length
    if len(text) > max_length:
        text = text[:max_length]

    return text
