from app.stores import load_stores


def test_load_stores(tmp_path):
    f = tmp_path / "stores.csv"
    f.write_text("id,name,address,lat,lon,metro\n"
                 "phl-1,Rittenhouse,130 S 19th St,39.95,-75.17,Philadelphia\n")
    assert load_stores(f) == [{"id": "phl-1", "name": "Rittenhouse", "address": "130 S 19th St",
                               "lat": 39.95, "lon": -75.17, "metro": "Philadelphia"}]
