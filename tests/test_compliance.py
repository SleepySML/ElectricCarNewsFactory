from ev_factory.compliance import ComplianceReport


def test_blocking_only_on_hard_failure():
    r = ComplianceReport()
    r.add("copyright_text", True, "no body stored")
    assert r.blocking is False
    r.add("style_note", False, "soft nit", hard=False)
    assert r.blocking is False
    r.add("sources_min_two", False, "only 1 source", hard=True)
    assert r.blocking is True


def test_roundtrip_dict():
    r = ComplianceReport()
    r.add("verbatim_clean", True)
    r.add("transformation_score", False, "score 40 < 70")
    d = r.to_dict()
    assert d["blocking"] is True
    r2 = ComplianceReport.from_dict(d)
    assert len(r2.checks) == 2
    assert r2.blocking is True
    assert r2.checks[0].key == "verbatim_clean"
