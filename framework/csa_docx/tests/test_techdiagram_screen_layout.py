from csa_docx.techdiagram.layout_tracks import layout


def test_screen_site_grid_places_two_sites_above_full_width_site():
    model = {
        "layout": {
            "top": [], "bottom": [], "dcs": ["rockhampton", "brisbane", "mackay"],
            "tiers": [["app", "Application"]],
            "screen_site_grid": {"columns": 2, "rows": [["brisbane", "mackay"], ["rockhampton"]]},
        },
        "nodes": [
            {"id": "B", "label": "B", "zone": "brisbane", "tier": "app"},
            {"id": "M", "label": "M", "zone": "mackay", "tier": "app"},
            {"id": "R", "label": "R", "zone": "rockhampton", "tier": "app"},
        ],
        "edges": [],
        "groups": [],
    }
    result = layout(model)
    brisbane = result["zones"]["brisbane"]
    mackay = result["zones"]["mackay"]
    rockhampton = result["zones"]["rockhampton"]
    assert brisbane[1] == mackay[1] < rockhampton[1]
    assert brisbane[2] < mackay[0]
    assert rockhampton[0] == brisbane[0]
    assert rockhampton[2] == mackay[2]
