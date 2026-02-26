import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

o = Options()
o.add_argument('--headless=new')
o.add_argument('--window-size=1280,1080')
o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
d = webdriver.Chrome(options=o)

d.get('https://builder.aws.com/posts')
time.sleep(5)

print("Starting deliberate viewport scrolling to trigger React intersection observers...")

# Deliberate scroll
last_h = d.execute_script("return document.body.scrollHeight")
for i in range(30):  # More steps
    # Scroll by strictly viewport height
    d.execute_script("window.scrollBy(0, window.innerHeight * 0.8);")
    time.sleep(1.5)
    
    try:
        btns = d.find_elements("xpath", "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'load more')]")
        if btns:
            print("Found LOAD MORE button, clicking...")
            d.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btns[0])
            time.sleep(0.5)
            d.execute_script("arguments[0].click();", btns[0])
            time.sleep(2)
    except:
        pass

# Extract from network logs
logs = d.get_log('performance')
count = 0
for entry in logs:
    try:
        msg = json.loads(entry['message'])['message']
        if msg['method'] == 'Network.responseReceived' and '/cs/content' in msg['params']['response']['url']:
            rid = msg['params']['requestId']
            body = d.execute_cdp_cmd('Network.getResponseBody', {'requestId': rid})
            data = json.loads(body.get('body', '{}'))
            count += len(data.get('feedContents', []))
    except:
        pass

print(f"Total posts found for /posts: {count}")
d.quit()
