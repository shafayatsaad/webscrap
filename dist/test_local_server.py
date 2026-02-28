from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

o = Options()
o.add_argument('--headless=new')
d = webdriver.Chrome(options=o)
d.set_capability("goog:loggingPrefs", {"browser": "ALL"})
d.get('http://localhost:8000/')
time.sleep(5)

# Try fetching logs
logs = d.get_log("browser")
for log in logs:
    print(f"Browser Log: [{log['level']}] {log['message']}")

html = d.page_source
if "Loaded fallback LOCAL data" in html or "data from GitHub" in html:
    print("Fallback script is visible in the HTML")

if "AIdeas Analyzer" in html:
    print("Page rendered text successfully")

d.quit()
