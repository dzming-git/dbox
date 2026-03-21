from services.service_manager import start_service
import json

result = start_service('web')
print(json.dumps(result, indent=2))
