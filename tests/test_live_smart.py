"""Live: meaning-based memory recall, documents Q&A and the research agent, with the real embedding model.
Run with:  pytest --live -s tests/test_live_smart.py
"""
from datetime import date, timedelta

import pytest

from aura import documents, embeddings, memory


def ask(aura, message):
    called, reply = [], []
    for e in aura.stream(message):
        if e.kind == "tool":
            called.append(e.text)
        elif e.kind == "token":
            reply.append(e.text)
    text = "".join(reply)
    print(f"> {message}\n  tools={called}\n  {text[:400]!r}\n")
    return called, text


@pytest.fixture
def real_embeddings(monkeypatch):
    if not embeddings.available():
        pytest.skip("embedding model not available")
    monkeypatch.setattr(embeddings, "current", embeddings.LocalEmbeddings())


@pytest.mark.live
def test_recall_by_meaning(aura_agent, real_embeddings):
    # Too old to be in the prompt, and no shared words with the question: only meaning-based recall finds it.
    memory.add_day_note("Started learning guitar with Ahmed", date.today() - timedelta(days=12))
    memory.add_fact("Studies CS at FAST")
    called, reply = ask(aura_agent, "what instrument did I start learning a while back?")
    assert "memory:recall" in called and "guitar" in reply.lower()


@pytest.mark.live
def test_documents_question(aura_agent, real_embeddings, home):
    uni = home / "uni"
    uni.mkdir()
    (uni / "networks.md").write_text("# Computer Networks\n\nTCP uses a three-way handshake (SYN, SYN-ACK, ACK).\n\n"
                                     "## Final exam\nThe final covers chapters 1-6 and takes place in hall B on 21 October.")
    (uni / "recipes.txt").write_text("Chicken karahi: tomatoes, ginger, garlic, green chillies.")
    documents.add_folder(str(uni))
    documents.index_all()
    called, reply = ask(aura_agent, "according to my notes, where is the final exam held?")
    assert "documents" in called and "hall b" in reply.lower() and "networks" in reply.lower()


@pytest.mark.live
def test_research_with_citations(aura_agent):
    called, reply = ask(aura_agent, "compare Python vs Rust for a complete beginner")
    assert "research" in called
    assert "[1]" in reply and "http" in reply  # inline citations and a source list survive the hand-off
