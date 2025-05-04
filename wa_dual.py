import requests
import time

def get_dero_difficulty(node_url="http://192.168.1.5:20206/json_rpc"):
    """Query the Dero node's network difficulty."""
    payload = {
        "jsonrpc": "2.0",
        "id": "0",
        "method": "get_info"
    }
    try:
        response = requests.post(node_url, json=payload, timeout=1)
        if response.status_code == 200:
            data = response.json()
            print(data["result"]["difficulty"])
            return data["result"]["difficulty"]
        else:
            print(f"Failed to query Dero node. Status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error querying Dero node: {e}")
        return None
    
get_dero_difficulty()