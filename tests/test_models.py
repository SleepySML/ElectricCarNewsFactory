from ev_factory.models import (
    ComplianceCheck,
    JobState,
    StageResult,
    StageStatus,
    make_slug,
)


def test_jobstate_values_are_lowercase_strings():
    assert JobState.IN_REVIEW.value == "in_review"
    assert JobState.PUBLISHED == "published"


def test_stage_result_ok_and_fail_helpers():
    ok = StageResult.ok("script", message="done", data={"n": 1})
    assert ok.status is StageStatus.DONE
    assert ok.data == {"n": 1}

    bad = StageResult.fail("voice", "api error")
    assert bad.status is StageStatus.FAILED
    assert bad.message == "api error"


def test_compliance_check_defaults_to_hard():
    c = ComplianceCheck(key="copyright_text", passed=True)
    assert c.hard is True


def test_make_slug_normalizes():
    assert make_slug("Tesla Cuts Model Y Price by 10%!") == "tesla-cuts-model-y-price-by-10"
    assert make_slug("  Rivian   R2  ") == "rivian-r2"
    assert len(make_slug("x" * 200)) <= 60
