import requests
import json

def inspect_api():
    url = "https://api.builder.aws.com/cs/content/feed"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "builder-session-token": "dummy"
    }
    payload = {
        "contentType": "ARTICLE",
        "pageSize": 20
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        feed = data.get("feedContents", [])
        if not feed:
            print("No feed items found.")
            return

        with open("raw_api_sample.json", "w", encoding="utf-8") as f:
            json.dump(feed, f, indent=2)
        
        print(f"Sample data saved to raw_api_sample.json. Total items: {len(feed)}")
        
        # Check for any field that might indicate region
        all_keys = set()
        for item in feed:
            for k in item.keys():
                all_keys.add(k)
        
        print("\nAvailable keys in feed items:")
        print(", ".join(sorted(list(all_keys))))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_api()
