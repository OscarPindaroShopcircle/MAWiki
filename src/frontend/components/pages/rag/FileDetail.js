(function () {
  function chunkRanges(documentElement) {
    return Array.from(documentElement.querySelectorAll("[data-rag-chunk]"))
      .map(function (element) {
        return {
          start: Number(element.dataset.start),
          end: Number(element.dataset.end),
          color: Number(element.dataset.color),
          label: element.dataset.label
        };
      })
      .filter(function (range) {
        return Number.isFinite(range.start) && range.start >= 0 && range.end > range.start;
      })
      .sort(function (left, right) { return left.start - right.start; });
  }

  function toCodeUnitRanges(sourceText, ranges) {
    var boundaries = Array.from(new Set(ranges.flatMap(function (range) {
      return [range.start, range.end];
    }))).sort(function (left, right) { return left - right; });
    var offsets = new Map();
    var boundaryIndex = 0;
    var codePoint = 0;
    var codeUnit = 0;

    for (var character of sourceText) {
      while (boundaries[boundaryIndex] <= codePoint) {
        offsets.set(boundaries[boundaryIndex], codeUnit);
        boundaryIndex += 1;
      }
      codePoint += 1;
      codeUnit += character.length;
    }
    while (boundaryIndex < boundaries.length) {
      offsets.set(boundaries[boundaryIndex], sourceText.length);
      boundaryIndex += 1;
    }

    return ranges.map(function (range) {
      var start = offsets.get(range.start);
      var end = offsets.get(range.end);
      return Object.assign({}, range, {
        sourceStart: range.start,
        sourceEnd: range.end,
        start: start,
        end: end,
        startsAtLineEdge: start === 0 || sourceText[start - 1] === "\n",
        endsAtLineEdge: end === sourceText.length || sourceText[end] === "\n" || sourceText[end - 1] === "\n"
      });
    });
  }

  function paintTextNode(node, sourceStart, ranges) {
    var text = node.nodeValue;
    var sourceEnd = sourceStart + text.length;
    var boundaries = [0, text.length];

    ranges.forEach(function (range) {
      if (range.start > sourceStart && range.start < sourceEnd) boundaries.push(range.start - sourceStart);
      if (range.end > sourceStart && range.end < sourceEnd) boundaries.push(range.end - sourceStart);
    });
    boundaries.sort(function (left, right) { return left - right; });

    var fragment = document.createDocumentFragment();
    boundaries.forEach(function (boundary, index) {
      if (index === boundaries.length - 1 || boundary === boundaries[index + 1]) return;
      var next = boundaries[index + 1];
      var range = ranges.find(function (candidate) {
        return candidate.start < sourceStart + next && candidate.end > sourceStart + boundary;
      });
      var content = text.slice(boundary, next);
      if (!range) {
        fragment.appendChild(document.createTextNode(content));
        return;
      }
      var span = document.createElement("span");
      span.className = "rag-chunk-highlight";
      span.dataset.chunkColor = String(range.color);
      span.dataset.chunkKey = range.sourceStart + ":" + range.sourceEnd;
      span.dataset.chunkLineStart = String(range.startsAtLineEdge);
      span.dataset.chunkLineEnd = String(range.endsAtLineEdge);
      span.title = range.label + ": characters " + range.sourceStart + "–" + range.sourceEnd;
      span.textContent = content;
      fragment.appendChild(span);
    });
    node.replaceWith(fragment);
  }

  function paintRendered(rendered, sourceText, ranges) {
    var walker = document.createTreeWalker(rendered, NodeFilter.SHOW_TEXT);
    var nodes = [];
    var node;
    while ((node = walker.nextNode())) nodes.push(node);

    var cursor = 0;
    nodes.forEach(function (textNode) {
      var value = textNode.nodeValue;
      if (!value) return;
      var start = sourceText.indexOf(value, cursor);
      if (start === -1) return;
      paintTextNode(textNode, start, ranges);
      cursor = start + value.length;
    });
  }

  function paintChunkBands(view) {
    if (view.hidden) return;
    var previous = view.querySelector(":scope > .rag-chunk-bands");
    if (previous) previous.remove();

    var viewRect = view.getBoundingClientRect();
    var fragments = [];
    view.querySelectorAll(".rag-chunk-highlight").forEach(function (span) {
      if (!span.textContent.trim()) return;
      var lineHeight = parseFloat(getComputedStyle(span).lineHeight);
      Array.from(span.getClientRects()).forEach(function (rect) {
        if (!rect.width || !rect.height) return;
        var padding = Number.isFinite(lineHeight) ? Math.max(0, lineHeight - rect.height) / 2 : 0;
        fragments.push({
          key: span.dataset.chunkKey,
          color: span.dataset.chunkColor,
          startsAtLineEdge: span.dataset.chunkLineStart === "true",
          endsAtLineEdge: span.dataset.chunkLineEnd === "true",
          rawTop: rect.top,
          rawBottom: rect.bottom,
          top: rect.top - viewRect.top + view.scrollTop - padding,
          bottom: rect.bottom - viewRect.top + view.scrollTop + padding,
          left: rect.left - viewRect.left + view.scrollLeft,
          right: rect.right - viewRect.left + view.scrollLeft
        });
      });
    });
    fragments.sort(function (left, right) { return left.rawTop - right.rawTop || left.left - right.left; });

    var rows = [];
    fragments.forEach(function (fragment) {
      var row = rows[rows.length - 1];
      var overlap = row
        ? Math.min(row.rawBottom, fragment.rawBottom) - Math.max(row.rawTop, fragment.rawTop)
        : 0;
      var sameRow = row && overlap >= Math.min(
        row.rawBottom - row.rawTop,
        fragment.rawBottom - fragment.rawTop
      ) / 2;
      if (!sameRow) {
        row = {
          rawTop: fragment.rawTop,
          rawBottom: fragment.rawBottom,
          top: fragment.top,
          bottom: fragment.bottom
        };
        rows.push(row);
      } else {
        row.rawTop = Math.min(row.rawTop, fragment.rawTop);
        row.rawBottom = Math.max(row.rawBottom, fragment.rawBottom);
        row.top = Math.min(row.top, fragment.top);
        row.bottom = Math.max(row.bottom, fragment.bottom);
      }
      fragment.row = row;
    });
    rows.forEach(function (row, index) {
      row.index = index;
      if (index === 0) row.edgeTop = row.top;
      if (index > 0) {
        var previousRow = rows[index - 1];
        var boundary = (previousRow.bottom + row.top) / 2;
        previousRow.edgeBottom = boundary;
        row.edgeTop = boundary;
      }
      if (index === rows.length - 1) row.edgeBottom = row.bottom;
    });

    var groups = new Map();
    fragments.forEach(function (fragment) {
      var group = groups.get(fragment.key) || {
        color: fragment.color,
        startsAtLineEdge: fragment.startsAtLineEdge,
        endsAtLineEdge: fragment.endsAtLineEdge,
        lines: []
      };
      var line = group.lines.find(function (candidate) { return candidate.row === fragment.row; });
      if (line) {
        line.left = Math.min(line.left, fragment.left);
        line.right = Math.max(line.right, fragment.right);
      } else {
        group.lines.push({
          row: fragment.row,
          top: fragment.row.edgeTop,
          bottom: fragment.row.edgeBottom,
          left: fragment.left,
          right: fragment.right
        });
      }
      groups.set(fragment.key, group);
    });

    var layer = document.createElement("span");
    layer.className = "rag-chunk-bands";
    layer.setAttribute("aria-hidden", "true");

    function addBand(color, left, right, top, bottom) {
      if (right <= left || bottom <= top) return;
      var band = document.createElement("span");
      band.className = "rag-chunk-band";
      band.dataset.chunkColor = color;
      band.style.top = top + "px";
      band.style.left = left + "px";
      band.style.width = right - left + "px";
      band.style.height = bottom - top + "px";
      layer.appendChild(band);
    }

    groups.forEach(function (group) {
      group.lines.sort(function (left, right) { return left.top - right.top || left.left - right.left; });
      var first = group.lines[0];
      var last = group.lines[group.lines.length - 1];
      var firstLeft = group.startsAtLineEdge ? 0 : first.left;
      var lastRight = group.endsAtLineEdge ? view.clientWidth : last.right;
      if (first === last) {
        addBand(group.color, firstLeft, lastRight, first.top, first.bottom);
        return;
      }
      addBand(group.color, firstLeft, view.clientWidth, first.top, group.lines[1].top);
      if (group.lines.length > 2) {
        addBand(group.color, 0, view.clientWidth, group.lines[1].top, last.top);
      }
      addBand(group.color, 0, lastRight, last.top, last.bottom);
    });
    view.prepend(layer);
  }

  function paintVisibleBands(root) {
    root.querySelectorAll("[data-rag-rendered]:not([hidden]), [data-rag-source]:not([hidden])")
      .forEach(paintChunkBands);
  }

  function initialize(root) {
    root.querySelectorAll("[data-rag-document]:not([data-rag-ready])").forEach(function (documentElement) {
      var source = documentElement.querySelector("[data-rag-source]");
      var rendered = documentElement.querySelector("[data-rag-rendered]");
      var sourceText = source.textContent;
      var ranges = toCodeUnitRanges(sourceText, chunkRanges(documentElement));
      documentElement.dataset.ragReady = "true";
      if (!ranges.length) return;
      paintRendered(rendered, sourceText, ranges);
      if (source.firstChild) paintTextNode(source.firstChild, 0, ranges);
      paintChunkBands(rendered);
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-rag-mode]");
    if (!button) return;
    var documentElement = button.closest("[data-rag-document]");
    var mode = button.dataset.ragMode;
    documentElement.querySelector("[data-rag-rendered]").hidden = mode !== "rendered";
    documentElement.querySelector("[data-rag-source]").hidden = mode !== "source";
    documentElement.querySelectorAll("[data-rag-mode]").forEach(function (candidate) {
      candidate.setAttribute("aria-pressed", String(candidate === button));
    });
    requestAnimationFrame(function () { paintVisibleBands(documentElement); });
  });

  var resizeFrame;
  window.addEventListener("resize", function () {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(function () { paintVisibleBands(document); });
  });

  if (document.fonts) {
    document.fonts.ready.then(function () { paintVisibleBands(document); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { initialize(document); });
  } else {
    initialize(document);
  }
})();
