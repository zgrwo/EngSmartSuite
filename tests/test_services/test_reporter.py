import os
import tempfile

from smartsuite.core.contracts import AnalysisRequest
from smartsuite.services.orchestrator import orchestrate


def test_reporter_pdf_output(sample_doe_data):
    from smartsuite.services.reporter import to_pdf
    req = AnalysisRequest(
        task="correlation", data=sample_doe_data,
        target_col="不良率", feature_cols=["料温", "模温"],
    )
    result = orchestrate(req)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = to_pdf(result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
    finally:
        os.unlink(path)


def test_reporter_ppt_output(sample_doe_data):
    from smartsuite.services.reporter import to_ppt
    req = AnalysisRequest(
        task="response_surface", data=sample_doe_data,
        target_col="强度", feature_cols=["料温", "模温"],
        params={"direction": "maximize"},
    )
    result = orchestrate(req)
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
        path = f.name
    try:
        out = to_ppt(result, path)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 1000
    finally:
        os.unlink(path)
