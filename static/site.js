/* ================================================================
   Sliver — SaaS Application Logic (site.js)
   ================================================================ */

'use strict';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/* ---- Auth Segmented Switcher ---- */
function initAuthTabs() {
  const tabs = Array.from(document.querySelectorAll('.segment-btn'));
  if (!tabs.length) return;

  const panels = {
    login: document.getElementById('loginPanel'),
    signup: document.getElementById('signupPanel'),
  };

  const initialMode =
    document.body.dataset.authMode === 'signup' ? 'signup' : 'login';

  function setMode(mode) {
    tabs.forEach((tab) => {
      const isActive = tab.dataset.authTarget === mode;
      tab.classList.toggle('active', isActive);
      tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    Object.entries(panels).forEach(([m, panel]) => {
      if (!panel) return;
      panel.hidden = m !== mode;
    });
  }

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => setMode(tab.dataset.authTarget));
  });

  setMode(initialMode);
}

/* ---- Workspace Video Upload & Controls ---- */
function initWorkspaceForm() {
  const form = document.getElementById('workspaceForm');
  if (!form) return;

  const videoInput          = document.getElementById('videoInput');
  const dropzoneLabel       = document.getElementById('dropzoneLabel');
  const previewShell        = document.getElementById('previewShell');
  const videoPreview        = document.getElementById('videoPreview');
  const videoName           = document.getElementById('videoName');
  const removeVideoBtn      = document.getElementById('removeVideoBtn');

  const durationInput       = document.getElementById('durationInput');
  const durationSlider      = document.getElementById('durationSlider');
  const durationDisplayPill = document.getElementById('durationDisplayPill');
  const presetBtns          = Array.from(document.querySelectorAll('.preset-btn'));

  const promptInput         = document.getElementById('promptInput');
  const promptTags          = Array.from(document.querySelectorAll('.prompt-tag'));

  const generateButton      = document.getElementById('generateButton');
  const progressCard        = document.getElementById('progressCard');
  const progressLabel       = document.getElementById('progressLabel');
  const progressPercent     = document.getElementById('progressPercent');
  const progressFill        = document.getElementById('progressFill');

  const stages = [
    document.getElementById('stage1'),
    document.getElementById('stage2'),
    document.getElementById('stage3'),
    document.getElementById('stage4'),
    document.getElementById('stage5'),
  ].filter(Boolean);

  const resultEmpty         = document.getElementById('resultEmpty');
  const resultShell         = document.getElementById('resultShell');
  const resultVideo         = document.getElementById('resultVideo');
  const resultTitle         = document.getElementById('resultTitle');
  const resultDetails       = document.getElementById('resultDetails');
  const resultDownload      = document.getElementById('resultDownload');

  /* ---- Sync Duration Settings ---- */
  function updateDuration(val) {
    const num = Math.max(1, Math.min(1800, Math.round(Number(val) || 30)));
    if (durationInput) durationInput.value = num;
    if (durationSlider) durationSlider.value = Math.min(300, num);
    if (durationDisplayPill) {
      durationDisplayPill.textContent = num < 60 ? `${num}s` : `${Math.floor(num / 60)}m ${num % 60 ? (num % 60) + 's' : ''}`.trim();
    }

    presetBtns.forEach((btn) => {
      btn.classList.toggle('active', Number(btn.dataset.duration) === num);
    });
  }

  presetBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const dur = Number(btn.dataset.duration);
      if (dur) updateDuration(dur);
    });
  });

  if (durationSlider) {
    durationSlider.addEventListener('input', (e) => {
      updateDuration(e.target.value);
    });
  }

  if (durationInput) {
    durationInput.addEventListener('input', (e) => {
      updateDuration(e.target.value);
    });
  }

  /* ---- Prompt Suggestions ---- */
  promptTags.forEach((tag) => {
    tag.addEventListener('click', () => {
      if (!promptInput) return;
      promptInput.value = tag.dataset.prompt;
      promptInput.focus();
    });
  });

  /* ---- Preview & Video Selection ---- */
  function showPreview(file) {
    if (!file) {
      if (previewShell) previewShell.hidden = true;
      if (dropzoneLabel) dropzoneLabel.hidden = false;
      if (videoPreview) videoPreview.removeAttribute('src');
      if (videoName) videoName.textContent = 'Selected video';
      return;
    }

    try {
      if (videoPreview) {
        videoPreview.src = URL.createObjectURL(file);
      }
      if (videoName) videoName.textContent = file.name;
      if (dropzoneLabel) dropzoneLabel.hidden = true;
      if (previewShell) previewShell.hidden = false;
    } catch {
      // Fallback
    }
  }

  if (removeVideoBtn) {
    removeVideoBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (videoInput) videoInput.value = '';
      showPreview(null);
      setProgress(0, 'Choose a source video to begin.', 'idle');
    });
  }

  /* ---- Drag and Drop Handling ---- */
  if (dropzoneLabel) {
    ['dragenter', 'dragover'].forEach((evt) => {
      dropzoneLabel.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzoneLabel.classList.add('drag-active');
      });
    });

    ['dragleave', 'drop'].forEach((evt) => {
      dropzoneLabel.addEventListener(evt, () => {
        dropzoneLabel.classList.remove('drag-active');
      });
    });

    dropzoneLabel.addEventListener('drop', (e) => {
      e.preventDefault();
      const file = e.dataTransfer?.files?.[0];
      if (file && file.type.startsWith('video/')) {
        const dt = new DataTransfer();
        dt.items.add(file);
        if (videoInput) videoInput.files = dt.files;
        showPreview(file);
        setProgress(0, 'Video selected. Ready to generate summary.', 'idle');
      }
    });
  }

  if (videoInput) {
    videoInput.addEventListener('change', () => {
      const file = videoInput.files[0];
      showPreview(file);
      if (file) {
        setProgress(0, 'Video selected. Ready to generate summary.', 'idle');
      }
    });
  }

  /* ---- Pipeline Stages Tracker ---- */
  function updateStages(pct, state) {
    if (!stages.length) return;

    if (state === 'idle') {
      stages.forEach((s) => (s.dataset.stepState = 'idle'));
      return;
    }

    if (state === 'error') {
      stages.forEach((s) => {
        if (s.dataset.stepState === 'active') s.dataset.stepState = 'error';
      });
      return;
    }

    if (state === 'success' || pct >= 100) {
      stages.forEach((s) => (s.dataset.stepState = 'done'));
      return;
    }

    let activeIdx = 0;
    if (pct >= 85) activeIdx = 4;
    else if (pct >= 65) activeIdx = 3;
    else if (pct >= 40) activeIdx = 2;
    else if (pct >= 18) activeIdx = 1;
    else activeIdx = 0;

    stages.forEach((step, idx) => {
      if (idx < activeIdx) {
        step.dataset.stepState = 'done';
      } else if (idx === activeIdx) {
        step.dataset.stepState = 'active';
      } else {
        step.dataset.stepState = 'idle';
      }
    });
  }

  function setProgress(percent, message, state) {
    const pct = Math.max(0, Math.min(100, Math.round(percent || 0)));
    if (progressCard) progressCard.dataset.state = state;
    if (progressLabel) progressLabel.textContent = message;
    if (progressPercent) progressPercent.textContent = `${pct}%`;
    if (progressFill) progressFill.style.width = `${pct}%`;
    updateStages(pct, state);
  }

  function setBusy(on) {
    if (generateButton) {
      generateButton.disabled = on;
      const label = generateButton.querySelector('.btn-label');
      if (on) {
        generateButton.classList.add('loading');
        if (label) label.textContent = 'Processing video…';
      } else {
        generateButton.classList.remove('loading');
        if (label) label.textContent = 'Generate summary';
      }
    }
    if (durationInput) durationInput.disabled = on;
    if (durationSlider) durationSlider.disabled = on;
    if (promptInput) promptInput.disabled = on;
    if (videoInput) videoInput.disabled = on;
  }

  function renderClip(clip) {
    if (!clip) return;
    if (resultVideo) {
      resultVideo.src = clip.video_url;
      resultVideo.load();
    }
    if (resultTitle) resultTitle.textContent = clip.source_name;
    if (resultDetails) resultDetails.textContent = `${clip.duration_label} · ${clip.created_label}`;
    if (resultDownload) {
      resultDownload.href = clip.download_url;
      resultDownload.setAttribute('download', clip.source_name || 'summary.mp4');
    }
    if (resultEmpty) resultEmpty.hidden = true;
    if (resultShell) resultShell.hidden = false;
  }

  /* ---- Job Status Polling ---- */
  async function pollJob(jobId) {
    while (true) {
      const res = await fetch(`/api/jobs/${jobId}`);
      let data = null;

      try {
        data = await res.json();
      } catch {
        throw new Error('Could not parse server response.');
      }

      if (!res.ok || !data.ok) {
        if (res.status === 401) {
          window.location.href = '/auth?mode=login';
          return;
        }
        throw new Error(data.error || 'Failed to retrieve job status.');
      }

      const { job } = data;
      const state =
        job.status === 'failed'    ? 'error'   :
        job.status === 'completed' ? 'success' : 'working';

      setProgress(job.progress, job.message, state);

      if (job.status === 'completed') {
        renderClip(job.clip);
        return;
      }
      if (job.status === 'failed') {
        throw new Error(job.error || job.message || 'Video processing failed.');
      }

      await sleep(1000);
    }
  }

  /* ---- Form Submit Handler ---- */
  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const file = videoInput?.files?.[0];
    if (!file) {
      setProgress(0, 'Please select a source video file to begin.', 'error');
      return;
    }

    const rawDuration = Number(durationInput?.value || '30');
    if (!Number.isFinite(rawDuration) || rawDuration <= 0) {
      setProgress(0, 'Please enter a valid duration in seconds.', 'error');
      return;
    }

    const durationSeconds = Math.round(rawDuration);
    const promptValue = promptInput ? promptInput.value.trim() : '';

    const payload = new FormData();
    payload.append('video', file);
    payload.append('duration', String(durationSeconds));
    if (promptValue) payload.append('prompt', promptValue);

    setBusy(true);
    setProgress(2, 'Uploading video to local workspace…', 'working');

    try {
      const res = await fetch('/api/process', { method: 'POST', body: payload });
      let data = null;

      try {
        data = await res.json();
      } catch {
        throw new Error('Server returned an invalid response.');
      }

      if (!res.ok || !data.ok) {
        if (res.status === 401) {
          window.location.href = '/auth?mode=login';
          return;
        }
        throw new Error(data.error || 'Failed to start processing job.');
      }

      if (resultShell) resultShell.hidden = true;
      if (resultEmpty) resultEmpty.hidden = false;

      await pollJob(data.job_id);
    } catch (err) {
      setProgress(0, err.message, 'error');
    } finally {
      setBusy(false);
    }
  });

  if (durationInput) {
    updateDuration(durationInput.value || 30);
  }
}

/* ---- Initialize on DOM Load ---- */
document.addEventListener('DOMContentLoaded', () => {
  initAuthTabs();
  initWorkspaceForm();
});
