import os

import pytest

from aura import documents, tools


@pytest.fixture
def uni(home):
    folder = home / "uni"
    folder.mkdir()
    (folder / "networks.md").write_text("TCP uses a three way handshake. UDP is connectionless.\n\nThe final exam is in hall B.")
    (folder / "recipes.txt").write_text("Chicken karahi needs tomatoes ginger garlic and green chillies.")
    (folder / "photo.png").write_bytes(b"\x89PNG not indexed")
    return folder


def test_index_and_search(uni):
    documents.add_folder("~/uni")
    status = documents.index_all()
    assert status["files"] == 2 and status["passages"] >= 2  # the .png is skipped
    hit = documents.search("karahi ginger garlic", k=1)[0]
    assert hit["path"].endswith("recipes.txt")


def test_reindex_skips_unchanged_and_picks_up_edits_and_deletions(uni):
    documents.add_folder(str(uni))
    documents.index_all()
    before = documents.status()["passages"]
    assert documents.index_all()["passages"] == before  # nothing changed

    (uni / "recipes.txt").write_text("Biryani needs rice saffron and yogurt.")
    os.utime(uni / "recipes.txt", (1, 1))  # make sure the mtime differs
    documents.index_all()
    assert documents.search("biryani saffron rice", k=1)[0]["text"].startswith("Biryani")

    (uni / "networks.md").unlink()
    assert documents.index_all()["files"] == 1


def test_removing_a_folder_drops_its_passages(uni):
    documents.add_folder(str(uni))
    documents.index_all()
    documents.remove_folder(str(uni))
    assert documents.folders() == [] and documents.status()["passages"] == 0


def test_folders_outside_home_are_refused():
    with pytest.raises(PermissionError):
        documents.add_folder("/etc")


def test_long_text_is_chunked_with_overlap():
    text = ("Sentence number %d about networking. " * 120) % tuple(range(120))
    chunks = documents._chunks(text)
    assert len(chunks) > 3 and all(len(c) <= documents.CHUNK for c in chunks)
    assert chunks[0][-30:] in text and chunks[1][:20] in chunks[0] + chunks[1]


def test_documents_tool(uni):
    assert "No document folders" in tools.documents.invoke({"query": "tcp"})
    documents.add_folder(str(uni))
    documents.index_all()
    out = tools.documents.invoke({"query": "tcp handshake udp"})
    assert "[networks.md]" in out and "handshake" in out
