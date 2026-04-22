function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function initAuthTabs() {
  const tabs = Array.from(document.querySelectorAll(".auth-tab"));
  if (!tabs.length) {
    return;
  }

  const panels = {
    login: document.getElementById("loginPanel"),
    signup: document.getElementById("signupPanel"),
  };
  const initialMode = document.body.dataset.authMode === "signup" ? "signup" : "login";

  function setMode(mode) {
    tabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.authTarget === mode);
    });

    Object.entries(panels).forEach(([panelMode, panel]) => {
      if (!panel) {
        return;
      }
      panel.hidden = panelMode !== mode;
    });
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => setMode(tab.dataset.authTarget));
  });

  setMode(initialMode);
}

function initWorkspaceForm() {
  const form = document.getElementById("workspaceForm");
  if (!form) {
    return;
  }

  const input = document.getElementById("videoInput");
  const previewShell = document.getElementById("previewShell");
  const preview = document.getElementById("videoPreview");
  const videoName = document.getElementById("videoName");
  const durationInput = document.getElementById("durationInput");
  const durationUnit = document.getElementById("durationUnit");
  const submitButton = document.getElementById("generateButton");

  const progressCard = document.getElementById("progressCard");
  const progressLabel = document.getElementById("progressLabel");
  const progressPercent = document.getElementById("progressPercent");
  const progressFill = document.getElementById("progressFill");

  const resultEmpty = document.getElementById("resultEmpty");
  const resultShell = document.getElementById("resultShell");
  const resultVideo = document.getElementById("resultVideo");
  const resultTitle = document.getElementById("resultTitle");
  const resultDetails = document.getElementById("resultDetails");
  const resultDownload = document.getElementById("resultDownload");

  function setProgress(percent, message, state) {
    const safePercent = Math.max(0, Math.min(100, Math.round(percent || 0)));
    progressCard.dataset.state = state;
    progressLabel.textContent = message;
    progressPercent.textContent = `${safePercent}%`;
    progressFill.style.width = `${safePercent}%`;
  }

  function setBusy(isBusy) {
    submitButton.disabled = isBusy;
    durationInput.disabled = isBusy;
    durationUnit.disabled = isBusy;
    input.disabled = isBusy;
  }

  function showPreview(file) {
    if (!file) {
      previewShell.hidden = true;
      preview.removeAttribute("src");
      videoName.textContent = "Selected video";
      return;
    }

    preview.src = URL.createObjectURL(file);
    previewShell.hidden = false;
    videoName.textContent = file.name;
  }

  function renderClip(clip) {
    resultVideo.src = clip.video_url;
    resultVideo.load();
    resultTitle.textContent = clip.source_name;
    resultDetails.textContent = `${clip.duration_label} · ${clip.created_label}`;
    resultDownload.href = clip.download_url;
    resultDownload.classList.remove("is-hidden");
    resultEmpty.hidden = true;
    resultShell.hidden = false;
  }

  async function pollJob(jobId) {
    while (true) {
      const response = await fetch(`/api/jobs/${jobId}`);
      let data = null;

      try {
        data = await response.json();
      } catch (error) {
        throw new Error("Could not read the job status from the server.");
      }

      if (!response.ok || !data.ok) {
        if (response.status === 401) {
          window.location.href = "/auth?mode=login";
          return;
        }
        throw new Error(data.error || "Could not fetch job status.");
      }

      const { job } = data;
      const state = job.status === "failed" ? "error" : job.status === "completed" ? "success" : "working";
      setProgress(job.progress, job.message, state);

      if (job.status === "completed") {
        renderClip(job.clip);
        return;
      }

      if (job.status === "failed") {
        throw new Error(job.error || job.message || "Summary generation failed.");
      }

      await sleep(1000);
    }
  }

  input.addEventListener("change", () => {
    const file = input.files[0];
    showPreview(file);
    if (file) {
      setProgress(0, "Video loaded. Generate the summary when you are ready.", "idle");
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const file = input.files[0];
    if (!file) {
      setProgress(0, "Choose a source video before generating the summary.", "error");
      return;
    }

    const rawDuration = Number(durationInput.value || "0");
    if (!Number.isFinite(rawDuration) || rawDuration <= 0) {
      setProgress(0, "Enter a valid summary length.", "error");
      return;
    }

    const durationSeconds = durationUnit.value === "minutes"
      ? Math.round(rawDuration * 60)
      : Math.round(rawDuration);

    const payload = new FormData();
    payload.append("video", file);
    payload.append("duration", String(durationSeconds));

    setBusy(true);
    setProgress(2, "Uploading the source video.", "working");

    try {
      const response = await fetch("/api/process", {
        method: "POST",
        body: payload,
      });

      let data = null;
      try {
        data = await response.json();
      } catch (error) {
        throw new Error("The server returned an unreadable response.");
      }

      if (!response.ok || !data.ok) {
        if (response.status === 401) {
          window.location.href = "/auth?mode=login";
          return;
        }
        throw new Error(data.error || "Could not start the summary job.");
      }

      resultShell.hidden = true;
      resultEmpty.hidden = false;
      await pollJob(data.job_id);
    } catch (error) {
      setProgress(0, error.message, "error");
    } finally {
      setBusy(false);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initAuthTabs();
  initWorkspaceForm();
});
