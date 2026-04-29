(() => {
  const normalize = (value = "") =>
    value.replace(/[\u200B-\u200D\uFEFF]/g, "").replace(/\s+/g, " ").trim().toLowerCase();

  const currentPath = () => window.location.pathname.replace(/\/$/, "") || "/";

  const resolveLinkTarget = (text) => {
    const label = normalize(text);
    if (label.includes("quick actions")) return "/simulation";
    if (label.includes("refresh system")) return null;
    if (label.includes("dashboard") || label.includes("overview")) return "/";
    if (label.includes("webhooks")) return "/webhooks";
    if (label.includes("console") || label.includes("backend")) return "/backend";
    if (label.includes("explorer") || label.includes("queue") || label.includes("logs")) return "/queue";
    if (label.includes("scheduler")) return "/scheduler";
    if (label.includes("workers")) return "/workers";
    if (label.includes("simulation")) return "/simulation";
    if (label.includes("settings")) return "/settings";
    return null;
  };

  const matchesRoute = (target) => {
    const path = currentPath();
    if (target === "/") return path === "/" || path === "/index.html";
    return path === target || path === `${target}.html` || path.startsWith(`${target}/`);
  };

  const setActiveState = (element, active) => {
    if (!element) return;
    element.setAttribute("aria-current", active ? "page" : "false");
    element.dataset.active = active ? "true" : "false";
  };

  const rewriteNavigation = () => {
    // Convert legacy placeholder anchors to concrete routes when possible
    document.querySelectorAll('a[href="#"]').forEach((link) => {
      const target = resolveLinkTarget(link.textContent || "");
      if (target) {
        link.href = target;
      }
    });

    // Ensure nav links reflect the current active route
    document.querySelectorAll('nav a, aside a, header a').forEach((link) => {
      try {
        const href = link.getAttribute("href") || "";
        if (!href) return;
        // Only evaluate internal routes
        if (href.startsWith("/") || href.endsWith(".html")) {
          const target = href.replace(/\.html$/, "");
          setActiveState(link, matchesRoute(target));
        }
      } catch (e) {
        // ignore malformed hrefs
      }
    });
  };

  const allButtons = () => Array.from(document.querySelectorAll("button"));

  const buttonsWithLabel = (label) => {
    const expected = normalize(label);
    return allButtons().filter((button) => normalize(button.textContent || "").includes(expected));
  };

  const bindOnce = (button, handler) => {
    if (!button || button.dataset.bound === "true") return;
    button.dataset.bound = "true";
    button.addEventListener("click", handler);
  };

  const goTo = (path) => window.location.assign(path);

  const attachRefreshButtons = () => {
    buttonsWithLabel("refresh system").forEach((button) => {
      bindOnce(button, () => window.location.reload());
    });
  };

  const attachViewLogsButtons = () => {
    buttonsWithLabel("view logs").forEach((button) => {
      bindOnce(button, () => goTo("/queue"));
    });
  };

  const attachQuickActionButtons = () => {
    buttonsWithLabel("quick actions").forEach((button) => {
      bindOnce(button, () => {
        const path = currentPath();
        if (path.startsWith("/queue")) {
          const flushQueue = buttonsWithLabel("flush queue")[0];
          if (flushQueue) {
            flushQueue.click();
            return;
          }
        }
        if (path.startsWith("/webhooks")) {
          const triggerWebhook = buttonsWithLabel("trigger webhook")[0];
          if (triggerWebhook) {
            triggerWebhook.click();
            return;
          }
        }
        if (path.startsWith("/simulation")) {
          const crashButton = buttonsWithLabel("simulate global crash")[0];
          if (crashButton) {
            crashButton.click();
            return;
          }
        }
        goTo("/simulation");
      });
    });
  };

  const attachQueueActions = () => {
    const flushQueue = buttonsWithLabel("flush queue")[0];
    if (!flushQueue) return;

    bindOnce(flushQueue, async () => {
      flushQueue.disabled = true;
      try {
        const response = await fetch("/ui/queue/flush", { method: "POST" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        window.location.reload();
      } catch (error) {
        console.error("Queue flush failed", error);
        alert("Unable to flush the queue right now.");
      } finally {
        flushQueue.disabled = false;
      }
    });
  };

  const readInputValue = (selector, fallback) => {
    const input = document.querySelector(selector);
    return input && "value" in input ? input.value : fallback;
  };

  const attachWebhookActions = () => {
    const triggerWebhook = buttonsWithLabel("trigger webhook")[0];
    if (!triggerWebhook) return;

    bindOnce(triggerWebhook, async () => {
      const repository = readInputValue('input[value="jenkins-core/pipeline-engine"]', "acme/service");
      const branch = readInputValue('input[value="feature/log-streaming"]', "main");
      const author = readInputValue('input[value="devops-bot"]', "bot");

      try {
        const response = await fetch("/webhook/github/simulate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo_url: `https://github.com/${repository}`, branch, author, count: 1 }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        window.location.reload();
      } catch (error) {
        console.error("Webhook simulation failed", error);
        alert("Unable to trigger a simulated webhook.");
      }
    });
  };

  const attachSimulationActions = () => {
    const simulateCrash = buttonsWithLabel("simulate global crash")[0];
    if (!simulateCrash) return;

    bindOnce(simulateCrash, async () => {
      simulateCrash.disabled = true;
      try {
        const response = await fetch("/webhook/github/simulate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ count: 3 }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        window.location.reload();
      } catch (error) {
        console.error("Simulation failed", error);
        alert("Unable to launch the simulation.");
      } finally {
        simulateCrash.disabled = false;
      }
    });
  };

  const populateQueueData = async () => {
    try {
      const response = await fetch("/ui/queue");
      if (!response.ok) throw new Error("Failed to fetch queue data");

      const data = await response.json();
      const tableBody = document.querySelector("table tbody");
      if (!tableBody) return;

      const existingRows = tableBody.querySelectorAll("tr");
      for (let index = existingRows.length - 1; index > 0; index -= 1) {
        existingRows[index].remove();
      }

      const runs = (data.runs_by_status?.QUEUED || []).concat(data.runs_by_status?.IN_PROGRESS || []);
      runs.forEach((run) => {
        const row = document.createElement("tr");
        const waitSeconds = run.queued_at ? Math.max(0, Math.floor((Date.now() - new Date(run.queued_at).getTime()) / 1000)) : null;
        const statusBadge = run.status === "QUEUED" ? { bg: "#fef3c7", color: "#92400e" } : { bg: "#dbeafe", color: "#1e40af" };
        row.innerHTML = `
          <td>${run.id || "-"}</td>
          <td>${run.priority || "Normal"}</td>
          <td>${run.language || ""}</td>
          <td>
            <div class="flex flex-col"><span class="font-medium">${run.repo || (run.repo_url ? run.repo_url.replace(/^https?:\/\//, '') : '')}</span>
            <span class="text-label-md text-on-surface-variant flex items-center gap-1"><span class="material-symbols-outlined text-[12px]">call_split</span> ${run.branch || ""}</span></div>
          </td>
          <td class="font-code-sm">${waitSeconds !== null ? waitSeconds + 's' : '-'}</td>
          <td><span style="padding: 4px 12px; border-radius: 4px; background: ${statusBadge.bg}; color: ${statusBadge.color}">${run.status || ""}</span></td>
          <td class="text-right"><button class="text-outline hover:text-error transition-colors p-1" data-cancel-id="${run.id || ''}" title="Cancel Job"><span class="material-symbols-outlined text-[18px]">cancel</span></button></td>
        `;
        tableBody.appendChild(row);
      });
    } catch (error) {
      console.error("Failed to populate queue data:", error);
    }
  };

  const populateQueueMetrics = async () => {
    try {
      const response = await fetch('/ui/queue');
      if (!response.ok) return;
      const data = await response.json();
      const queued = data.runs_by_status?.QUEUED || [];
      const inProg = data.runs_by_status?.IN_PROGRESS || [];
      const active = [...queued, ...inProg];

      const totalEl = document.querySelector('[data-ui="queue-total"]');
      if (totalEl) totalEl.textContent = String(data.total || 0);

      const now = Date.now();
      const waitTimes = active
        .filter(r => r.queued_at)
        .map(r => Math.max(0, Math.floor((now - new Date(r.queued_at).getTime()) / 1000)));

      const avgWaitEl = document.querySelector('[data-ui="avg-wait-queue"]');
      if (avgWaitEl && waitTimes.length) {
        const avg = (waitTimes.reduce((a, b) => a + b, 0) / waitTimes.length).toFixed(1);
        avgWaitEl.innerHTML = `${avg}<span class="text-headline-sm font-headline-sm text-on-surface-variant ml-1">sec</span>`;
      }

      const longestEl = document.querySelector('[data-ui="longest-wait"]');
      if (longestEl && waitTimes.length) {
        const max = Math.max(...waitTimes);
        longestEl.innerHTML = `${max}<span class="text-headline-sm font-headline-sm text-on-surface-variant ml-1">sec</span>`;
      }

      const throughputEl = document.querySelector('[data-ui="throughput"]');
      if (throughputEl) {
        const completed = (data.runs_by_status?.COMPLETED || []).length;
        throughputEl.innerHTML = `${completed}<span class="text-headline-sm font-headline-sm text-on-surface-variant ml-1">/session</span>`;
      }
    } catch (error) {
      console.error('Failed to populate queue metrics:', error);
    }
  };


  const populateQueueTable = async () => {
    try {
      const response = await fetch('/ui/queue');
      if (!response.ok) throw new Error('Failed to fetch queue data');
      const data = await response.json();
      const tableBody = document.querySelector('table tbody');
      if (!tableBody) return;
      // clear existing rows
      tableBody.innerHTML = '';
      const runs = (data.runs_by_status?.QUEUED || []).concat(data.runs_by_status?.IN_PROGRESS || []);
      runs.forEach((run) => {
        const row = document.createElement('tr');
        const waitSeconds = run.queued_at ? Math.max(0, Math.floor((Date.now() - new Date(run.queued_at).getTime()) / 1000)) : null;
        const statusBadge = run.status === 'QUEUED' ? { bg: '#fef3c7', color: '#92400e' } : { bg: '#dbeafe', color: '#1e40af' };
        row.className = 'border-b border-surface-variant hover:bg-surface-container-low transition-colors group';
        row.innerHTML = `
          <td class="px-md py-sm"><span class="text-code-sm font-code-sm text-surface-tint">#J-${run.id || ''}</span></td>
          <td class="px-md py-sm"><span class="bg-surface-container-highest text-on-surface-variant text-label-md px-2 py-0.5 rounded-full">${run.priority || 'Normal'}</span></td>
          <td class="px-md py-sm"><span class="material-symbols-outlined text-[20px]">code</span></td>
          <td class="px-md py-sm"><div class="flex flex-col"><span class="font-medium">${run.repo || (run.repo_url ? run.repo_url.replace(/^https?:\/\//, '') : '')}</span><span class="text-label-md text-on-surface-variant flex items-center gap-1"><span class="material-symbols-outlined text-[12px]">call_split</span> ${run.branch || ''}</span></div></td>
          <td class="px-md py-sm font-code-sm">${waitSeconds !== null ? waitSeconds + 's' : '-'}</td>
          <td class="px-md py-sm"><span class="flex items-center gap-1.5 text-secondary"><span class="material-symbols-outlined text-[16px]">sync</span> ${run.status || ''}</span></td>
          <td class="px-md py-sm text-right opacity-0 group-hover:opacity-100 transition-opacity"><button class="text-outline hover:text-error transition-colors p-1" title="Cancel Job"><span class="material-symbols-outlined text-[18px]">cancel</span></button></td>
        `;
        tableBody.appendChild(row);
      });
    } catch (error) {
      console.error('Failed to populate queue table:', error);
    }
  };

  const populateSchedulerData = async () => {
    try {
      const response = await fetch("/ui/scheduler");
      if (!response.ok) throw new Error("Failed to fetch scheduler data");

      const data = await response.json();
      const tableBody = document.querySelector("table tbody");
      if (!tableBody) return;

      const existingRows = tableBody.querySelectorAll("tr");
      for (let index = existingRows.length - 1; index > 0; index -= 1) {
        existingRows[index].remove();
      }

      (data.scheduled || []).forEach((job) => {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${job.repo || ""}</td>
          <td>${job.branch || ""}</td>
          <td>${job.job_name || ""}</td>
          <td><span style="padding: 4px 12px; border-radius: 4px; background: #dbeafe; color: #1e40af">${job.priority || ""}</span></td>
          <td>${job.estimated_wait || ""}</td>
        `;
        tableBody.appendChild(row);
      });
    } catch (error) {
      console.error("Failed to populate scheduler data:", error);
    }
  };

  const populateSchedulerKanban = async () => {
    try {
      const response = await fetch('/ui/scheduler');
      if (!response.ok) throw new Error('Failed to fetch scheduler data');
      const data = await response.json();

      const queuedCountEl = document.querySelector('[data-ui="kanban-queued-count"]');
      const scheduledCountEl = document.querySelector('[data-ui="kanban-scheduled-count"]');
      const runningCountEl = document.querySelector('[data-ui="kanban-running-count"]');
      if (queuedCountEl) queuedCountEl.textContent = String((data.queued || []).length);
      if (scheduledCountEl) scheduledCountEl.textContent = String((data.scheduled || []).length);
      if (runningCountEl) runningCountEl.textContent = String((data.running || []).length);

      const queuedList = document.querySelector('[data-ui="kanban-queued-list"]');
      const scheduledList = document.querySelector('[data-ui="kanban-scheduled-list"]');
      const runningList = document.querySelector('[data-ui="kanban-running-list"]');

      const renderJobCard = (job) => {
        const el = document.createElement('div');
        el.className = 'bg-surface-container-lowest border border-outline-variant rounded p-sm shadow-sm hover:shadow-[0px_10px_15px_rgba(0,0,0,0.05)] transition-shadow cursor-grab';
        el.innerHTML = `
          <div class="flex justify-between items-start mb-2">
            <span class="font-code-sm text-code-sm font-semibold text-on-surface">${job.id || job.job_id || 'JOB'}</span>
            <span class="material-symbols-outlined text-outline text-[16px]">more_horiz</span>
          </div>
          <div class="font-body-md text-[13px] text-on-surface-variant mb-3 line-clamp-2">${job.summary || job.description || ''}</div>
          <div class="flex items-center gap-2 mt-auto border-t border-outline-variant/50 pt-2">
            <span class="font-label-md text-[10px] text-outline">PRIORITY: ${job.priority || 'N/A'}</span>
          </div>
        `;
        return el;
      };

      if (queuedList) {
        queuedList.innerHTML = '';
        (data.queued || []).forEach((j) => queuedList.appendChild(renderJobCard(j)));
      }
      if (scheduledList) {
        scheduledList.innerHTML = '';
        (data.scheduled || []).forEach((j) => scheduledList.appendChild(renderJobCard(j)));
      }
      if (runningList) {
        runningList.innerHTML = '';
        (data.running || []).forEach((j) => runningList.appendChild(renderJobCard(j)));
      }
    } catch (error) {
      console.error('Failed to populate scheduler kanban:', error);
    }
  };

  const populateWebhookEvents = async () => {
    try {
      const response = await fetch('/ui/build_events');
      if (!response.ok) throw new Error('Failed to fetch build events');
      const data = await response.json();
      const tbody = document.querySelector('[data-ui="webhook-events-body"]');
      if (!tbody) return;
      tbody.innerHTML = '';
      const events = data.events || [];
      events.slice(0, 50).forEach((ev) => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-surface-variant hover:bg-surface-container-lowest transition-colors group';
        tr.innerHTML = `
          <td class="px-md py-sm text-on-surface-variant font-code-sm text-code-sm">${ev.processed_at ? new Date(ev.processed_at).toLocaleTimeString() : '-'}</td>
          <td class="px-md py-sm"><span class="bg-surface-container px-2 py-0.5 rounded text-xs border border-outline-variant">${ev.event_type || ev.failure_type || 'event'}</span></td>
          <td class="px-md py-sm">${ev.repo_name || ev.job_name || '-'}</td>
          <td class="px-md py-sm font-code-sm text-code-sm text-on-surface-variant">${ev.delivery_id || ev.id || '-'}</td>
          <td class="px-md py-sm text-right"><span class="inline-flex items-center gap-1 bg-[#e6f4ea] text-[#137333] px-2 py-0.5 rounded-full text-xs font-semibold">${ev.delivery_status || 'OK'}</span></td>
        `;
        tbody.appendChild(tr);
      });
    } catch (error) {
      console.error('Failed to populate webhook events:', error);
    }
  };

  const formatBytes = (value) => {
    if (!Number.isFinite(value)) return '-';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = value;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex += 1;
    }
    return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  };

  const renderQueueDatabaseState = (data) => {
    const database = data.queue?.database;
    if (!database) return;

    const totalRecords = document.querySelector('[data-ui="queue-db-total-records"]');
    const fileSize = document.querySelector('[data-ui="queue-db-size"]');
    const jobRows = document.querySelector('[data-ui="queue-db-job-rows"]');
    const execRows = document.querySelector('[data-ui="queue-db-exec-rows"]');
    const workerRows = document.querySelector('[data-ui="queue-db-worker-rows"]');
    const webhookRows = document.querySelector('[data-ui="queue-db-webhook-rows"]');

    if (totalRecords) totalRecords.textContent = Number(database.total_records || 0).toLocaleString();
    if (fileSize) fileSize.textContent = `File size: ${database.file_size || '-'}`;
    if (jobRows && database.tables?.[0]) jobRows.textContent = `${Number(database.tables[0].rows || 0).toLocaleString()} rows`;
    if (execRows && database.tables?.[1]) execRows.textContent = `${Number(database.tables[1].rows || 0).toLocaleString()} rows`;
    if (workerRows && database.tables?.[2]) workerRows.textContent = `${Number(database.tables[2].rows || 0).toLocaleString()} rows`;
    if (webhookRows && database.tables?.[3]) webhookRows.textContent = `${Number(database.tables[3].rows || 0).toLocaleString()} rows`;
  };

  const renderBackendPanel = (data) => {
    const backend = data.backend;
    if (!backend) return;

    const status = document.querySelector('[data-ui="backend-status"]');
    const uptime = document.querySelector('[data-ui="backend-uptime"]');
    const technology = document.querySelector('[data-ui="backend-technology"]');
    const port = document.querySelector('[data-ui="backend-port"]');
    const memory = document.querySelector('[data-ui="backend-memory"]');
    const memoryBar = document.getElementById('backend-memory-bar');
    const alertTitle = document.querySelector('[data-ui="backend-alert-title"]');
    const alertCopy = document.querySelector('[data-ui="backend-alert-copy"]');
    const endpointBody = document.querySelector('[data-ui="backend-endpoint-body"]');
    const requestBody = document.querySelector('[data-ui="backend-request-body"]');

    if (status) {
      status.lastChild && (status.lastChild.textContent = ` ${backend.status || 'RUNNING'}`);
    }
    if (uptime) uptime.textContent = backend.uptime || '-';
    if (technology) technology.textContent = backend.technology || 'FastAPI / Python';
    if (port) port.textContent = backend.port || '8000';
    if (memory) {
      const used = Number(backend.memory_used || 0);
      const total = Number(backend.memory_total || 0);
      const pct = total > 0 ? Math.round((used / total) * 100) : 0;
      memory.innerHTML = `${formatBytes(used)} <span class="text-outline font-body-md text-body-md">/ ${formatBytes(total)}</span>`;
      if (memoryBar) memoryBar.style.width = `${pct}%`;
    }

    const buildEvents = data.build_events || [];
    const latest = buildEvents[0];
    if (alertTitle && latest) {
      alertTitle.textContent = `${String(latest.severity || 'Warning').toUpperCase()} ALERT: ${String(latest.failure_type || 'issue').replace(/_/g, ' ').toUpperCase()}`;
    }
    if (alertCopy) {
      alertCopy.textContent = latest?.summary_text || 'Backend is healthy and serving live data.';
    }

    if (endpointBody) {
      endpointBody.innerHTML = '';
      (data.backend_routes || []).forEach((route) => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-surface-container-low transition-colors ambient-shadow-hover';
        const isHealthy = String(route.status || '').toLowerCase() === 'healthy';
        tr.innerHTML = `
          <td class="py-sm font-code-sm text-code-sm text-on-surface">${route.route || '-'}</td>
          <td class="py-sm"><span class="inline-flex items-center gap-1 ${isHealthy ? 'text-primary bg-primary-container' : 'text-error bg-error-container'} px-2 py-0.5 rounded font-label-md text-label-md"><span class="material-symbols-outlined text-[14px]">${isHealthy ? 'check_circle' : 'warning'}</span> ${route.status || 'Healthy'}</span></td>
          <td class="py-sm font-code-sm text-code-sm text-on-surface text-right">${route.latency || '-'}</td>
          <td class="py-sm font-code-sm text-code-sm text-on-surface text-right">${route.rate || '0.0%'}</td>
        `;
        endpointBody.appendChild(tr);
      });
    }

    if (requestBody) {
      requestBody.innerHTML = '';
      (data.backend_request_feed || []).forEach((request) => {
        const tr = document.createElement('tr');
        const statusColor = String(request.status || '').startsWith('5') ? 'text-error' : 'text-primary';
        tr.className = 'hover:bg-surface-container-low transition-colors';
        tr.innerHTML = `
          <td class="py-2 px-md text-outline">${request.id || '-'}</td>
          <td class="py-2 px-md text-on-surface-variant">${request.timestamp ? new Date(request.timestamp).toLocaleTimeString() : '-'}</td>
          <td class="py-2 px-md"><span class="bg-surface-container text-on-surface-variant px-1.5 py-0.5 rounded border border-outline-variant">${request.method || 'GET'}</span></td>
          <td class="py-2 px-md text-on-surface">${request.route || '-'}</td>
          <td class="py-2 px-md text-right"><span class="${statusColor} font-bold">${request.status || '200'}</span></td>
        `;
        requestBody.appendChild(tr);
      });
    }
  };

  const renderWorkersPanels = (data) => {
    const assignmentBody = document.querySelector('[data-ui="worker-assignment-body"]');
    if (assignmentBody) {
      assignmentBody.innerHTML = '';
      const workers = data.workers?.items || [];
      workers.slice(0, 3).forEach((worker, index) => {
        const row = document.createElement('tr');
        row.className = 'border-b border-surface-variant hover:bg-surface-container-low transition-colors';
        const tag = worker.language ? worker.language.charAt(0).toUpperCase() + worker.language.slice(1) : 'General';
        row.innerHTML = `
          <td class="py-2 px-md font-code-sm text-code-sm">lang=${worker.language || 'any'}</td>
          <td class="py-2 px-md"><span class="bg-surface-container px-2 py-0.5 rounded text-[10px] font-label-md">${tag}</span></td>
          <td class="py-2 px-md text-on-surface-variant">${index + 1}</td>
        `;
        assignmentBody.appendChild(row);
      });
    }

    const timelineRows = document.querySelector('[data-ui="worker-timeline-rows"]');
    if (timelineRows) {
      timelineRows.innerHTML = '';
      const workers = data.workers?.items || [];
      const runs = data.queue?.latest_runs || [];
      workers.forEach((worker, index) => {
        const row = document.createElement('div');
        row.className = 'flex items-center h-8 relative';
        const load = Math.max(0, Math.min(100, Math.round((worker.load || 0) * 100)));
        const currentJob = worker.current_job || runs[index]?.jenkins_job_name || 'idle';
        row.innerHTML = `
          <div class="w-32 flex-shrink-0 font-code-sm text-code-sm ${index % 2 === 1 ? 'text-on-surface-variant' : ''}">${worker.name || 'worker'}</div>
          <div class="flex-1 relative h-full bg-surface-container-low rounded">
            <div class="absolute left-0 top-0 h-full bg-secondary-fixed-dim rounded opacity-80 border border-outline-variant" style="width:${Math.max(10, 100 - load)}%" title="${currentJob} (Queued)"></div>
            <div class="absolute right-0 top-0 h-full bg-primary rounded border border-primary-container shadow-sm" style="width:${load}%" title="${currentJob} (Running)"></div>
          </div>
        `;
        timelineRows.appendChild(row);
      });
    }
  };

  const renderSimulationPanel = (data) => {
    const simulation = data.simulation;
    if (!simulation) return;

    const intensity = document.querySelector('[data-ui="chaos-intensity"]');
    const level = document.querySelector('[data-ui="chaos-level"]');
    const arrivalSpan = document.querySelector('[data-ui="arrival-rate"]');
    const arrivalInput = document.querySelector('[data-ui="arrival-rate-input"]');
    const burstSpan = document.querySelector('[data-ui="burst-prob"]');
    const burstInput = document.querySelector('[data-ui="burst-prob-input"]');
    const failureSpan = document.querySelector('[data-ui="simulation-failure-rate"]');
    const failureInput = document.querySelector('[data-ui="simulation-failure-rate-input"]');
    const minDuration = document.querySelector('[data-ui="simulation-min-duration"]');
    const maxDuration = document.querySelector('[data-ui="simulation-max-duration"]');
    const pipelineStatus = document.querySelector('[data-ui="pipeline-status"]');
    const pipelineLog = document.querySelector('[data-ui="pipeline-log"]');
    const eventBody = document.querySelector('[data-ui="simulation-live-log"]');

    if (intensity) intensity.textContent = `${simulation.chaos_intensity || 0}%`;
    if (level) level.textContent = simulation.chaos_level || 'Normal';
    if (arrivalSpan && arrivalInput) {
      arrivalSpan.textContent = `${simulation.arrival_rate || 0} req/s`;
      arrivalInput.value = simulation.arrival_rate || 0;
      arrivalInput.addEventListener('input', (e) => {
        arrivalSpan.textContent = `${e.target.value} req/s`;
      });
    }
    if (burstSpan && burstInput) {
      burstSpan.textContent = `${simulation.burst_prob || 0}%`;
      burstInput.value = simulation.burst_prob || 0;
      burstInput.addEventListener('input', (e) => {
        burstSpan.textContent = `${e.target.value}%`;
      });
    }
    if (failureSpan && failureInput) {
      failureSpan.textContent = `${simulation.failure_rate || 0}%`;
      failureInput.value = simulation.failure_rate || 0;
      failureInput.addEventListener('input', (e) => {
        failureSpan.textContent = `${e.target.value}%`;
      });
    }
    if (minDuration) minDuration.value = simulation.min_duration_ms || 100;
    if (maxDuration) maxDuration.value = simulation.max_duration_ms || 5000;

    if (pipelineStatus && pipelineStatus.textContent.trim() === 'Ready') {
      pipelineStatus.textContent = `${simulation.chaos_level || 'Normal'} simulation ready`;
    }
    if (pipelineLog && pipelineLog.childElementCount === 0) {
      pipelineLog.innerHTML = '<div>Live simulation data synchronized from the backend.</div>';
    }

    if (eventBody) {
      eventBody.innerHTML = '';
      const buildEvents = data.build_events || [];
      const latestRuns = data.queue?.latest_runs || [];
      const rows = [];
      buildEvents.slice(0, 4).forEach((event) => {
        rows.push({
          timestamp: event.processed_at,
          type: event.failure_type || 'Build Event',
          target: event.job_name || '-',
          details: event.summary_text || '-',
          severity: event.severity,
        });
      });
      latestRuns.slice(0, 4).forEach((run) => {
        rows.push({
          timestamp: run.queued_at,
          type: run.status || 'Queue Update',
          target: run.repo_url ? run.repo_url.split('/').pop() : '-',
          details: `${run.branch || 'main'} triggered by ${run.triggered_by || 'system'}`,
          severity: run.status === 'FAILED' ? 'error' : 'info',
        });
      });

      rows.slice(0, 6).forEach((row) => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-surface-container-low transition-colors';
        const labelClass = row.severity === 'error' ? 'bg-error-container text-on-error-container' : row.severity === 'info' ? 'bg-surface-container-high text-on-surface' : 'bg-tertiary-container text-on-tertiary-container';
        tr.innerHTML = `
          <td class="p-sm text-on-surface-variant whitespace-nowrap">${row.timestamp ? new Date(row.timestamp).toLocaleTimeString() : '-'}</td>
          <td class="p-sm"><span class="px-2 py-0.5 ${labelClass} rounded-sm font-semibold">${row.type || '-'}</span></td>
          <td class="p-sm text-primary">${row.target || '-'}</td>
          <td class="p-sm">${row.details || '-'}</td>
        `;
        eventBody.appendChild(tr);
      });
    }
  };

    // Simulation page bindings
    function bindSimulationControls(bootstrap) {
      const intensity = document.querySelector('[data-ui="chaos-intensity"]');
      const level = document.querySelector('[data-ui="chaos-level"]');
      const arrivalSpan = document.querySelector('[data-ui="arrival-rate"]');
      const arrivalInput = document.querySelector('[data-ui="arrival-rate-input"]');
      const burstSpan = document.querySelector('[data-ui="burst-prob"]');
      const burstInput = document.querySelector('[data-ui="burst-prob-input"]');
      const failureSpan = document.querySelector('[data-ui="simulation-failure-rate"]');
      const failureInput = document.querySelector('[data-ui="simulation-failure-rate-input"]');
      const minDuration = document.querySelector('[data-ui="simulation-min-duration"]');
      const maxDuration = document.querySelector('[data-ui="simulation-max-duration"]');

      if (intensity && bootstrap.health) {
        intensity.textContent = Math.round((bootstrap.health.chaos_intensity || 0) * 100) + '%';
      }
      if (level && bootstrap.health) {
        level.textContent = (bootstrap.health.chaos_level || 'Normal');
      }
      if (arrivalSpan && arrivalInput) {
        const v = bootstrap.simulation?.arrival_rate || 42;
        arrivalSpan.textContent = v + ' req/s';
        arrivalInput.value = v;
        arrivalInput.addEventListener('input', (e) => {
          arrivalSpan.textContent = e.target.value + ' req/s';
        });
      }
      if (burstSpan && burstInput) {
        const b = bootstrap.simulation?.burst_prob || 15;
        burstSpan.textContent = b + '%';
        burstInput.value = b;
        burstInput.addEventListener('input', (e) => {
          burstSpan.textContent = e.target.value + '%';
        });
      }
      if (failureSpan && failureInput) {
        const failureRate = bootstrap.simulation?.failure_rate || 5;
        failureSpan.textContent = failureRate + '%';
        failureInput.value = failureRate;
        failureInput.addEventListener('input', (e) => {
          failureSpan.textContent = e.target.value + '%';
        });
      }
      if (minDuration) minDuration.value = bootstrap.simulation?.min_duration_ms || 100;
      if (maxDuration) maxDuration.value = bootstrap.simulation?.max_duration_ms || 5000;
    }
  const populateWorkers = async () => {
    try {
      const [bootstrapRes, workersRes] = await Promise.all([
        fetch('/ui/bootstrap'),
        fetch('/api/workers'),
      ]);
      if (!bootstrapRes.ok) throw new Error('Failed to fetch bootstrap data');
      const data = await bootstrapRes.json();

      let liveById = {};
      if (workersRes.ok) {
        const wd = await workersRes.json();
        (wd.workers || []).forEach((w) => { liveById[w.id] = w; });

        // Populate summary stats bar
        const summary = wd.summary || {};
        const statTotal = document.querySelector('[data-ui="worker-stat-total"]');
        const statIdle = document.querySelector('[data-ui="worker-stat-idle"]');
        const statBusy = document.querySelector('[data-ui="worker-stat-busy"]');
        const statOffline = document.querySelector('[data-ui="worker-stat-offline"]');
        if (statTotal) statTotal.textContent = String(summary.total ?? 0);
        if (statIdle) statIdle.textContent = String(summary.idle ?? 0);
        if (statBusy) statBusy.textContent = String(summary.busy ?? 0);
        if (statOffline) statOffline.textContent = String(summary.offline ?? 0);
      }

      const container = document.querySelector('[data-ui="workers-list"]');
      if (!container) return;
      container.innerHTML = '';
      const items = (data.workers && data.workers.items) || [];
      items.forEach((w) => {
        const live = liveById[w.id] || {};
        const merged = { ...w, ...live };
        const card = document.createElement('div');
        card.className = 'bg-surface-container-lowest border border-outline-variant rounded-xl shadow-[0px_4px_6px_rgba(0,0,0,0.02)] p-md flex flex-col gap-sm hover:shadow-[0px_10px_15px_rgba(0,0,0,0.05)] transition-shadow';
        const status = (merged.status || '').toLowerCase();
        const isBusy = status === 'busy';
        const isOffline = status === 'offline';
        const pct = Math.round((merged.load || 0) * 100);
        const jobsRun = merged.jobs_run != null ? merged.jobs_run : '—';
        const currentJob = merged.current_job || null;
        const statusBadge = isBusy
          ? `<span class="bg-primary-container text-on-primary-container px-2 py-1 rounded text-[10px] font-label-md flex items-center gap-1"><span class="material-symbols-outlined text-[12px] animate-pulse">sync</span> BUSY</span>`
          : isOffline
          ? `<span class="bg-error-container text-on-error-container px-2 py-1 rounded text-[10px] font-label-md flex items-center gap-1"><span class="material-symbols-outlined text-[12px]">power_off</span> OFFLINE</span>`
          : `<span class="bg-surface-variant text-on-surface-variant px-2 py-1 rounded text-[10px] font-label-md flex items-center gap-1"><span class="material-symbols-outlined text-[12px]">pause</span> IDLE</span>`;
        const currentJobRow = currentJob
          ? `<div class="mt-xs"><span class="font-label-md text-[10px] text-on-surface-variant">JOB: </span><span class="font-code-sm text-code-sm text-primary truncate">${currentJob}</span></div>`
          : '';
        card.innerHTML = `
          <div class="flex justify-between items-start">
            <div>
              <h3 class="font-headline-sm text-headline-sm text-on-surface">${merged.name || 'worker'}</h3>
              <div class="flex gap-xs mt-xs">
                <span class="bg-surface-container px-2 py-0.5 rounded text-[10px] font-label-md text-on-surface-variant">${merged.language || ''}</span>
              </div>
              ${currentJobRow}
            </div>
            ${statusBadge}
          </div>
          <div class="mt-sm ${isBusy ? '' : 'opacity-40'}">
            <div class="flex justify-between font-label-md text-label-md text-on-surface-variant mb-1">
              <span>${isBusy ? 'Load' : 'Awaiting assignment'}</span>
              <span>${isBusy ? pct + '%' : '--'}</span>
            </div>
            <div class="h-2 bg-surface-container rounded-full overflow-hidden"><div class="h-full bg-primary" style="width: ${pct}%"></div></div>
          </div>
          <div class="grid grid-cols-2 gap-sm mt-auto pt-sm border-t border-surface-variant ${isBusy ? '' : 'opacity-70'}">
            <div><span class="font-label-md text-[10px] text-on-surface-variant block mb-1">CPU</span><div class="font-code-sm text-code-sm text-on-surface ${pct > 90 ? 'text-error' : ''}">${pct}%</div></div>
            <div><span class="font-label-md text-[10px] text-on-surface-variant block mb-1">JOBS RUN</span><div class="font-code-sm text-code-sm text-on-surface">${jobsRun}</div></div>
          </div>
        `;
        container.appendChild(card);
      });

      // Rebuild assignment table with all workers
      const assignmentBody = document.querySelector('[data-ui="worker-assignment-body"]');
      if (assignmentBody) {
        assignmentBody.innerHTML = '';
        items.forEach((w) => {
          const live = liveById[w.id] || {};
          const merged = { ...w, ...live };
          let caps = [];
          try { caps = JSON.parse(merged.capabilities || '[]'); } catch (e) { caps = []; }
          const tag = merged.language ? merged.language.charAt(0).toUpperCase() + merged.language.slice(1) : 'General';
          const statusDot = (merged.status || '').toLowerCase() === 'busy'
            ? '<span class="inline-block w-2 h-2 rounded-full bg-primary mr-1"></span>'
            : (merged.status || '').toLowerCase() === 'offline'
            ? '<span class="inline-block w-2 h-2 rounded-full bg-error mr-1"></span>'
            : '<span class="inline-block w-2 h-2 rounded-full bg-outline mr-1"></span>';
          const row = document.createElement('tr');
          row.className = 'border-b border-surface-variant hover:bg-surface-container-low transition-colors';
          row.innerHTML = `
            <td class="py-2 px-md font-code-sm text-code-sm">${statusDot}${merged.name || 'worker'}</td>
            <td class="py-2 px-md"><span class="bg-surface-container px-2 py-0.5 rounded text-[10px] font-label-md">${tag}</span>${caps.slice(0,2).map(c => ` <span class="text-[10px] text-on-surface-variant">${c}</span>`).join('')}</td>
            <td class="py-2 px-md text-on-surface-variant font-code-sm">${merged.jobs_run ?? 0}</td>
          `;
          assignmentBody.appendChild(row);
        });
      }

      renderWorkersPanels(data);
    } catch (error) {
      console.error('Failed to populate workers:', error);
    }
  };

  const populateBootstrapData = async () => {
    try {
      const response = await fetch('/ui/bootstrap');
      if (!response.ok) throw new Error('Failed to fetch bootstrap data');
      const data = await response.json();

      // Last updated
      const lastEl = document.querySelector('[data-ui="last-updated"]');
      if (lastEl) lastEl.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;

      // Queue counts
      const qDepth = document.querySelector('[data-ui="queue-depth"]');
      if (qDepth && data.queue && typeof data.queue.total !== 'undefined') {
        qDepth.textContent = String(data.queue.total);
      }
      const topologyCount = document.querySelector('[data-ui="topology-queue-count"]');
      if (topologyCount && data.queue && typeof data.queue.queued !== 'undefined') {
        topologyCount.textContent = String(data.queue.queued);
      }
      const avgWait = document.querySelector('[data-ui="avg-wait"]');
      if (avgWait && data.queue && typeof data.queue.avg_wait_seconds !== 'undefined') {
        avgWait.textContent = `Avg wait: ${Number(data.queue.avg_wait_seconds).toFixed(1)}s`;
      }

      // System uptime
      const uptime = document.querySelector('[data-ui="system-uptime"]');
      if (uptime && data.health && data.health.uptime_percentage) {
        uptime.textContent = String(data.health.uptime_percentage);
      }

      // Worker utilization
      const workerUtil = document.querySelector('[data-ui="worker-utilization"]');
      const workerBar = document.getElementById('worker-utilization-bar');
      if (workerUtil && data.workers && typeof data.workers.total !== 'undefined') {
        const total = data.workers.total || 0;
        const busy = data.workers.busy || 0;
        const pct = total > 0 ? Math.round((busy / total) * 100) : 0;
        workerUtil.textContent = `${pct}%`;
        if (workerBar) workerBar.style.width = `${pct}%`;
      }
      // initialize page-specific panels if present
      try { bindSimulationControls(data); } catch (err) { console.warn('bindSimulationControls failed', err); }
      try { renderQueueDatabaseState(data); } catch (err) { console.warn('renderQueueDatabaseState failed', err); }
      try { renderBackendPanel(data); } catch (err) { console.warn('renderBackendPanel failed', err); }
      try { renderWorkersPanels(data); } catch (err) { console.warn('renderWorkersPanels failed', err); }
      try { renderSimulationPanel(data); } catch (err) { console.warn('renderSimulationPanel failed', err); }
    } catch (error) {
      console.error('Failed to populate bootstrap data:', error);
    }
  };

  const pollLiveMetrics = async () => {
    try {
      const response = await fetch('/ui/metrics/live');
      if (!response.ok) throw new Error('Failed to fetch live metrics');
      const result = await response.json();
      
      if (result.status !== 'ok' || !result.data) return;
      
      const data = result.data;
      const timestamp = result.timestamp;

      // Update backend panel with live metrics
      const uptimeEl = document.querySelector('[data-ui="backend-uptime"]');
      if (uptimeEl) uptimeEl.textContent = data.uptime_formatted || `${data.uptime_seconds}s`;

      const memUsedEl = document.querySelector('[data-ui="backend-memory-used"]');
      if (memUsedEl) {
        const memMB = Math.round(data.memory_used_bytes / (1024 * 1024));
        const totalGB = (data.memory_total_bytes / (1024 * 1024 * 1024)).toFixed(1);
        memUsedEl.textContent = `${memMB} MB / ${totalGB} GB`;
      }

      const cpuEl = document.querySelector('[data-ui="backend-cpu"]');
      if (cpuEl) cpuEl.textContent = `${data.cpu_percent.toFixed(1)}%`;

      // Update chaos intensity/level
      const chaosIntensityEl = document.querySelector('[data-ui="chaos-intensity"]');
      if (chaosIntensityEl) chaosIntensityEl.textContent = `${data.chaos_intensity}%`;

      const chaosLevelEl = document.querySelector('[data-ui="chaos-level"]');
      if (chaosLevelEl) chaosLevelEl.textContent = data.chaos_level || '';

      // Update queue info
      const queueTotalEl = document.querySelector('[data-ui="queue-total-live"]');
      if (queueTotalEl) queueTotalEl.textContent = String(data.queue_total);

      const workerBusyEl = document.querySelector('[data-ui="worker-busy-live"]');
      if (workerBusyEl) workerBusyEl.textContent = `${data.busy_workers}/${data.worker_total}`;

      // Update last poll time
      const lastPollEl = document.querySelector('[data-ui="last-metric-poll"]');
      if (lastPollEl) lastPollEl.textContent = `Last poll: ${new Date(timestamp).toLocaleTimeString()}`;

    } catch (error) {
      console.warn('Live metrics polling failed', error);
    }
  };

  window.triggerJenkinsFailure = async () => {
    const statusEl = document.getElementById("pipeline-status");
    const logEl = document.getElementById("pipeline-log");
    if (!statusEl || !logEl) return;

    statusEl.textContent = "Processing...";
    statusEl.style.color = "#ba1a1a";

    try {
      const response = await fetch("/webhook/jenkins/simulate", { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();

      logEl.innerHTML += `<div>[${new Date().toLocaleTimeString()}] ✓ Jenkins failure triggered: ${result.job_name} #${result.build_number}</div>`;
      statusEl.textContent = "Jenkins failure injected -> Analyzing...";
      statusEl.style.color = "#f59e0b";

      setTimeout(async () => {
        try {
          const queueResponse = await fetch("/ui/queue");
          const queueData = await queueResponse.json();
          const failureCount = (queueData.runs_by_status?.FAILED || []).length;
          logEl.innerHTML += `<div>[${new Date().toLocaleTimeString()}] 📊 LLM analysis running... Check /queue for status</div>`;
          statusEl.textContent = `Failure analysis complete (${failureCount} failed jobs)`;
          statusEl.style.color = "#059669";
        } catch (error) {
          console.error("Queue poll failed", error);
        }
      }, 2000);
    } catch (error) {
      logEl.innerHTML += `<div style="color: #dc2626">[${new Date().toLocaleTimeString()}] ✗ Error: ${error.message}</div>`;
      statusEl.textContent = "Error";
      statusEl.style.color = "#ba1a1a";
    }
  };

  window.triggerGitHubPush = async () => {
    const statusEl = document.getElementById("pipeline-status");
    const logEl = document.getElementById("pipeline-log");
    if (!statusEl || !logEl) return;

    statusEl.textContent = "Processing...";
    statusEl.style.color = "#0f766e";

    try {
      const response = await fetch("/webhook/github/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count: 1 }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();

      logEl.innerHTML += `<div>[${new Date().toLocaleTimeString()}] ✓ GitHub push simulated: ${result.simulated} job(s) queued</div>`;
      statusEl.textContent = "GitHub push -> Enqueued in scheduler...";
      statusEl.style.color = "#f59e0b";

      setTimeout(async () => {
        try {
          const queueResponse = await fetch("/ui/queue");
          const queueData = await queueResponse.json();
          const queuedCount = (queueData.runs_by_status?.QUEUED || []).length;
          logEl.innerHTML += `<div>[${new Date().toLocaleTimeString()}] 📦 Job queued. Awaiting worker dispatch (${queuedCount} in queue)</div>`;
          statusEl.textContent = "Job queued -> Waiting for worker";
          statusEl.style.color = "#7c3aed";
        } catch (error) {
          console.error("Queue poll failed", error);
        }
      }, 1500);
    } catch (error) {
      logEl.innerHTML += `<div style="color: #dc2626">[${new Date().toLocaleTimeString()}] ✗ Error: ${error.message}</div>`;
      statusEl.textContent = "Error";
      statusEl.style.color = "#ba1a1a";
    }
  };

  window.refreshBuildEvents = async () => {
    const container = document.getElementById("llm-analysis");
    if (!container) return;

    container.innerHTML = '<div class="text-on-surface-variant">Loading analysis...</div>';

    try {
      const response = await fetch("/ui/build_events");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      if (!data.events || data.events.length === 0) {
        container.innerHTML = '<div class="text-on-surface-variant">No analysis records available.</div>';
        return;
      }

      container.innerHTML = "";
      data.events.forEach((event) => {
        const block = document.createElement("div");
        block.className = "p-sm border-b border-surface-variant";
        const fixes = (event.fix_suggestions || []).map((fix) => `<li>${fix}</li>`).join("");
        block.innerHTML = `
          <div class="font-semibold">${event.job_name} #${event.build_number} - ${event.severity} (${event.failure_type})</div>
          <div class="text-xs text-on-surface-variant">Processed: ${event.processed_at ? new Date(event.processed_at).toLocaleString() : "-"} | Delivery: ${event.delivery_status || "-"}</div>
          <div class="mt-2">${event.summary_text || ""}</div>
          <ul class="mt-2 text-sm text-on-surface-variant">${fixes}</ul>
          <a class="text-primary block mt-1" href="${event.log_url || "#"}" target="_blank" rel="noreferrer">View full log</a>
        `;
        container.appendChild(block);
      });
    } catch (error) {
      container.innerHTML = `<div style="color:#dc2626">Error loading analysis: ${error.message}</div>`;
    }
  };

  const init = () => {
    rewriteNavigation();
    attachRefreshButtons();
    attachViewLogsButtons();
    attachQuickActionButtons();
    attachQueueActions();
    attachWebhookActions();
    attachSimulationActions();

    if (currentPath().startsWith("/queue")) {
      if (document.querySelector("table tbody")) {
        populateQueueTable();
        populateQueueMetrics();
        let qInterval = setInterval(() => {
          if (document.querySelector("table tbody")) {
            populateQueueTable();
            populateQueueMetrics();
          } else {
            clearInterval(qInterval);
          }
        }, 5000);
      }
    }

    if (currentPath().startsWith("/scheduler")) {
      if (document.querySelector('[data-ui="kanban-queued-list"]')) {
        populateSchedulerKanban();
        let sInterval = setInterval(() => {
          if (document.querySelector('[data-ui="kanban-queued-list"]')) {
            populateSchedulerKanban();
          } else {
            clearInterval(sInterval);
          }
        }, 5000);
      }
    }

    if (currentPath().startsWith('/workers')) {
      if (document.querySelector('[data-ui="workers-list"]')) {
        populateWorkers();
        let wInterval = setInterval(() => {
          if (document.querySelector('[data-ui="workers-list"]')) {
            populateWorkers();
          } else {
            clearInterval(wInterval);
          }
        }, 5000);
      }
    }

    if (currentPath().startsWith('/webhooks')) {
      if (document.querySelector('[data-ui="webhook-events-body"]')) {
        populateWebhookEvents();
        let hInterval = setInterval(() => {
          if (document.querySelector('[data-ui="webhook-events-body"]')) {
            populateWebhookEvents();
          } else {
            clearInterval(hInterval);
          }
        }, 5000);
      }
    }

    // Populate global bootstrap/dashboard data when present
    try {
      populateBootstrapData();
      const bInterval = setInterval(() => {
        if (document.querySelector('[data-ui="last-updated"]')) {
          populateBootstrapData();
        } else {
          clearInterval(bInterval);
        }
      }, 10000);
    } catch (e) {
      // ignore
    }

    // Start polling live metrics every 5 seconds
    try {
      pollLiveMetrics();
      const metricsInterval = setInterval(() => {
        pollLiveMetrics();
      }, 5000);
    } catch (e) {
      console.warn('Live metrics polling not available', e);
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
