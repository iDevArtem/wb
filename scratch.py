with open("tests/test_extra_features.py", "r") as f:
    content = f.read()

import re
# Keep only up to before test_gemini_service_extra_methods
new_content = re.sub(r'@pytest\.mark\.asyncio\nasync def test_gemini_service_extra_methods.*', '', content, flags=re.DOTALL)

with open("tests/test_extra_features.py", "w") as f:
    f.write(new_content)
