from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_dashboard_smoke():
    app = Path(__file__).parents[1] / "app" / "app.py"
    result = AppTest.from_file(str(app), default_timeout=30).run()
    assert not result.exception
    assert result.subheader[0].value == "Material variances"
    assert result.metric[0].value == "1"
    assert result.metric[2].value == "1/1"
