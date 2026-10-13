
import os, site, sys

# First, drop system-sites related paths.
original_sys_path = sys.path[:]
known_paths = set()
for path in {'c:\\code\\vnm\\chatbot_odoo_hr_test\\.ai-gateway-benchmark-staging\\client\\.venv\\lib\\site-packages', 'c:\\code\\vnm\\chatbot_odoo_hr_test\\.ai-gateway-benchmark-staging\\client\\.venv'}:
    site.addsitedir(path, known_paths=known_paths)
system_paths = set(
    os.path.normcase(path)
    for path in sys.path[len(original_sys_path):]
)
original_sys_path = [
    path for path in original_sys_path
    if os.path.normcase(path) not in system_paths
]
sys.path = original_sys_path

# Second, add lib directories.
# ensuring .pth file are processed.
for path in ['C:\\code\\vnm\\chatbot_odoo_hr_test\\.ai-gateway-benchmark-staging\\client\\pip-build-env-km065ho_\\overlay\\Lib\\site-packages', 'C:\\code\\vnm\\chatbot_odoo_hr_test\\.ai-gateway-benchmark-staging\\client\\pip-build-env-km065ho_\\normal\\Lib\\site-packages']:
    assert not path in sys.path
    site.addsitedir(path)
