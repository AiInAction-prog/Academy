#!/usr/bin/env python3
"""
Discover Available Accounts - Find all accounts accessible to your API credentials
"""

import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Token management
token_info = {
    'token': None,
    'acquired_at': None,
    'expires_in': 3600
}

def authenticate_and_get_token():
    """Authenticate with TopstepX API"""
    url = "https://api.topstepx.com/api/Auth/loginKey"
    payload = {
        "userName": os.getenv("TSX_USERNAME"),
        "apiKey": os.getenv("API_KEY")
    }
    headers = {
        "Content-Type": "application/json"
    }
    try:
        print(f"[AUTH] Authenticating with TopstepX API...")
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            token = data.get("token")
            expires_in = data.get("expiresIn", 3600)
            if token:
                print(f"[AUTH] Successfully authenticated")
                return token, datetime.now(timezone.utc), expires_in
            else:
                print(f"[AUTH] No token in response: {data}")
        else:
            print(f"[AUTH] Authentication failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[AUTH] Error during authentication: {e}")
    return None, None, None

def get_valid_token():
    """Return a valid token, refreshing if expired"""
    now = datetime.now(timezone.utc)
    if token_info['token'] is None or token_info['acquired_at'] is None or \
       (now - token_info['acquired_at']).total_seconds() > (token_info['expires_in'] - 60):
        print("[AUTH] Token expired or not present. Authenticating...")
        token, acquired_at, expires_in = authenticate_and_get_token()
        if token:
            token_info['token'] = token
            token_info['acquired_at'] = acquired_at
            token_info['expires_in'] = expires_in
        else:
            raise Exception("[AUTH] Could not obtain a valid token.")
    return token_info['token']

def get_auth_headers():
    """Return headers with current valid token"""
    return {
        "Authorization": f"Bearer {get_valid_token()}",
        "Content-Type": "application/json"
    }

def get_user_info():
    """Get user information"""
    url = "https://api.topstepx.com/api/User/me"
    headers = get_auth_headers()
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Failed to get user info: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Error getting user info: {e}")
        return None

def get_accounts():
    """Get all accounts for the user"""
    headers = get_auth_headers()
    url = "https://api.topstepx.com/api/Account/search"
    body = {"request": {}}
    try:
        print(f"🔍 Trying POST {url} with body {body}")
        response = requests.post(url, headers=headers, json=body, timeout=15)
        print(f"📡 Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and 'accounts' in data:
                print(f"✅ Found accounts using POST {url}")
                return data['accounts']
            elif isinstance(data, list):
                print(f"✅ Found accounts using POST {url}")
                return data
            else:
                print(f"⚠️ Unexpected response format: {data}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error with POST {url}: {e}")
    return []

def get_contracts():
    """Get available contracts"""
    url = "https://api.topstepx.com/api/Market/contracts"
    headers = get_auth_headers()
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Failed to get contracts: {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ Error getting contracts: {e}")
        return []

def test_account_access(account_id):
    """Test if we can access a specific account"""
    url = f"https://api.topstepx.com/api/Account/{account_id}"
    headers = get_auth_headers()
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        return None

def main():
    """Discover accounts and contracts"""
    print("🔍 Discovering Available Accounts...")
    print("=" * 50)
    
    # Get user info
    user_info = get_user_info()
    if user_info:
        print(f"👤 User Information:")
        print(f"   User ID: {user_info.get('id', 'N/A')}")
        print(f"   Username: {user_info.get('userName', 'N/A')}")
        print(f"   Email: {user_info.get('email', 'N/A')}")
        print()
    
    # Get all accounts
    accounts = get_accounts()
    accessible_accounts = []
    if accounts:
        print(f"📊 Accessible Accounts:")
        for account in accounts:
            account_id = account.get('id')
            account_name = account.get('name', 'Unknown')
            account_type = account.get('type', 'Unknown')
            balance = account.get('balance', 0)
            
            # Test access to this account
            account_details = test_account_access(account_id)
            if account_details:
                accessible_accounts.append(account)
                print(f"   Account ID: {account_id}")
                print(f"   Name: {account_name}")
                print(f"   Type: {account_type}")
                print(f"   Balance: ${balance:,.2f}")
                print(f"   ✅ Accessible")
                equity = account_details.get('equity', 0)
                print(f"   Equity: ${equity:,.2f}")
                print()
        if not accessible_accounts:
            print("❌ No accessible accounts found")
            print()
    else:
        print("❌ No accounts found or access denied")
        print()
    
    # Get available contracts
    contracts = get_contracts()
    if contracts:
        print(f"📈 Available Contracts:")
        # Filter for futures contracts
        futures_contracts = [c for c in contracts if 'F.US.' in c.get('id', '')]
        for contract in futures_contracts[:10]:  # Show first 10
            contract_id = contract.get('id')
            name = contract.get('name', 'Unknown')
            print(f"   {contract_id} - {name}")
        print(f"   ... and {len(futures_contracts) - 10} more futures contracts")
        print()
    
    print("💡 Next Steps:")
    print("   1. Note the correct Account ID from above")
    print("   2. Update the ACCOUNT_ID in your trading scripts")
    print("   3. Choose a contract ID for trading")
    print("   4. Test with small position sizes first")

if __name__ == "__main__":
    main() 
