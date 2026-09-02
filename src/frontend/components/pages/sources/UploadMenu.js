(function () {
  if (window.__circeusKbUpload) return;
  window.__circeusKbUpload = true;

  var MAX_ATTEMPTS = 3;
  var CACHE_PREFIX = 'menelao:source-upload:';

  function wait(milliseconds) {
    return new Promise(function (resolve) {
      window.setTimeout(resolve, milliseconds);
    });
  }

  function loadCache(form) {
    try {
      return JSON.parse(localStorage.getItem(CACHE_PREFIX + form.action)) || {};
    } catch (_) {
      return {};
    }
  }

  function saveCache(form, cache) {
    try {
      localStorage.setItem(CACHE_PREFIX + form.action, JSON.stringify(cache));
    } catch (_) {}
  }

  function fingerprint(file) {
    return [file.webkitRelativePath || file.name, file.size, file.lastModified].join('\u0000');
  }

  function prepareFiles(files, maxBytes, cache) {
    var ready = [];
    var cached = 0;
    var oversized = 0;
    files.forEach(function (file) {
      var key = fingerprint(file);
      var entry = cache[key];
      if (entry && entry.uploaded) {
        cached += 1;
        return;
      }
      if (file.size > maxBytes) {
        oversized += 1;
        return;
      }
      if (!entry || !entry.id) {
        entry = { id: crypto.randomUUID(), uploaded: false };
        cache[key] = entry;
      }
      ready.push({ file: file, id: entry.id, key: key });
    });
    return { files: ready, cached: cached, oversized: oversized };
  }

  function batches(files, maxFiles, maxBytes) {
    var result = [];
    var batch = [];
    var bytes = 0;
    files.forEach(function (item) {
      if (batch.length && (batch.length === maxFiles || bytes + item.file.size > maxBytes)) {
        result.push(batch);
        batch = [];
        bytes = 0;
      }
      batch.push(item);
      bytes += item.file.size;
    });
    if (batch.length) result.push(batch);
    return result;
  }

  function fileCount(count) {
    return count + ' file' + (count === 1 ? '' : 's');
  }

  function completionMessage(state) {
    var parts = ['Uploaded ' + fileCount(state.uploaded) + '.'];
    if (state.cached) parts.push('Skipped ' + fileCount(state.cached) + ' already uploaded.');
    if (state.oversized) parts.push('Skipped ' + fileCount(state.oversized) + ' over the size limit.');
    return parts.join(' ');
  }

  function setBusy(form, busy) {
    form.dataset.uploading = busy ? 'true' : 'false';
    form.querySelectorAll('[role="menuitem"]').forEach(function (item) {
      item.disabled = busy;
    });
  }

  function setStatus(form, message, retry) {
    var status = form.querySelector('[data-source-upload-status]');
    status.hidden = false;
    status.querySelector('[data-source-upload-message]').textContent = message;
    status.querySelector('[data-source-upload-retry]').hidden = !retry;
  }

  async function uploadBatch(form, files) {
    var lastError;
    for (var attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
      var data = new FormData();
      files.forEach(function (item) {
        data.append('files', item.file);
        data.append('file_ids', item.id);
      });
      var response;
      try {
        response = await fetch(form.action, {
          method: 'POST',
          body: data,
          credentials: 'same-origin',
        });
      } catch (error) {
        lastError = error;
      }
      if (response && response.ok) return;
      if (response && response.status !== 429 && response.status < 500) {
        var detail = '';
        try {
          var errorBody = await response.json();
          detail = errorBody.detail || '';
        } catch (_) {}
        throw new Error(detail || ('Upload rejected with status ' + response.status));
      }
      if (response) lastError = new Error('Upload failed with status ' + response.status);
      if (attempt + 1 < MAX_ATTEMPTS) await wait(500 * Math.pow(2, attempt));
    }
    throw lastError;
  }

  async function run(form) {
    var state = form._uploadState;
    setBusy(form, true);
    form.querySelector('[data-source-upload-retry]').hidden = true;
    while (state.index < state.batches.length) {
      var batch = state.batches[state.index];
      setStatus(
        form,
        'Uploading ' + (state.uploaded + 1) + '–' + (state.uploaded + batch.length) +
          ' of ' + state.total + ' files…',
        false
      );
      try {
        await uploadBatch(form, batch);
      } catch (error) {
        setBusy(form, false);
        setStatus(
          form,
          'Uploaded ' + state.uploaded + ' of ' + state.total +
            ' files. ' + error.message + '.',
          true
        );
        return;
      }
      batch.forEach(function (item) {
        state.cache[item.key].uploaded = true;
      });
      saveCache(form, state.cache);
      state.uploaded += batch.length;
      state.index += 1;
    }
    setBusy(form, false);
    setStatus(form, completionMessage(state), false);
    form.querySelector('[data-source-upload-input]').value = '';
    form._uploadState = null;
    htmx.trigger(document.body, 'source-files-refresh');
  }

  document.addEventListener('change', function (event) {
    var input = event.target.closest('[data-source-upload-input]');
    if (!input || !input.files.length) return;
    var form = input.closest('[data-source-upload-form]');
    var maxBytes = Number(form.dataset.maxBytes);
    var cache = loadCache(form);
    var prepared = prepareFiles(Array.from(input.files), maxBytes, cache);
    saveCache(form, cache);
    form._uploadState = {
      batches: batches(prepared.files, Number(form.dataset.maxFiles), maxBytes),
      cache: cache,
      cached: prepared.cached,
      oversized: prepared.oversized,
      index: 0,
      uploaded: 0,
      total: prepared.files.length,
    };
    var menu = form.querySelector('[data-menu]');
    if (menu && menu.matches(':popover-open')) menu.hidePopover();
    run(form);
  });

  document.addEventListener('click', function (event) {
    var retry = event.target.closest('[data-source-upload-retry]');
    if (!retry) return;
    var form = retry.closest('[data-source-upload-form]');
    if (form._uploadState && form.dataset.uploading !== 'true') run(form);
  });
})();
