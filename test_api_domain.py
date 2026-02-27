import time
import json
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

print("1. Launching Chrome briefly to acquire token & cookies...")
o = Options()
o.add_argument('--headless=new')
o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
d = webdriver.Chrome(options=o)
d.get('https://builder.aws.com')
time.sleep(3)
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

print(f"2. Got {len(target_headers)} headers. Testing REAL API domain...")

if target_headers:
    s = requests.Session()
    for k, v in target_headers.items():
        if k.lower() not in ['content-length', 'accept-encoding']:
            s.headers[k] = v
    s.headers['Origin'] = 'https://builder.aws.com'
    s.headers['Referer'] = 'https://builder.aws.com/'
    
    for c in cookies:
        s.cookies.set(c['name'], c['value'])
        
    print("3. Querying https://api.builder.aws.com/cs/content/feed...")
    res = s.post('https://api.builder.aws.com/cs/content/feed', json={'contentType': 'article', 'pageSize': 100})
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        data = res.json()
        print(f"Success! Got {len(data.get('feedContents', []))} items. NextToken: {bool(data.get('nextToken'))}")
    else:
        print("Failed:")
        print(res.text[:200])
