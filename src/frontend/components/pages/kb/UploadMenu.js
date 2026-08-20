(function () {
  if (window.__circeusKbUpload) return;
  window.__circeusKbUpload = true;

  var MAX_ATTEMPTS = 3;

  function wait(milliseconds) {
    return new Promise(function (resolve) {
      window.setTimeout(resolve, milliseconds);
    });
  }

  function batches(files, maxFiles, maxBytes) {
    var result = [];
    var batch = [];
    var bytes = 0;
    files.forEach(function (file) {
      if (batch.length && (batch.length === maxFiles || bytes + file.size > maxBytes)) {
        result.push(batch);
        batch = [];
        bytes = 0;
      }
      batch.push({ file: file, id: crypto.randomUUID() });
      bytes += file.size;
    });
    if (batch.length) result.push(batch);
    return result;
  }

  function setBusy(form, busy) {
    form.dataset.uploading = busy ? 'true' : 'false';
    form.querySelectorAll('[role="menuitem"]').forEach(function (item) {
      item.disabled = busy;
    });
  }

  function setStatus(form, message, retry) {
    var status = form.querySelector('[data-kb-upload-status]');
    status.hidden = false;
    status.querySelector('[data-kb-upload-message]').textContent = message;
    status.querySelector('[data-kb-upload-retry]').hidden = !retry;
  }

  async function uploadBatch(form, files) {
    var lastError;
    for (var attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
      var body = new FormData();
      files.forEach(function (item) {
        body.append('files', item.file);
        body.append('file_ids', item.id);
      });
      var response;
      try {
        response = await fetch(form.action, { method: 'POST', body: body });
      } catch (error) {
        lastError = error;
      }
      if (response && response.ok) return;
      if (response && response.status !== 429 && response.status < 500) {
        throw new Error('Upload rejected with status ' + response.status);
      }
      if (response) lastError = new Error('Upload failed with status ' + response.status);
      if (attempt + 1 < MAX_ATTEMPTS) await wait(500 * Math.pow(2, attempt));
    }
    throw lastError;
  }

  async function run(form) {
    var state = form._uploadState;
    setBusy(form, true);
    form.querySelector('[data-kb-upload-retry]').hidden = true;
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
      state.uploaded += batch.length;
      state.index += 1;
    }
    setBusy(form, false);
    setStatus(form, 'Uploaded ' + state.total + ' files.', false);
    form.querySelector('[data-kb-upload-input]').value = '';
    form._uploadState = null;
    htmx.trigger(document.body, 'kb-files-refresh');
  }

  document.addEventListener('change', function (event) {
    var input = event.target.closest('[data-kb-upload-input]');
    if (!input || !input.files.length) return;
    var form = input.closest('[data-kb-upload-form]');
    var files = Array.from(input.files);
    form._uploadState = {
      batches: batches(files, Number(form.dataset.maxFiles), Number(form.dataset.maxBytes)),
      index: 0,
      uploaded: 0,
      total: files.length
    };
    var menu = form.querySelector('[data-menu]');
    if (menu && menu.matches(':popover-open')) menu.hidePopover();
    run(form);
  });

  document.addEventListener('click', function (event) {
    var retry = event.target.closest('[data-kb-upload-retry]');
    if (!retry) return;
    var form = retry.closest('[data-kb-upload-form]');
    if (form._uploadState && form.dataset.uploading !== 'true') run(form);
  });
})();
