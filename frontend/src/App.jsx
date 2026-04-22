import { useEffect, useState } from "react";

const OS_OPTIONS = [
  { label: "Linux", value: "linux" },
  { label: "Windows", value: "windows" }
];
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

function buildApiUrl(path) {
  return API_BASE_URL ? `${API_BASE_URL}${path}` : path;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function App() {
  const [osType, setOsType] = useState("linux");
  const [controlsCount, setControlsCount] = useState(0);
  const [controlsLoading, setControlsLoading] = useState(true);
  const [controlsError, setControlsError] = useState("");

  const [uploadFile, setUploadFile] = useState(null);
  const [ingestLoading, setIngestLoading] = useState(false);
  const [ingestMessage, setIngestMessage] = useState("");
  const [ingestError, setIngestError] = useState("");

  const [query, setQuery] = useState("");
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryResult, setQueryResult] = useState("");
  const [queryError, setQueryError] = useState("");

  const [scriptLoading, setScriptLoading] = useState(false);
  const [scriptResult, setScriptResult] = useState("");
  const [scriptFilename, setScriptFilename] = useState("");
  const [scriptError, setScriptError] = useState("");
  const [scriptProgress, setScriptProgress] = useState("");
  const [scriptProcessedControls, setScriptProcessedControls] = useState(0);
  const [scriptTotalControls, setScriptTotalControls] = useState(0);

  useEffect(() => {
    let isActive = true;

    async function loadControls() {
      setControlsLoading(true);
      setControlsError("");

      try {
        const response = await fetch(buildApiUrl(`/api/controls?os_type=${osType}`));
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.error || "Failed to load controls.");
        }

        if (isActive) {
          setControlsCount(data.count || 0);
        }
      } catch (error) {
        if (isActive) {
          setControlsCount(0);
          setControlsError(error.message);
        }
      } finally {
        if (isActive) {
          setControlsLoading(false);
        }
      }
    }

    loadControls();

    return () => {
      isActive = false;
    };
  }, [osType]);

  async function handleIngest(event) {
    event.preventDefault();
    setIngestMessage("");
    setIngestError("");

    if (!uploadFile) {
      setIngestError("Choose a CIS benchmark PDF first.");
      return;
    }

    const formData = new FormData();
    formData.append("file", uploadFile);
    formData.append("os_type", osType);

    setIngestLoading(true);
    try {
      const response = await fetch(buildApiUrl("/api/ingest"), {
        method: "POST",
        body: formData
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Unable to ingest document.");
      }

      setIngestMessage(data.message);
      setUploadFile(null);
      await refreshControls();
    } catch (error) {
      setIngestError(error.message);
    } finally {
      setIngestLoading(false);
    }
  }

  async function refreshControls() {
    setControlsLoading(true);
    setControlsError("");

    try {
      const response = await fetch(buildApiUrl(`/api/controls?os_type=${osType}`));
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to refresh controls.");
      }

      setControlsCount(data.count || 0);
    } catch (error) {
      setControlsCount(0);
      setControlsError(error.message);
    } finally {
      setControlsLoading(false);
    }
  }

  async function handleQuery(event) {
    event.preventDefault();
    setQueryError("");
    setQueryResult("");

    if (!query.trim()) {
      setQueryError("Enter one or more CIS controls to generate a script snippet.");
      return;
    }

    setQueryLoading(true);
    try {
      const response = await fetch(buildApiUrl("/api/query"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          query,
          os_type: osType
        })
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Unable to generate snippet.");
      }

      setQueryResult(data.result || "");
    } catch (error) {
      setQueryError(error.message);
    } finally {
      setQueryLoading(false);
    }
  }

  async function handleBuildScript() {
    setScriptError("");
    setScriptResult("");
    setScriptFilename("");
    setScriptProgress("Queued master script build...");
    setScriptProcessedControls(0);
    setScriptTotalControls(0);

    setScriptLoading(true);
    try {
      const response = await fetch(buildApiUrl("/api/master-script"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          os_type: osType
        })
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Unable to build master script.");
      }

      const { job_id: jobId } = data;

      if (!jobId) {
        throw new Error("Master script job did not return a job id.");
      }

      while (true) {
        await sleep(1000);

        const statusResponse = await fetch(buildApiUrl(`/api/master-script/${jobId}`));
        const statusData = await statusResponse.json();

        if (!statusResponse.ok) {
          throw new Error(statusData.error || "Unable to fetch master script progress.");
        }

        setScriptProgress(statusData.progress_message || "");
        setScriptProcessedControls(statusData.processed_controls || 0);
        setScriptTotalControls(statusData.total_controls || 0);

        if (statusData.status === "completed") {
          setScriptResult(statusData.script || "");
          setScriptFilename(statusData.filename || "");
          setScriptProgress(statusData.progress_message || "Master script completed.");
          break;
        }

        if (statusData.status === "failed") {
          throw new Error(statusData.error || "Unable to build master script.");
        }
      }
    } catch (error) {
      setScriptError(error.message);
      setScriptProgress("");
    } finally {
      setScriptLoading(false);
    }
  }

  function downloadScript() {
    if (!scriptResult || !scriptFilename) {
      return;
    }

    const blob = new Blob([scriptResult], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = scriptFilename;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="app-shell">
      <div className="hero-glow hero-glow-left" />
      <div className="hero-glow hero-glow-right" />

      <main className="layout">
        <section className="hero">
          <p className="eyebrow">AWS Bedrock + ChromaDB</p>
          <h1>CIS Hardening Script Generator</h1>
          <p className="hero-copy">
            Train your vector store on benchmark PDFs, generate script snippets for
            specific controls, and assemble a full hardening script from the indexed
            CIS content.
          </p>

          <div className="os-switch" role="tablist" aria-label="Target operating system">
            {OS_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={option.value === osType ? "os-pill active" : "os-pill"}
                onClick={() => setOsType(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="summary-card">
            <span className="summary-label">Indexed controls</span>
            <strong>{controlsLoading ? "Loading..." : controlsCount}</strong>
            <span className="summary-meta">
              {controlsError ? controlsError : `Current target: ${osType}`}
            </span>
          </div>
        </section>

        <section className="grid">
          <article className="panel">
            <div className="panel-heading">
              <span className="panel-step">Step 1</span>
              <h2>Ingest Benchmark PDF</h2>
            </div>
            <p className="panel-copy">
              Upload the CIS PDF for the selected OS to populate the Chroma vector store.
            </p>

            <form onSubmit={handleIngest} className="stack">
              <label className="file-input">
                <span>{uploadFile ? uploadFile.name : "Choose PDF file"}</span>
                <input
                  type="file"
                  accept="application/pdf"
                  onChange={(event) => setUploadFile(event.target.files?.[0] || null)}
                />
              </label>

              <button type="submit" className="primary-button" disabled={ingestLoading}>
                {ingestLoading ? "Training vector DB..." : "Train Vector DB"}
              </button>
            </form>

            {ingestMessage ? <p className="status success">{ingestMessage}</p> : null}
            {ingestError ? <p className="status error">{ingestError}</p> : null}
          </article>

          <article className="panel">
            <div className="panel-heading">
              <span className="panel-step">Step 2</span>
              <h2>Generate Specific Snippet</h2>
            </div>
            <p className="panel-copy">
              Ask for one control or a small set of controls like 1.1.1.2 Disable USB Storage.
            </p>

            <form onSubmit={handleQuery} className="stack">
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Enter control IDs or names"
                rows={5}
              />

              <button type="submit" className="primary-button" disabled={queryLoading}>
                {queryLoading ? "Generating..." : "Generate Snippet"}
              </button>
            </form>

            {queryError ? <p className="status error">{queryError}</p> : null}
            {queryResult ? <pre className="result-block">{queryResult}</pre> : null}
          </article>

          <article className="panel panel-wide">
            <div className="panel-heading">
              <span className="panel-step">Step 3</span>
              <h2>Build Complete Hardening Script</h2>
            </div>
            <p className="panel-copy">
              Generate one combined script from all indexed controls for the selected OS.
            </p>

            <div className="action-row">
              <button
                type="button"
                className="primary-button"
                onClick={handleBuildScript}
                disabled={scriptLoading}
              >
                {scriptLoading ? "Building script..." : "Build Complete Script"}
              </button>

              <button
                type="button"
                className="secondary-button"
                onClick={downloadScript}
                disabled={!scriptResult}
              >
                Download Script
              </button>
            </div>

            {scriptLoading || scriptProgress ? (
              <div className="progress-card">
                <p className="status progress">{scriptProgress || "Building master script..."}</p>
                {scriptTotalControls ? (
                  <p className="progress-meta">
                    Processed {scriptProcessedControls} of {scriptTotalControls} control IDs
                  </p>
                ) : null}
              </div>
            ) : null}
            {scriptError ? <p className="status error">{scriptError}</p> : null}
            {scriptResult ? <pre className="result-block tall">{scriptResult}</pre> : null}
          </article>
        </section>
      </main>
    </div>
  );
}

export default App;
