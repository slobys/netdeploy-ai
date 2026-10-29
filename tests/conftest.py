import os
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix='nd-tests-'))
os.environ['NETDEPLOY_ADMIN_TOKEN'] = 'test-only-' + 'a' * 32
os.environ['NETDEPLOY_DATA'] = str(root)
