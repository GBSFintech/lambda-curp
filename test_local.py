# test_local.py
from handler import handler

event = {
    "user_id": "4984"
}

response = handler(event, None)
print(response)
