import pytest

from app.scoring import km, nearest_cell, pick, score, spearman, stability


def store(id, lat, lon, metro="M"):
    return {"id": id, "name": id, "address": "", "lat": lat, "lon": lon, "metro": metro}


def cell(lat, lon, affinity, popularity=0.9):
    return {"lat": lat, "lon": lon, "affinity": affinity, "popularity": popularity}


def test_km_one_degree_latitude():
    assert round(km(0, 0, 1, 0)) == 111


def test_nearest_cell_picks_closest_and_respects_max():
    cells = [cell(40.0, -74.0, 0.1), cell(40.01, -74.0, 0.9)]
    assert nearest_cell(cells, 40.009, -74.0)["affinity"] == 0.9
    assert nearest_cell(cells, 40.05, -74.0) is None  # ~4.4 km away
    assert nearest_cell([], 40.0, -74.0) is None


def test_score_z_scores_and_sorts():
    stores = [store("lo", 0.0, 0.2), store("hi", 0.0, 0.0), store("mid", 0.0, 0.1)]
    cells = {"M": {"T1": [cell(0.0, 0.0, 0.9), cell(0.0, 0.1, 0.5), cell(0.0, 0.2, 0.1)]}}
    out = score(stores, cells, {"T1": 1.0})
    assert [s["id"] for s in out] == ["hi", "mid", "lo"]
    assert [s["fit"] for s in out] == [1.22, 0.0, -1.22]
    assert all(s["confidence"] == "high" for s in out)


def test_score_weighted_mean_across_items():
    stores = [store("a", 0.0, 0.0), store("b", 0.0, 0.1)]
    cells = {"M": {"T1": [cell(0.0, 0.0, 1.0), cell(0.0, 0.1, 0.0)],
                   "T2": [cell(0.0, 0.0, 0.0), cell(0.0, 0.1, 1.0)]}}
    by_id = {s["id"]: s for s in score(stores, cells, {"T1": 3.0, "T2": 1.0})}
    assert by_id["a"]["affinity"] == 0.75
    assert by_id["b"]["affinity"] == 0.25


def test_missing_data_rules():
    stores = [store("a", 0.0, 0.0), store("b", 0.0, 0.1), store("far", 10.0, 10.0),
              store("nodata", 0.0, 0.0, metro="M2")]
    cells = {"M": {"T1": [cell(0.0, 0.0, 0.9, popularity=0.1), cell(0.0, 0.1, 0.5)]}}
    by_id = {s["id"]: s for s in score(stores, cells, {"T1": 1.0})}
    assert by_id["far"]["affinity"] == 0.0 and by_id["far"]["confidence"] == "low"  # city has data, none nearby
    assert by_id["nodata"]["fit"] is None and by_id["nodata"]["confidence"] == "none"  # city has no data
    assert by_id["a"]["confidence"] == "low"  # popularity below MIN_POPULARITY
    out = score(stores, cells, {"T1": 1.0})
    assert [s["id"] for s in out] == ["a", "b", "far", "nodata"]


def test_item_without_city_data_is_skipped_not_penalized():
    stores = [store("a", 0.0, 0.0), store("b", 0.0, 0.1)]
    cells = {"M": {"T1": [cell(0.0, 0.0, 0.8), cell(0.0, 0.1, 0.4)], "T2": []}}
    by_id = {s["id"]: s for s in score(stores, cells, {"T1": 1.0, "T2": 1.0})}
    assert by_id["a"]["affinity"] == 0.8


def test_single_scored_store_gets_zero_fit():
    out = score([store("a", 0.0, 0.0)], {"M": {"T1": [cell(0.0, 0.0, 0.5)]}}, {"T1": 1.0})
    assert out[0]["fit"] == 0.0


def test_pick_no_overlap_and_bottom_worst_first():
    scored = [{"id": str(i), "fit": f} for i, f in enumerate([2.0, 1.0, 0.5, 0.0, -0.5, -1.0])]
    top, bottom = pick(scored)
    assert [s["id"] for s in top] == ["0", "1", "2", "3", "4"]
    assert [s["id"] for s in bottom] == ["5"]
    scored.append({"id": "x", "fit": None})
    top, bottom = pick(scored, top_n=2, bottom_n=2)
    assert [s["id"] for s in bottom] == ["5", "4"]


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 2], [1, 2, 3]) == pytest.approx(0.866, abs=1e-3)  # ties get average ranks
    assert spearman([1, 2], [1, 2]) is None
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def four_stores():
    return [store(f"s{i}", 0.0, i * 0.1) for i in range(4)]


def cells_for(affinities):
    return [cell(0.0, i * 0.1, a) for i, a in enumerate(affinities)]


def test_stability_agreeing_items_is_one():
    cells = {"M": {"T1": cells_for([0.9, 0.7, 0.5, 0.3]), "T2": cells_for([0.8, 0.6, 0.4, 0.2])}}
    assert stability(four_stores(), cells, {"T1": 1.0, "T2": 1.0}) == {"rho": 1.0, "weakest": "T1"}


def test_stability_finds_the_item_the_ranking_hangs_on():
    cells = {"M": {"T1": cells_for([0.9, 0.7, 0.5, 0.3]), "T2": cells_for([0.1, 0.3, 0.5, 0.7])}}
    assert stability(four_stores(), cells, {"T1": 1.0, "T2": 0.5}) == {"rho": -1.0, "weakest": "T1"}


def test_stability_needs_two_items():
    assert stability(four_stores(), {"M": {"T1": cells_for([0.9, 0.7, 0.5, 0.3])}}, {"T1": 1.0}) is None
