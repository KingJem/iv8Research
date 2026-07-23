import httpcloak

PROXY = "http://127.0.0.1:7890"

TARGET_URL = "https://www.cvs.com/shop/cvs-health-distilled-water-128-oz-prodid-1190732"


session = httpcloak.Session(preset="chrome-146-windows",)


resp = session.get(TARGET_URL)

print(resp.text)
print(resp.status_code)