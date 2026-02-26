from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time
import json

o = Options()
o.add_argument('--headless=new')
o.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
d = webdriver.Chrome(options=o)

d.get('https://builder.aws.com/posts')
time.sleep(5)

last_h = d.execute_script('return document.body.scrollHeight')
for i in range(15):
    d.execute_script('window.scrollTo(0, document.body.scrollHeight);')
    time.sleep(2)
    
    # Try finding load more button
    try:
        btns = d.find_elements('xpath', "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'load more')]")
        if btns:
            print(f"Found Load More on scroll {i}!")
            d.execute_script('arguments[0].click();', btns[0])
            time.sleep(2)
    except Exception as e:
        print(f"Btn error: {e}")
        
    new_h = d.execute_script('return document.body.scrollHeight')
    if new_h == last_h and not btns:
        print(f"Reached bottom at scroll {i}")
        break
    last_h = new_h

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
    except Exception:
        pass

print(f"Total posts found in network logs: {count}")
d.quit()
