import requests

x = requests.get(url='http://10.0.0.58:5000/session/get',json={"ip":"115.145.178.185"},headers={"Content-Type":"application/json"})
print(x.json())