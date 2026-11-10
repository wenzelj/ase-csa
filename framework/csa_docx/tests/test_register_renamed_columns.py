from csa_docx import doc_spec


def test_a_register_with_the_frame_columns_is_still_a_register(monkeypatch):
    from csa_docx import topic_frames
    monkeypatch.setattr(topic_frames, "frame_for", lambda h: {"register_columns": ["GPO Name", "Category", "Applied on"]})
    node = {"title": "Group Policy Observations",
            "parts": [{"kind": "reference", "columns": ["GPO Name", "Category", "Applied on"]}]}
    tparts = [{"kind": "register", "columns": ["GPO Name", "Category", "[Host group 1]"]}]
    doc_spec._align(node, tparts)
    assert node["parts"][0]["kind"] == "register"
