import time
import json
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

o = Options()
o.add_argument('--headless=new')
o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
d = webdriver.Chrome(options=o)
d.get('https://builder.aws.com')
time.sleep(5)

# Trigger a feed request by scrolling once
d.execute_script("window.scrollTo(0, document.body.scrollHeight);")
time.sleep(2)

target_headers = {}
cookies = d.get_cookies()

for e in d.get_log('performance'):
    try:
        m = json.loads(e['message'])['message']
        if m['method'] == 'Network.requestWillBeSent':
            req = m.get('params', {}).get('request', {})
            if '/cs/content/feed' in req.get('url', ''):
                target_headers = req.get('headers', {})
                break
    except:
        pass

d.quit()

print(f"Captured {len(target_headers)} headers.")
if target_headers:
    s = requests.Session()
    # Apply verbatim
    for k, v in target_headers.items():
        if k.lower() not in ['content-length', 'accept-encoding']:
            s.headers[k] = v
            
    # Apply cookies
    for c in cookies:
        s.cookies.set(c['name'], c['value'])
        
    print("Testing article fetch...")
    res = s.post('https://builder.aws.com/cs/content/feed', json={'contentType': 'article', 'pageSize': 50})
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        data = res.json()
        print(f"Success! Got {len(data.get('feedContents', []))} items. Next: {bool(data.get('nextToken'))}")
    else:
        print(res.text[:200])
