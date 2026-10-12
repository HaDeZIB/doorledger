"""Write web/dashboard/lib/mock/messages.json from the backend templates.

    uv run --package doorledger python scripts/export_mock_messages.py

The hosted demo (mock mode) shows exactly what the backend would send; see
core/src/doorledger/demo_export.py.
"""

from doorledger.demo_export import MOCK_MESSAGES, render

if __name__ == "__main__":
    MOCK_MESSAGES.write_text(render())
    print(f"wrote {MOCK_MESSAGES}")
