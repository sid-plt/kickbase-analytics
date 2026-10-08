from sofascore_kickbase_points import eligibility_metadata, qualifies_for_average


def test_post_md3_eligibility_accepts_45_minutes_in_latest_match_only():
    ordered = [101, 102, 103]
    assert qualifies_for_average({103}, ordered, 4, 45)
    assert qualifies_for_average({103}, ordered, 4, 90)
    assert not qualifies_for_average({103}, ordered, 4, 44)
    assert not qualifies_for_average({102}, ordered, 4, None)


def test_existing_post_md3_eligibility_routes_remain_available():
    ordered = [101, 102, 103]
    assert qualifies_for_average({102, 103}, ordered, 4, 20)
    assert qualifies_for_average({101, 102, 103}, ordered, 4, 0)
    assert qualifies_for_average({103}, ordered, 3, 90)  # Existing MD2–3 latest-match route.


def test_eligibility_metadata_documents_latest_match_minutes_exception():
    assert eligibility_metadata(4)["latest_match_minutes_exception"] == {
        "enabled": True, "minimum_minutes": 45,
    }
    assert eligibility_metadata(3)["latest_match_minutes_exception"] == {
        "enabled": False, "minimum_minutes": None,
    }


def test_goalkeeper_one_appearance_exception_applies_at_every_matchday():
    ordered = [101, 102, 103, 104, 105]
    assert qualifies_for_average({101}, ordered, 1, position="GK")
    assert qualifies_for_average({103}, ordered, 4, position="GK")
    assert qualifies_for_average({101}, ordered, 34, position="G")
    assert not qualifies_for_average({101}, ordered, 4, position="DEF")
    assert eligibility_metadata(4)["goalkeeper_appearance_exception"] == (
        "One appearance in the sampled last five matches."
    )
