export function buildPieces(text, segments) {

  const ordered = [...segments].sort((a, b) => a.start_char - b.start_char);

  const pieces = [];

  let cursor = 0;



  for (const segment of ordered) {

    if (segment.start_char > cursor) {

      pieces.push({

        type: "gap",

        text: text.slice(cursor, segment.start_char),

      });

    }

    pieces.push({

      type: "segment",

      text: text.slice(segment.start_char, segment.end_char),

      segmentId: segment.id,

      startChar: segment.start_char,

      endChar: segment.end_char,

    });

    cursor = segment.end_char;

  }



  if (cursor < text.length) {

    pieces.push({

      type: "gap",

      text: text.slice(cursor),

    });

  }



  if (import.meta.env.DEV) {

    const joined = pieces.map((piece) => piece.text).join("");

    console.assert(joined === text, "Student response text must round-trip exactly");

  }



  return pieces;

}



function offsetWithinContainer(container, node, offset) {

  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);

  let total = 0;

  let current = walker.nextNode();

  while (current) {

    if (current === node) {

      return total + offset;

    }

    total += current.textContent.length;

    current = walker.nextNode();

  }

  return null;

}



export function selectionToOffsets(container, selection, text) {

  if (!container || !selection || selection.isCollapsed || selection.rangeCount === 0) {

    return null;

  }



  const range = selection.getRangeAt(0);

  if (!container.contains(range.commonAncestorContainer)) {

    return null;

  }



  const start = offsetWithinContainer(container, range.startContainer, range.startOffset);

  const end = offsetWithinContainer(container, range.endContainer, range.endOffset);

  if (start === null || end === null || start >= end) {

    return null;

  }



  const selectedText = text.slice(start, end);

  if (selectedText !== range.toString()) {

    return null;

  }



  return {

    start_char: start,

    end_char: end,

    text: selectedText,

  };

}



function collectBoundaries(textLength, spans, draft) {

  const points = new Set([0, textLength]);

  for (const span of spans) {

    points.add(span.start_char);

    points.add(span.end_char);

  }

  if (draft) {

    points.add(draft.start_char);

    points.add(draft.end_char);

  }

  return [...points].sort((a, b) => a - b);

}



function codingIdsForRange(start, end, codings) {

  return codings

    .filter((coding) => coding.start_char < end && coding.end_char > start)

    .map((coding) => coding.id);

}



export function buildHighlightPieces(
  text,
  spans,
  codings,
  draft,
  focusedCodingId,
  pendingCriterionId = null
) {
  const boundaries = collectBoundaries(text.length, spans, draft);
  const pieces = [];

  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const start = boundaries[index];
    const end = boundaries[index + 1];
    if (start === end) continue;

    const pieceText = text.slice(start, end);
    const codingIds = codingIdsForRange(start, end, codings);
    const isDraft =
      draft !== null && draft.start_char <= start && draft.end_char >= end && draft.end_char > start;
    const isDraftPending =
      isDraft && pendingCriterionId !== null && focusedCodingId === null;

    pieces.push({
      text: pieceText,
      start_char: start,
      end_char: end,
      codingIds,
      isDraft,
      isDraftPending,
      isFocused:
        (focusedCodingId !== null && codingIds.includes(focusedCodingId)) ||
        (isDraft && pendingCriterionId !== null),
    });
  }



  if (import.meta.env.DEV) {

    const joined = pieces.map((piece) => piece.text).join("");

    console.assert(joined === text, "Highlighted response text must round-trip exactly");

  }



  return pieces;

}



export function snippet(text, maxLength = 48) {

  if (text.length <= maxLength) return text;

  return `${text.slice(0, maxLength - 1)}…`;

}


