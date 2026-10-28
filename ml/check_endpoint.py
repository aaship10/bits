"""Cheap end-to-end check of the published QuickML endpoint: sends at most 5 rows (default 3)
and compares each answer with the local ridge fallback. Run from the repo root with the
QUICKML_* environment variables set (see predict.py):  python ml/check_endpoint.py [N]
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import predict as P  # noqa: E402

MAX_CALLS = 5  # hard cap: the free tier allows only a few hundred prediction calls in total

n = min(int(sys.argv[1]) if len(sys.argv) > 1 else 3, MAX_CALLS)
df = pd.read_csv(Path(__file__).resolve().parent.parent / "sample_test_input.csv").head(n)
rows = P.build_features(df).to_dict(orient="records")
local = P._fallback_predict(df)
P._headers()  # token refresh / config errors surface here, before any prediction call
url = P.QUICKML_ENDPOINT_URL
import os  # noqa: E402
url = os.environ.get("QUICKML_ENDPOINT_URL", url)
for i, row in enumerate(rows):
    q = P._post_row(url, row)  # raises on 401/403/429 with the server's message
    print(f"row {i}: QuickML {q:8.2f} kW | local ridge {local[i]:8.2f} kW | diff {q - local[i]:+.2f}")
print(f"OK: {n} prediction call(s) used.")
