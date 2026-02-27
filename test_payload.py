import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

o = Options()
o.add_argument('--headless=new')
o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
d = webdriver.Chrome(options=o)
d.get('https://builder.aws.com')
time.sleep(5)

# Scroll to trigger feed fetch
d.execute_script('window.scrollTo(0, document.body.scrollHeight);')
time.sleep(3)

req = {}
for e in d.get_log('performance'):
    try:
        m = json.loads(e['message'])['message']
        if m['method'] == 'Network.requestWillBeSent':
            r = m.get('params', {}).get('request', {})
            if '/cs/content/feed' in r.get('url', ''):
                req = r
                break
    except:
        pass
d.quit()

print(json.dumps(req, indent=2))
