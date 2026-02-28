"""Test: Capture API details and write to a log file."""
import time, json, sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

log = []
def lg(msg):
    print(msg)
    log.append(msg)

lg("1. Launching Chrome...")
o = Options()
o.add_argument('--headless=new')
o.add_argument('--no-sandbox')
o.add_argument('--disable-dev-shm-usage')
o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
d = webdriver.Chrome(options=o)
d.execute_cdp_cmd("Network.enable", {})
d.get('https://builder.aws.com')
time.sleep(6)

# Scroll once to trigger initial feed load 
d.execute_script('window.scrollTo(0, document.body.scrollHeight);')
time.sleep(3)

# Capture all request/response details
api_requests = []
api_responses = []

for e in d.get_log('performance'):
    try:
        m = json.loads(e['message'])['message']
        if m['method'] == 'Network.requestWillBeSent':
            r = m.get('params', {}).get('request', {})
            url = r.get('url', '')
            if '/cs/content' in url and r.get('method') == 'POST':
                api_requests.append({
                    'url': url,
                    'method': r.get('method'),
                    'postData': r.get('postData', ''),
                    'headers': r.get('headers', {}),
                    'requestId': m.get('params', {}).get('requestId', ''),
                })
        elif m['method'] == 'Network.responseReceived':
            url = m['params']['response']['url']
            if '/cs/content' in url:
                rid = m['params']['requestId']
                try:
                    body = d.execute_cdp_cmd('Network.getResponseBody', {'requestId': rid})
                    data = json.loads(body.get('body', '{}'))
                    api_responses.append({
                        'url': url,
                        'items_count': len(data.get('feedContents', [])),
                        'has_next_token': data.get('nextToken') is not None,
                        'next_token_preview': str(data.get('nextToken', ''))[:50],
                        'first_item': data.get('feedContents', [{}])[0] if data.get('feedContents') else None,
                    })
                except Exception as ex:
                    api_responses.append({'url': url, 'error': str(ex)})
    except Exception:
        pass

d.quit()

# Write results
result = {
    'requests': api_requests,
    'responses': api_responses,
}

with open('test_api_results.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2, ensure_ascii=False, default=str)

lg(f"Found {len(api_requests)} POST requests, {len(api_responses)} responses")
lg(f"Results saved to test_api_results.json")

for i, req in enumerate(api_requests):
    lg(f"\nRequest {i+1}: {req['url']}")
    lg(f"  PostData: {req['postData'][:200] if req['postData'] else 'None'}")

for i, resp in enumerate(api_responses):
    lg(f"\nResponse {i+1}: {resp.get('url', '?')}")
    lg(f"  Items: {resp.get('items_count', '?')}, NextToken: {resp.get('has_next_token', '?')}")
    if resp.get('first_item'):
        fi = resp['first_item']
        lg(f"  First: [{fi.get('likesCount', 0)} likes] {fi.get('title', '?')[:60]}")
