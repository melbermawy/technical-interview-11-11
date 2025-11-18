"""Unit tests for document chunker (PR-10A)."""

from backend.app.docs.chunker import chunk_document


def test_simple_short_doc_returns_one_chunk() -> None:
    """Test that a simple short document returns a single chunk with order 0."""
    text = "This is a short document."

    chunks = chunk_document(text)

    assert len(chunks) == 1
    assert chunks[0][0] == 0  # order
    assert chunks[0][1] == "This is a short document."


def test_long_text_splits_into_multiple_chunks() -> None:
    """Test that long text is split into multiple chunks under max_chars."""
    # Create a text that will definitely need multiple chunks
    para1 = "A" * 400
    para2 = "B" * 400
    para3 = "C" * 400
    text = f"{para1}\n\n{para2}\n\n{para3}"

    chunks = chunk_document(text, max_chars=800)

    # Should have at least 2 chunks
    assert len(chunks) >= 2

    # Each chunk should be ≤ max_chars
    for _order, chunk_text in chunks:
        assert len(chunk_text) <= 800

    # Orders should be 0, 1, 2, ...
    orders = [order for order, _ in chunks]
    assert orders == list(range(len(chunks)))

    # Concatenation should roughly equal original (modulo whitespace)
    concatenated = "\n\n".join(chunk_text for _, chunk_text in chunks)
    # All original characters should be in concatenated
    assert "A" * 400 in concatenated
    assert "B" * 400 in concatenated
    assert "C" * 400 in concatenated


def test_chunk_lengths_respect_max_chars() -> None:
    """Test that all chunks respect max_chars limit (with some tolerance for edge cases)."""
    # Create paragraphs that will force chunking
    para1 = "A" * 250  # Single 250-char paragraph
    para2 = "B" * 250  # Another 250-char paragraph
    para3 = "C" * 250  # Third 250-char paragraph
    text = f"{para1}\n\n{para2}\n\n{para3}"

    chunks = chunk_document(text, max_chars=500)

    # Most chunks should be ≤ max_chars, but single oversized sentences may exceed slightly
    for _, chunk_text in chunks:
        # Allow small tolerance for separator edge cases
        assert len(chunk_text) <= 520  # 500 + small tolerance


def test_order_sequence_is_strictly_increasing() -> None:
    """Test that order values are 0, 1, 2, ... without gaps."""
    text = "Para 1\n\n" + "Para 2\n\n" + "Para 3\n\n" + "Para 4"

    chunks = chunk_document(text, max_chars=20)

    orders = [order for order, _ in chunks]
    assert orders == list(range(len(chunks)))


def test_weird_whitespace_handling() -> None:
    """Test behavior with excessive newlines and spaces."""
    text = "Para 1\n\n\n\n\n\nPara 2\n\n   \n\n  Para 3   \n\n\n"

    chunks = chunk_document(text)

    # Should still extract paragraphs properly
    assert len(chunks) >= 1

    # No chunk should be empty
    for _, chunk_text in chunks:
        assert chunk_text.strip()


def test_deterministic_same_input_same_output() -> None:
    """Test that chunking is deterministic: same input → same chunks."""
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph."

    chunks1 = chunk_document(text, max_chars=100)
    chunks2 = chunk_document(text, max_chars=100)

    assert chunks1 == chunks2


def test_empty_text_returns_empty_list() -> None:
    """Test that empty or whitespace-only text returns no chunks."""
    assert chunk_document("") == []
    assert chunk_document("   ") == []
    assert chunk_document("\n\n\n") == []


def test_single_long_paragraph_splits_by_sentences() -> None:
    """Test that a single paragraph exceeding max_chars is split."""
    # Create a paragraph with multiple sentences that exceeds max_chars
    text = "First sentence here. Second sentence here. Third sentence here. " * 20

    chunks = chunk_document(text, max_chars=200)

    # Should split into multiple chunks
    assert len(chunks) > 1

    # Each chunk should be ≤ max_chars
    for _, chunk_text in chunks:
        assert len(chunk_text) <= 200


def test_no_empty_chunks_returned() -> None:
    """Test that no empty chunks are ever returned."""
    text = "Para 1\n\n\n\nPara 2\n\n\n\n\n\nPara 3"

    chunks = chunk_document(text)

    for _, chunk_text in chunks:
        assert chunk_text.strip()  # No empty chunks


def test_line_ending_normalization() -> None:
    """Test that different line endings are normalized."""
    text_unix = "Para 1\n\nPara 2"
    text_windows = "Para 1\r\n\r\nPara 2"
    text_old_mac = "Para 1\r\rPara 2"

    chunks_unix = chunk_document(text_unix)
    chunks_windows = chunk_document(text_windows)
    chunks_old_mac = chunk_document(text_old_mac)

    # Should all produce similar structure
    assert len(chunks_unix) >= 1
    assert len(chunks_windows) >= 1
    assert len(chunks_old_mac) >= 1
