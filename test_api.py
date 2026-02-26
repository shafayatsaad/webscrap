from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

o = Options()
o.add_argument('--headless=new')
o.add_argument('--window-size=1920,1080')
d = webdriver.Chrome(options=o)
d.get('https://builder.aws.com/posts')
time.sleep(5)

html = d.page_source
with open('test_page.html', 'w', encoding='utf-8') as f:
    f.write(html)
    
print(f"Saved {len(html)} bytes of HTML.")

# Also try to print some basic text to see what's visible
titles = d.find_elements('css selector', 'h2, h3, article, .title')
print(f"Found {len(titles)} potential title elements.")
for t in titles[:5]:
    text = t.text.strip()
    if text: print(text)

d.quit()
