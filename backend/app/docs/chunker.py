"""Document chunker - deterministic text splitting (PR-10A)."""


def chunk_document(
    text: str,
    *,
    max_chars: int = 800,
) -> list[tuple[int, str]]:
    """Chunk document text into ordered segments.

    Pure function with no I/O or randomness. Splits text into chunks
    that respect paragraph boundaries while staying under max_chars.

    Args:
        text: Raw document text to chunk
        max_chars: Maximum characters per chunk (default 800)

    Returns:
        List of (order, chunk_text) tuples where:
        - order is 0-based, strictly increasing
        - chunk_text is stripped, non-empty text
        - Concatenating all chunks reproduces original (modulo whitespace normalization)

    Strategy:
        1. Normalize line endings to \n
        2. Split on double newlines to get paragraphs
        3. Pack paragraphs into chunks ≤ max_chars
        4. If a single paragraph exceeds max_chars, split by sentences (naive)
        5. Never return empty chunks
        6. Deterministic: same input → same output
    """
    if not text or not text.strip():
        return []

    # Normalize line endings
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # Split into paragraphs (double newline)
    paragraphs = [p.strip() for p in normalized.split("\n\n") if p.strip()]

    if not paragraphs:
        return []

    chunks: list[tuple[int, str]] = []
    current_chunk_parts: list[str] = []
    current_length = 0

    def flush_chunk() -> None:
        """Flush current chunk to results."""
        if current_chunk_parts:
            chunk_text = "\n\n".join(current_chunk_parts)
            chunks.append((len(chunks), chunk_text))
            current_chunk_parts.clear()
            nonlocal current_length
            current_length = 0

    for para in paragraphs:
        para_len = len(para)

        # If paragraph alone exceeds max_chars, split it by sentences
        if para_len > max_chars:
            # Flush any pending chunk first
            flush_chunk()

            # Naive sentence split: split on ". " or ".\n" or "? " or "! "
            sentences = []
            current_sentence = []
            for char in para:
                current_sentence.append(char)
                if char in ".?!" and (
                    len(current_sentence) > 1
                    and (
                        "".join(current_sentence).endswith(". ")
                        or "".join(current_sentence).endswith(".\n")
                        or "".join(current_sentence).endswith("? ")
                        or "".join(current_sentence).endswith("! ")
                        or "".join(current_sentence).rstrip().endswith(".")
                    )
                ):
                    sentences.append("".join(current_sentence).strip())
                    current_sentence = []

            # Don't forget remaining text
            if current_sentence:
                sentences.append("".join(current_sentence).strip())

            # Pack sentences into chunks
            for sentence in sentences:
                if not sentence:
                    continue

                sentence_len = len(sentence)

                # If adding this sentence would exceed limit, flush
                if current_length > 0 and current_length + sentence_len + 1 > max_chars:
                    flush_chunk()

                # If single sentence exceeds limit, force it into its own chunk
                if sentence_len > max_chars:
                    flush_chunk()
                    chunks.append((len(chunks), sentence))
                else:
                    if current_chunk_parts:
                        current_length += 1  # Space between sentences
                    current_chunk_parts.append(sentence)
                    current_length += sentence_len

        else:
            # Normal paragraph fits or might fit with current chunk
            # Account for "\n\n" separator (2 chars) between paragraphs
            if current_chunk_parts:
                # Adding this para would need "\n\n" separator
                needed_len = current_length + 2 + para_len
            else:
                # First paragraph in chunk, no separator needed
                needed_len = para_len

            if needed_len > max_chars:
                # Would exceed limit, flush current chunk
                flush_chunk()
                current_chunk_parts.append(para)
                current_length = para_len
            else:
                # Fits in current chunk
                if current_chunk_parts:
                    current_length += 2  # Add separator length
                current_chunk_parts.append(para)
                current_length += para_len

    # Flush any remaining chunk
    flush_chunk()

    return chunks
