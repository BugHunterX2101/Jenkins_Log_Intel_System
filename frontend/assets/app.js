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
    if (label.includes("explorer") || label.includes("logs")) return "/explorer";
    if (label.includes("queue")) return "/queue";
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
    // F2: "View All Logs" should open the Pipeline Explorer (full history),
    // not the Queue page (only shows active QUEUED/IN_PROGRESS runs)
    buttonsWithLabel("view logs").forEach((button) => {
      bindOnce(button, () => goTo("/explorer"));
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


  const populateQueueMetrics = async () => {
    try {
      const response = await fetch('/ui/queue');
      if (!response.ok) return;
      const data = await response.json();
      const queued = data.runs_by_status?.QUEUED || [];
      const inProg = data.runs_by_status?.IN_PROGRESS || [];
      const active = [...queued, ...inProg];

      const totalEl = document.querySelector('[data-ui="queue-total"]');
      // F6: show active queue depth only (not historical completed/failed count)
      if (totalEl) totalEl.textContent = String(active.length);

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
      const tableBody = document.querySelector('[data-ui="queue-table-body"]');
      if (!tableBody) return;
      // clear existing rows
      tableBody.innerHTML = '';
      const runs = (data.runs_by_status?.QUEUED || []).concat(data.runs_by_status?.IN_PROGRESS || []);
      if (!runs.length) {
        const empty = document.createElement('tr');
        empty.innerHTML = '<td colspan="7" class="px-md py-6 text-center text-on-surface-variant text-sm">No active jobs in the queue</td>';
        tableBody.appendChild(empty);
      } else {
        runs.forEach((run) => {
          const row = document.createElement('tr');
          const waitSeconds = run.queued_at ? Math.max(0, Math.floor((Date.now() - new Date(run.queued_at).getTime()) / 1000)) : null;
          row.className = 'border-b border-surface-variant hover:bg-surface-container-low transition-colors group';
          // F5: derive priority from branch — 'priority' field not in API response
          const priority = run.branch === 'main' ? 'High' : 'Normal';
          const priorityClass = priority === 'High'
            ? 'bg-primary-fixed text-on-primary-fixed'
            : 'bg-surface-container-highest text-on-surface-variant';
          row.innerHTML = `
            <td class="px-md py-sm"><span class="text-code-sm font-code-sm text-surface-tint">#J-${run.id || ''}</span></td>
            <td class="px-md py-sm"><span class="${priorityClass} text-label-md px-2 py-0.5 rounded-full">${priority}</span></td>
            <td class="px-md py-sm"><span class="material-symbols-outlined text-[20px]">code</span></td>
            <td class="px-md py-sm"><div class="flex flex-col"><span class="font-medium">${run.repo || ''}</span><span class="text-label-md text-on-surface-variant flex items-center gap-1"><span class="material-symbols-outlined text-[12px]">call_split</span> ${run.branch || ''}</span></div></td>
            <td class="px-md py-sm font-code-sm">${waitSeconds !== null ? waitSeconds + 's' : '-'}</td>
            <td class="px-md py-sm"><span class="flex items-center gap-1.5 text-secondary"><span class="material-symbols-outlined text-[16px]">sync</span> ${run.status || ''}</span></td>
            <td class="px-md py-sm text-right opacity-0 group-hover:opacity-100 transition-opacity"><button class="text-outline hover:text-error transition-colors p-1" title="Cancel Job"><span class="material-symbols-outlined text-[18px]">cancel</span></button></td>
          `;
          tableBody.appendChild(row);
        });
      }
    } catch (error) {
      console.error('Failed to populate queue table:', error);
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
      const completedList = document.querySelector('[data-ui="kanban-completed-list"]');
      const completedCountEl = document.querySelector('[data-ui="kanban-completed-count"]');

      const renderJobCard = (job, variant) => {
        const el = document.createElement('div');
        const isRunning = variant === 'running';
        const isCompleted = variant === 'completed';
        el.className = isCompleted
          ? 'bg-surface-container-lowest border border-outline-variant rounded p-sm shadow-sm border-l-4 border-l-[#10B981]'
          : isRunning
          ? 'bg-surface-container-lowest border border-primary/40 rounded p-sm shadow-sm relative overflow-hidden'
          : 'bg-surface-container-lowest border border-outline-variant rounded p-sm shadow-sm hover:shadow-[0px_10px_15px_rgba(0,0,0,0.05)] transition-shadow cursor-grab';
        const durationLabel = job.duration_s ? `${Math.floor(job.duration_s / 60)}m ${job.duration_s % 60}s` : (job.started ? new Date(job.started).toLocaleTimeString() : '—');
        el.innerHTML = `
          <div class="flex justify-between items-start mb-2">
            <span class="font-code-sm text-code-sm font-semibold text-on-surface ${isCompleted ? 'line-through text-outline' : ''}">#${job.id || 'JOB'}</span>
            ${isCompleted
              ? '<span class="material-symbols-outlined text-[#10B981] text-[18px]">check_circle</span>'
              : '<span class="material-symbols-outlined text-outline text-[16px]">more_horiz</span>'}
          </div>
          <div class="font-body-md text-[13px] text-on-surface-variant mb-3 line-clamp-2">${job.summary || job.description || `${job.repo || ''}/${job.branch || 'main'}`}</div>
          <div class="flex items-center justify-between mt-auto border-t border-outline-variant/50 pt-2">
            <span class="font-label-md text-[10px] text-outline">PRIORITY: ${(job.priority || 'normal').toUpperCase()}</span>
            ${isRunning || isCompleted ? `<span class="font-code-sm text-[11px] text-outline">${durationLabel}</span>` : ''}
          </div>
        `;
        return el;
      };

      const _emptyCard = (msg) => {
        const el = document.createElement('div');
        el.className = 'text-center text-on-surface-variant text-[12px] py-4';
        el.textContent = msg;
        return el;
      };

      if (queuedList) {
        queuedList.innerHTML = '';
        const queued = data.queued || [];
        queued.length ? queued.forEach((j) => queuedList.appendChild(renderJobCard(j, 'queued'))) : queuedList.appendChild(_emptyCard('No jobs queued'));
      }
      if (scheduledList) {
        scheduledList.innerHTML = '';
        // "scheduled" is FIFO-ordered (oldest first = next to run) — no dedup needed
        const scheduled = data.scheduled || [];
        scheduled.length ? scheduled.forEach((j) => scheduledList.appendChild(renderJobCard(j, 'scheduled'))) : scheduledList.appendChild(_emptyCard('No scheduled jobs'));
      }
      if (runningList) {
        runningList.innerHTML = '';
        const running = data.running || [];
        running.length ? running.forEach((j) => runningList.appendChild(renderJobCard(j, 'running'))) : runningList.appendChild(_emptyCard('No running jobs'));
      }
      if (completedList) {
        completedList.innerHTML = '';
        const completed = data.completed || [];
        if (completedCountEl) completedCountEl.textContent = String(completed.length);
        completed.length ? completed.slice(0, 8).forEach((j) => completedList.appendChild(renderJobCard(j, 'completed'))) : completedList.appendChild(_emptyCard('No completed jobs'));
      }

      // Decision Log
      const decisionLog = document.querySelector('[data-ui="decision-log-list"]');
      if (decisionLog) {
        decisionLog.innerHTML = '';
        const running = data.running || [];
        const queued = data.queued || [];
        const completed = (data.completed || []).slice(0, 3);
        const entries = [];
        running.forEach((j) => entries.push({ type: 'assigned', job: j }));
        queued.slice(0, 4).forEach((j) => entries.push({ type: 'queued', job: j }));
        completed.forEach((j) => entries.push({ type: 'completed', job: j }));

        if (!entries.length) {
          decisionLog.innerHTML = '<li class="p-sm px-md text-on-surface-variant text-[12px]">No scheduler activity yet</li>';
        } else {
          entries.forEach(({ type, job }) => {
            const li = document.createElement('li');
            li.className = 'p-sm px-md hover:bg-surface-container-lowest transition-colors flex gap-3 items-start';
            const dotColor = type === 'assigned' ? 'bg-primary' : type === 'completed' ? 'bg-[#10B981]' : 'bg-secondary';
            const ts = job.started
              ? new Date(job.started).toLocaleTimeString()
              : job.completed
              ? new Date(job.completed).toLocaleTimeString()
              : job.queued_at
              ? new Date(job.queued_at).toLocaleTimeString()
              : '—';
            const label = type === 'assigned'
              ? `<span class="font-semibold text-primary">Job #${job.id}</span> running — ${job.repo || ''}/${job.branch || 'main'}`
              : type === 'completed'
              ? `<span class="font-semibold text-[#10B981]">Job #${job.id} COMPLETED</span> — ${job.repo || ''}/${job.branch || 'main'}`
              : `<span class="font-semibold">Job #${job.id}</span> queued, awaiting capacity`;
            li.innerHTML = `
              <div class="w-2 h-2 mt-1.5 rounded-full ${dotColor} flex-shrink-0"></div>
              <div>
                <div class="font-code-sm text-[12px] text-on-surface mb-1">${label}</div>
                <div class="font-code-sm text-[10px] text-outline">${ts} • ${job.job_name || 'pipeline'}</div>
              </div>
            `;
            decisionLog.appendChild(li);
          });
        }
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
      if (!events.length) {
        const empty = document.createElement('tr');
        empty.innerHTML = '<td colspan="5" class="px-md py-6 text-center text-on-surface-variant text-sm">No webhook events recorded yet</td>';
        tbody.appendChild(empty);
      } else {
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
      }
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
    const alertBar = document.querySelector('[data-ui="backend-alert-bar"]');
    if (alertBar) {
      if (latest) {
        alertBar.classList.remove('hidden');
        alertBar.style.display = 'flex';
      } else {
        alertBar.classList.add('hidden');
        alertBar.style.display = '';
      }
    }
    if (alertTitle) {
      alertTitle.textContent = latest
        ? `${String(latest.severity || 'Warning').toUpperCase()} ALERT: ${String(latest.failure_type || 'issue').replace(/_/g, ' ').toUpperCase()}`
        : 'System Status: All Clear';
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
    // Skip on workers page — populateWorkers() owns these elements there
    if (currentPath().startsWith('/workers')) return;

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

    if (intensity) {
      const pct = simulation.chaos_intensity || 0;
      intensity.textContent = `${pct}%`;
      const dialCircle = intensity.closest('div')?.previousElementSibling?.querySelector('circle:last-child');
      if (dialCircle) dialCircle.setAttribute('stroke-dashoffset', String(Math.round(283 * (1 - pct / 100))));
    }
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
        const pct = Math.round((bootstrap.health.chaos_intensity || 0) * 100);
        intensity.textContent = pct + '%';
        const dialCircle = intensity.closest('div')?.previousElementSibling?.querySelector('circle:last-child');
        if (dialCircle) dialCircle.setAttribute('stroke-dashoffset', String(Math.round(283 * (1 - pct / 100))));
      }
      if (level && bootstrap.health) {
        level.textContent = (bootstrap.health.chaos_level || 'Normal');
      }
      if (arrivalSpan && arrivalInput) {
        const v = bootstrap.simulation?.arrival_rate || 42;
        arrivalSpan.textContent = v + ' req/s';
        arrivalInput.value = v;
        if (!arrivalInput.dataset.bound) {
          arrivalInput.dataset.bound = 'true';
          arrivalInput.addEventListener('input', (e) => { arrivalSpan.textContent = e.target.value + ' req/s'; });
        }
      }
      if (burstSpan && burstInput) {
        const b = bootstrap.simulation?.burst_prob || 15;
        burstSpan.textContent = b + '%';
        burstInput.value = b;
        if (!burstInput.dataset.bound) {
          burstInput.dataset.bound = 'true';
          burstInput.addEventListener('input', (e) => { burstSpan.textContent = e.target.value + '%'; });
        }
      }
      if (failureSpan && failureInput) {
        const failureRate = bootstrap.simulation?.failure_rate || 5;
        failureSpan.textContent = failureRate + '%';
        failureInput.value = failureRate;
        if (!failureInput.dataset.bound) {
          failureInput.dataset.bound = 'true';
          failureInput.addEventListener('input', (e) => { failureSpan.textContent = e.target.value + '%'; });
        }
      }
      if (minDuration) minDuration.value = bootstrap.simulation?.min_duration_ms || 100;
      if (maxDuration) maxDuration.value = bootstrap.simulation?.max_duration_ms || 5000;
    }
  const populateWorkers = async () => {
    try {
      const workersRes = await fetch('/api/workers');
      if (!workersRes.ok) throw new Error('Failed to fetch workers');
      const wd = await workersRes.json();
      const items = wd.workers || [];
      const summary = wd.summary || {};

      // Stat cards
      const statTotal = document.querySelector('[data-ui="worker-stat-total"]');
      const statIdle = document.querySelector('[data-ui="worker-stat-idle"]');
      const statBusy = document.querySelector('[data-ui="worker-stat-busy"]');
      const statOffline = document.querySelector('[data-ui="worker-stat-offline"]');
      if (statTotal) statTotal.textContent = String(summary.total ?? items.length);
      if (statIdle) statIdle.textContent = String(summary.idle ?? items.filter(w => w.status === 'IDLE').length);
      if (statBusy) statBusy.textContent = String(summary.busy ?? items.filter(w => w.status === 'BUSY').length);
      if (statOffline) statOffline.textContent = String(summary.offline ?? items.filter(w => w.status === 'OFFLINE').length);

      const container = document.querySelector('[data-ui="workers-list"]');
      if (!container) return;
      container.innerHTML = '';
      if (!items.length) {
        container.innerHTML = '<div class="col-span-full py-8 text-center text-on-surface-variant">No workers available</div>';
        return;
      }
      items.forEach((w) => {
        const merged = { ...w };
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

      // Assignment logic table
      const assignmentBody = document.querySelector('[data-ui="worker-assignment-body"]');
      if (assignmentBody) {
        assignmentBody.innerHTML = '';
        if (!items.length) {
          assignmentBody.innerHTML = '<tr><td colspan="3" class="py-4 text-center text-on-surface-variant">No workers</td></tr>';
        } else {
          items.forEach((w) => {
            const tag = w.language ? w.language.charAt(0).toUpperCase() + w.language.slice(1) : 'General';
            const statusDot = w.status === 'BUSY'
              ? '<span class="inline-block w-2 h-2 rounded-full bg-primary mr-1"></span>'
              : w.status === 'OFFLINE'
              ? '<span class="inline-block w-2 h-2 rounded-full bg-error mr-1"></span>'
              : '<span class="inline-block w-2 h-2 rounded-full bg-outline mr-1"></span>';
            const row = document.createElement('tr');
            row.className = 'border-b border-surface-variant hover:bg-surface-container-low transition-colors';
            row.innerHTML = `
              <td class="py-2 px-md font-code-sm text-code-sm">${statusDot}lang=${w.language || 'any'}</td>
              <td class="py-2 px-md"><span class="bg-surface-container px-2 py-0.5 rounded text-[10px] font-label-md">${tag}</span></td>
              <td class="py-2 px-md text-on-surface-variant font-code-sm">${w.jobs_run ?? 0}</td>
            `;
            assignmentBody.appendChild(row);
          });
        }
      }

      // Timeline rows
      const timelineRows = document.querySelector('[data-ui="worker-timeline-rows"]');
      if (timelineRows) {
        timelineRows.innerHTML = '';
        items.forEach((w) => {
          const row = document.createElement('div');
          row.className = 'flex items-center h-8 relative';
          const load = Math.max(0, Math.min(100, Math.round((w.load || 0) * 100)));
          const isBusy = w.status === 'BUSY';
          row.innerHTML = `
            <div class="w-32 flex-shrink-0 font-code-sm text-code-sm text-on-surface-variant truncate">${w.name || 'worker'}</div>
            <div class="flex-1 relative h-full bg-surface-container-low rounded overflow-hidden">
              <div class="absolute left-0 top-0 h-full bg-secondary-fixed-dim rounded opacity-80" style="width:${Math.max(5, 100 - load)}%" title="Idle"></div>
              ${isBusy ? `<div class="absolute right-0 top-0 h-full bg-primary rounded" style="width:${load}%" title="${w.current_job || 'running'}"></div>` : ''}
            </div>
            <div class="ml-2 w-10 text-right font-code-sm text-[11px] text-on-surface-variant">${load}%</div>
          `;
          timelineRows.appendChild(row);
        });
      }
    } catch (error) {
      console.error('Failed to populate workers:', error);
    }
  };

  let _metricsPaused = false;
  let _allPollingIntervals = [];
  let _autoArriveInterval = null;
  let _schedulerKanbanInterval = null;
  let _activityLastTimestamp = null;

  const _activityBadge = (status) => {
    const s = (status || '').toUpperCase();
    if (s === 'COMPLETED') return 'bg-green-100 text-green-800 border-green-200';
    if (s === 'IN_PROGRESS') return 'bg-amber-100 text-amber-800 border-amber-200';
    if (s === 'FAILED') return 'bg-red-100 text-red-800 border-red-200';
    if (s === 'ABORTED') return 'bg-slate-100 text-slate-600 border-slate-200';
    return 'bg-blue-100 text-blue-800 border-blue-200'; // QUEUED / default
  };

  const _activityLabel = (status) => {
    const s = (status || '').toUpperCase();
    if (s === 'COMPLETED') return 'Success';
    if (s === 'IN_PROGRESS') return 'Running';
    if (s === 'FAILED') return 'Failed';
    if (s === 'ABORTED') return 'Aborted';
    return 'Queued';
  };

  const renderActivityStream = (data) => {
    const tbody = document.querySelector('[data-ui="activity-stream-body"]');
    if (!tbody) return;

    const items = data.activity_stream || (data.queue?.latest_runs || []).map((run) => ({
      timestamp: run.queued_at,
      source: run.author || run.triggered_by || 'system',
      event: `Push to ${run.branch || 'unknown'} — ${run.repo_url ? run.repo_url.replace(/\.git$/, '').split('/').pop() : 'unknown'}${run.commit_sha ? ' (' + run.commit_sha.slice(0, 7) + ')' : ''}`,
      status: run.status || 'QUEUED',
    }));

    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="py-4 px-md text-center text-on-surface-variant text-sm">No recent activity</td></tr>';
      return;
    }

    const newestTs = items[0]?.timestamp || null;
    const isNew = newestTs && _activityLastTimestamp && newestTs > _activityLastTimestamp;
    _activityLastTimestamp = newestTs;

    tbody.innerHTML = '';
    items.forEach((item, index) => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-slate-50 transition-colors';
      if (isNew && index === 0) {
        tr.classList.add('bg-green-50');
        setTimeout(() => tr.classList.remove('bg-green-50'), 1500);
      }
      const ts = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '—';
      const badgeClasses = _activityBadge(item.status);
      const label = _activityLabel(item.status);
      tr.innerHTML = `
        <td class="py-2 px-md text-on-surface-variant">${ts}</td>
        <td class="py-2 px-md font-medium text-primary truncate max-w-[120px]">${item.source || '—'}</td>
        <td class="py-2 px-md truncate max-w-xs">${item.event || '—'}</td>
        <td class="py-2 px-md text-right">
          <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${badgeClasses}">${label}</span>
        </td>
      `;
      tbody.appendChild(tr);
    });
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
      const workerNodeCount = document.querySelector('[data-ui="worker-node-count"]');
      if (workerUtil && data.workers && typeof data.workers.total !== 'undefined') {
        const total = data.workers.total || 0;
        const busy = data.workers.busy || 0;
        const pct = total > 0 ? Math.round((busy / total) * 100) : 0;
        workerUtil.textContent = `${pct}%`;
        if (workerBar) workerBar.style.width = `${pct}%`;
        if (workerNodeCount) workerNodeCount.textContent = `${busy} of ${total} nodes active`;
      }
      // initialize page-specific panels if present
      try { bindSimulationControls(data); } catch (err) { console.warn('bindSimulationControls failed', err); }
      try { renderQueueDatabaseState(data); } catch (err) { console.warn('renderQueueDatabaseState failed', err); }
      try { renderBackendPanel(data); } catch (err) { console.warn('renderBackendPanel failed', err); }
      try { renderWorkersPanels(data); } catch (err) { console.warn('renderWorkersPanels failed', err); }
      try { renderSimulationPanel(data); } catch (err) { console.warn('renderSimulationPanel failed', err); }
      try { renderActivityStream(data); } catch (err) { console.warn('renderActivityStream failed', err); }
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

      // F1: correct selector — element is [data-ui="backend-memory"], not "backend-memory-used"
      const memUsedEl = document.querySelector('[data-ui="backend-memory"]');
      if (memUsedEl) {
        const memMB = Math.round(data.memory_used_bytes / (1024 * 1024));
        const totalGB = (data.memory_total_bytes / (1024 * 1024 * 1024)).toFixed(1);
        memUsedEl.innerHTML = `${memMB} MB <span class="text-outline font-body-md text-body-md">/ ${totalGB} GB</span>`;
        const memBar = document.getElementById('backend-memory-bar');
        if (memBar) {
          const pct = Math.round((data.memory_used_bytes / data.memory_total_bytes) * 100);
          memBar.style.width = `${pct}%`;
        }
      }

      // F3: update CPU element now that it exists in backend.html
      const cpuEl = document.querySelector('[data-ui="backend-cpu"]');
      if (cpuEl) cpuEl.textContent = `${(data.cpu_percent || 0).toFixed(1)}%`;

      // Update simulation page chaos dial
      const chaosIntensityEl = document.querySelector('[data-ui="chaos-intensity"]');
      if (chaosIntensityEl) {
        chaosIntensityEl.textContent = `${data.chaos_intensity}%`;
        const dialCircle = chaosIntensityEl.closest('div')?.previousElementSibling?.querySelector('circle:last-child');
        if (dialCircle) dialCircle.setAttribute('stroke-dashoffset', String(Math.round(283 * (1 - data.chaos_intensity / 100))));
      }

      const chaosLevelEl = document.querySelector('[data-ui="chaos-level"]');
      if (chaosLevelEl) chaosLevelEl.textContent = data.chaos_level || '';

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

  // ─── Header icon buttons (all pages) ───
  const attachHeaderIconButtons = () => {
    document.querySelectorAll('button').forEach((btn) => {
      const icon = btn.querySelector('.material-symbols-outlined');
      if (!icon) return;
      const name = (icon.dataset.icon || icon.textContent || '').trim();
      if (name === 'health_and_safety') bindOnce(btn, () => window.open('/health', '_blank'));
      if (name === 'cloud_sync') bindOnce(btn, () => { populateBootstrapData(); pollLiveMetrics(); });
      if (name === 'settings') bindOnce(btn, () => goTo('/settings'));
    });
  };

  // ─── Queue page: live search filter ───
  const attachQueueSearch = () => {
    const searchInput = document.querySelector('input[placeholder="Filter jobs..."]');
    const filterBtn = document.querySelector('button .material-symbols-outlined');
    if (!searchInput || searchInput.dataset.bound) return;
    searchInput.dataset.bound = 'true';
    let statusFilter = false;
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.toLowerCase();
      document.querySelectorAll('[data-ui="queue-table-body"] tr').forEach((row) => {
        const text = row.textContent.toLowerCase();
        row.style.display = !q || text.includes(q) ? '' : 'none';
      });
    });
    const filterButton = Array.from(document.querySelectorAll('button')).find(b => b.querySelector('.material-symbols-outlined')?.textContent?.trim() === 'filter_list');
    if (filterButton) {
      bindOnce(filterButton, () => {
        statusFilter = !statusFilter;
        filterButton.classList.toggle('text-primary', statusFilter);
        document.querySelectorAll('[data-ui="queue-table-body"] tr').forEach((row) => {
          if (!statusFilter) { row.style.display = ''; return; }
          const isQueued = row.textContent.includes('QUEUED');
          row.style.display = isQueued ? '' : 'none';
        });
      });
    }
  };

  // ─── Scheduler controls ───
  const _setActiveModeButton = (modeButtons, mode) => {
    modeButtons.forEach(b => b.classList.remove('bg-surface-container-lowest', 'shadow-sm', 'border', 'border-outline-variant/30', 'text-on-surface'));
    const active = modeButtons.find(b => b.textContent.trim() === mode);
    if (active) active.classList.add('bg-surface-container-lowest', 'shadow-sm', 'border', 'border-outline-variant/30', 'text-on-surface');
  };

  const attachSchedulerControls = () => {
    const modeButtons = Array.from(document.querySelectorAll('button')).filter(b =>
      ['FIFO', 'Priority', 'Load-Balanced'].includes(b.textContent.trim())
    );

    // Load active mode from backend on page load
    fetch('/ui/scheduler/mode')
      .then(r => r.json())
      .then(d => {
        localStorage.setItem('schedulerMode', d.mode);
        _setActiveModeButton(modeButtons, d.mode);
      })
      .catch(() => {
        const saved = localStorage.getItem('schedulerMode') || 'Priority';
        _setActiveModeButton(modeButtons, saved);
      });

    modeButtons.forEach((btn) => {
      bindOnce(btn, async () => {
        const mode = btn.textContent.trim();
        _setActiveModeButton(modeButtons, mode);
        localStorage.setItem('schedulerMode', mode);
        try {
          await fetch('/ui/scheduler/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode }),
          });
        } catch (e) {
          console.warn('Failed to set scheduler mode:', e);
        }
      });
    });

    const slider = document.querySelector('input[type="range"][min="100"][max="5000"]');
    const sliderLabel = slider?.closest('div')?.querySelector('span');
    if (slider) {
      const saved = localStorage.getItem('schedulerPollMs');
      if (saved) { slider.value = saved; if (sliderLabel) sliderLabel.textContent = saved + 'ms'; }
      slider.addEventListener('input', () => {
        if (sliderLabel) sliderLabel.textContent = slider.value + 'ms';
        localStorage.setItem('schedulerPollMs', slider.value);
        if (_schedulerKanbanInterval) {
          clearInterval(_schedulerKanbanInterval);
          _schedulerKanbanInterval = setInterval(() => {
            if (document.querySelector('[data-ui="kanban-queued-list"]')) populateSchedulerKanban();
            else clearInterval(_schedulerKanbanInterval);
          }, Number(slider.value));
          _allPollingIntervals.push(_schedulerKanbanInterval);
        }
      });
    }

    const masterSwitch = document.querySelector('input[type="checkbox"].sr-only');
    const kanbanSection = document.querySelector('[data-ui="kanban-queued-list"]')?.closest('.col-span-12');
    if (masterSwitch) {
      masterSwitch.addEventListener('change', () => {
        if (!masterSwitch.checked) {
          if (_schedulerKanbanInterval) clearInterval(_schedulerKanbanInterval);
          if (kanbanSection) kanbanSection.style.opacity = '0.4';
        } else {
          const ms = Number(localStorage.getItem('schedulerPollMs') || 5000);
          _schedulerKanbanInterval = setInterval(() => {
            if (document.querySelector('[data-ui="kanban-queued-list"]')) populateSchedulerKanban();
            else clearInterval(_schedulerKanbanInterval);
          }, ms);
          _allPollingIntervals.push(_schedulerKanbanInterval);
          if (kanbanSection) kanbanSection.style.opacity = '';
          populateSchedulerKanban();
        }
      });
    }

    const filterBtn = document.querySelector('[data-ui="kanban-queued-list"]')?.closest('.col-span-12')
      ?.querySelector('button');
    if (filterBtn) {
      let runningOnly = false;
      bindOnce(filterBtn, () => {
        runningOnly = !runningOnly;
        filterBtn.classList.toggle('text-primary', runningOnly);
        ['[data-ui="kanban-queued-list"]', '[data-ui="kanban-scheduled-list"]'].forEach((sel) => {
          const el = document.querySelector(sel);
          if (el) el.closest('.flex-col')?.style && (el.closest('.flex-col').style.display = runningOnly ? 'none' : '');
        });
      });
    }
  };

  // ─── Workers page controls ───
  const attachWorkerControls = () => {
    const editBtn = document.querySelector('button .material-symbols-outlined[data-icon="edit"]')?.closest('button')
      || Array.from(document.querySelectorAll('button')).find(b => b.querySelector('.material-symbols-outlined')?.textContent?.trim() === 'edit');
    if (editBtn) bindOnce(editBtn, () => goTo('/explorer'));

    const fallback = document.querySelector('select');
    if (fallback) {
      const saved = localStorage.getItem('workerFallbackPolicy');
      if (saved) {
        Array.from(fallback.options).forEach((opt, i) => { if (opt.text === saved) fallback.selectedIndex = i; });
      }
      fallback.addEventListener('change', () => {
        localStorage.setItem('workerFallbackPolicy', fallback.options[fallback.selectedIndex].text);
        const toast = document.createElement('div');
        toast.className = 'fixed bottom-6 right-6 bg-on-surface text-surface px-4 py-2 rounded shadow-lg text-sm z-50';
        toast.textContent = 'Policy saved';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2000);
      });
    }
  };

  // ─── Webhooks page: copy URL, visibility toggle, reset, burst mode ───
  const attachWebhookPageActions = () => {
    const ngrokInput = document.querySelector('[data-ui="ngrok-url"]');
    const copyBtn = Array.from(document.querySelectorAll('button')).find(b => normalize(b.textContent).includes('copy url'));
    if (copyBtn && ngrokInput) {
      bindOnce(copyBtn, () => {
        navigator.clipboard.writeText(ngrokInput.value).catch(() => {});
        const orig = copyBtn.innerHTML;
        copyBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size:16px">check</span> Copied!';
        setTimeout(() => { copyBtn.innerHTML = orig; }, 1500);
      });
    }

    const secretInput = document.querySelector('input[type="password"]');
    const visBtn = secretInput?.closest('div')?.querySelector('button');
    if (visBtn && secretInput) {
      bindOnce(visBtn, () => {
        const isHidden = secretInput.type === 'password';
        secretInput.type = isHidden ? 'text' : 'password';
        const icon = visBtn.querySelector('.material-symbols-outlined');
        if (icon) icon.textContent = isHidden ? 'visibility_off' : 'visibility';
      });
    }

    const resetBtn = Array.from(document.querySelectorAll('button')).find(b => normalize(b.textContent).includes('reset defaults'));
    if (resetBtn) {
      bindOnce(resetBtn, () => {
        const branch = document.querySelector('[data-ui="wh-branch"]');
        const sha = document.querySelector('[data-ui="wh-sha"]');
        const author = document.querySelector('[data-ui="wh-author"]');
        const repo = document.querySelector('[data-ui="wh-repo"]');
        const eventType = document.querySelector('[data-ui="wh-event-type"]');
        if (branch) branch.value = 'main';
        if (sha) sha.value = '';
        if (author) author.value = 'devops-bot';
        if (repo) repo.selectedIndex = 0;
        if (eventType) eventType.selectedIndex = 0;
      });
    }

    const burstToggle = document.querySelector('[data-ui="burst-mode-toggle"]');
    if (burstToggle) {
      bindOnce(burstToggle, () => {
        const active = burstToggle.dataset.burst === '1';
        burstToggle.dataset.burst = active ? '5' : '1';
        burstToggle.classList.toggle('bg-primary', !active);
        burstToggle.classList.toggle('bg-outline-variant', active);
        const dot = burstToggle.querySelector('div');
        if (dot) dot.style.left = !active ? '18px' : '2px';
      });
    }
  };

  // ─── Patched Trigger Webhook — reads live form values ───
  const attachWebhookActionsFixed = () => {
    const triggerWebhook = buttonsWithLabel("trigger webhook")[0];
    if (!triggerWebhook) return;
    bindOnce(triggerWebhook, async () => {
      const repoSelect = document.querySelector('[data-ui="wh-repo"]');
      const branchInput = document.querySelector('[data-ui="wh-branch"]');
      const authorInput = document.querySelector('[data-ui="wh-author"]');
      const burstToggle = document.querySelector('[data-ui="burst-mode-toggle"]');
      const repo = repoSelect ? repoSelect.value : 'acme/service';
      const branch = branchInput ? branchInput.value : 'main';
      const author = authorInput ? authorInput.value : 'bot';
      const count = burstToggle ? Number(burstToggle.dataset.burst || 1) : 1;
      try {
        const response = await fetch('/webhook/github/simulate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ repo_url: `https://github.com/${repo}`, branch, author, count }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        window.location.reload();
      } catch (error) {
        console.error('Webhook simulation failed', error);
        alert('Unable to trigger a simulated webhook.');
      }
    });
  };

  // ─── Backend console: Start / Pause / Stop ───
  const attachBackendButtons = () => {
    const startBtn = Array.from(document.querySelectorAll('button')).find(b => normalize(b.textContent).includes('start'));
    const pauseBtn = Array.from(document.querySelectorAll('button')).find(b => normalize(b.textContent).includes('pause'));
    const stopBtn = Array.from(document.querySelectorAll('button')).find(b => normalize(b.textContent).includes('stop') && !normalize(b.textContent).includes('start'));

    if (startBtn) {
      startBtn.classList.remove('opacity-50', 'cursor-not-allowed');
      bindOnce(startBtn, () => {
        _metricsPaused = false;
        populateBootstrapData();
        pollLiveMetrics();
        const orig = startBtn.innerHTML;
        startBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size:16px;font-variation-settings:\'FILL\' 1">sync</span> Syncing…';
        setTimeout(() => { startBtn.innerHTML = orig; }, 1500);
        if (pauseBtn) { pauseBtn.textContent = ''; pauseBtn.innerHTML = '<span class="material-symbols-outlined" style="font-variation-settings:\'FILL\' 1">pause</span> Pause'; }
      });
    }

    if (pauseBtn) {
      bindOnce(pauseBtn, () => {
        _metricsPaused = !_metricsPaused;
        pauseBtn.innerHTML = _metricsPaused
          ? '<span class="material-symbols-outlined" style="font-variation-settings:\'FILL\' 1">play_arrow</span> Resume'
          : '<span class="material-symbols-outlined" style="font-variation-settings:\'FILL\' 1">pause</span> Pause';
      });
    }

    if (stopBtn) {
      bindOnce(stopBtn, () => {
        if (!confirm('Stop all dashboard polling?')) return;
        _metricsPaused = true;
        _allPollingIntervals.forEach(id => clearInterval(id));
        _allPollingIntervals = [];
        const banner = document.createElement('div');
        banner.className = 'fixed top-20 left-1/2 -translate-x-1/2 bg-error text-on-error px-6 py-3 rounded shadow-lg z-50 text-sm';
        banner.textContent = 'Polling stopped — click Start to resume';
        document.body.appendChild(banner);
        setTimeout(() => banner.remove(), 5000);
      });
    }
  };

  // ─── Simulation page toggles ───
  const attachSimulationToggles = () => {
    const allCheckboxes = document.querySelectorAll('input[type="checkbox"]');
    let autoArriveCheckbox = null;
    let priorityCheckbox = null;
    let duplicateCheckbox = null;

    allCheckboxes.forEach((cb) => {
      const label = cb.closest('label') || cb.closest('div');
      const text = (label?.textContent || '').toLowerCase();
      if (text.includes('auto-arrive') || cb.classList.contains('sr-only')) autoArriveCheckbox = cb;
      else if (text.includes('priority')) priorityCheckbox = cb;
      else if (text.includes('duplicate')) duplicateCheckbox = cb;
    });

    if (autoArriveCheckbox) {
      autoArriveCheckbox.addEventListener('change', () => {
        if (autoArriveCheckbox.checked) {
          _autoArriveInterval = setInterval(() => {
            fetch('/webhook/github/simulate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ count: 1 }) }).catch(() => {});
          }, 30000);
          // F4: register so the central Stop button can clear it
          _allPollingIntervals.push(_autoArriveInterval);
        } else {
          clearInterval(_autoArriveInterval);
          _allPollingIntervals = _allPollingIntervals.filter(id => id !== _autoArriveInterval);
          _autoArriveInterval = null;
        }
      });
    }

    if (priorityCheckbox) {
      const saved = localStorage.getItem('chaosInversion') === 'true';
      priorityCheckbox.checked = saved;
      priorityCheckbox.addEventListener('change', () => localStorage.setItem('chaosInversion', String(priorityCheckbox.checked)));
    }

    if (duplicateCheckbox) {
      const saved = localStorage.getItem('chaosDuplicate') === 'true';
      duplicateCheckbox.checked = saved;
      duplicateCheckbox.addEventListener('change', () => localStorage.setItem('chaosDuplicate', String(duplicateCheckbox.checked)));
    }
  };

  // ─── Explorer page ───
  let _explorerFilter = { text: '', status: '' };

  const populateExplorer = async () => {
    const tbody = document.querySelector('[data-ui="explorer-table-body"]');
    if (!tbody) return;
    try {
      const res = await fetch('/ui/queue');
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      const byStatus = data.runs_by_status || {};
      const all = Object.values(byStatus).flat().sort((a, b) => (b.queued_at || '').localeCompare(a.queued_at || ''));

      // Update stat cards
      const total = all.length;
      const completed = (byStatus.COMPLETED || []).length;
      const failed = (byStatus.FAILED || []).length + (byStatus.ABORTED || []).length;
      const inProgress = (byStatus.IN_PROGRESS || []).length;
      const setEl = (sel, v) => { const el = document.querySelector(sel); if (el) el.textContent = String(v); };
      setEl('[data-ui="exp-total"]', total);
      setEl('[data-ui="exp-completed"]', completed);
      setEl('[data-ui="exp-failed"]', failed);
      setEl('[data-ui="exp-inprogress"]', inProgress);

      // Apply filters
      const { text, status } = _explorerFilter;
      const filtered = all.filter((r) => {
        const matchText = !text || [r.repo, r.branch, r.author, String(r.id)].join(' ').toLowerCase().includes(text);
        const matchStatus = !status || r.status === status;
        return matchText && matchStatus;
      });

      // Badge colours
      const badge = (s) => {
        const map = { COMPLETED: 'bg-green-100 text-green-800', IN_PROGRESS: 'bg-amber-100 text-amber-800', FAILED: 'bg-red-100 text-red-800', ABORTED: 'bg-slate-100 text-slate-600', QUEUED: 'bg-blue-100 text-blue-800' };
        return map[s] || 'bg-surface-container text-on-surface';
      };

      tbody.innerHTML = '';
      if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-on-surface-variant">No pipeline runs match the current filter</td></tr>';
        return;
      }
      filtered.forEach((run) => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-surface-variant hover:bg-surface-container-low transition-colors';
        const queuedAt = run.queued_at ? new Date(run.queued_at).toLocaleString() : '—';
        const duration = run.duration_s != null ? `${Math.floor(run.duration_s / 60)}m ${run.duration_s % 60}s` : '—';
        const trigger = (run.triggered_by || 'api').replace('github-push-simulated', 'simulated').replace('github-push', 'github').replace('random-arrival', 'scheduler');
        tr.innerHTML = `
          <td class="px-md py-sm font-code-sm text-code-sm text-primary">#${run.id}</td>
          <td class="px-md py-sm"><div class="font-medium">${run.repo || '—'}</div><div class="text-xs text-on-surface-variant flex items-center gap-1"><span class="material-symbols-outlined text-[12px]">call_split</span>${run.branch || ''}</div></td>
          <td class="px-md py-sm text-on-surface-variant">${run.author || '—'}</td>
          <td class="px-md py-sm"><span class="bg-surface-container px-2 py-0.5 rounded text-xs">${trigger}</span></td>
          <td class="px-md py-sm"><span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${badge(run.status)}">${run.status}</span></td>
          <td class="px-md py-sm text-on-surface-variant text-xs">${queuedAt}</td>
          <td class="px-md py-sm font-code-sm text-xs">${duration}</td>
          <td class="px-md py-sm text-right"><span class="font-code-sm text-xs text-outline">${(run.commit_sha || '').slice(0, 7) || '—'}</span></td>
        `;
        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('populateExplorer failed', e);
    }
  };

  const attachExplorerFilters = () => {
    const searchInput = document.querySelector('[data-ui="exp-search"]');
    const statusSelect = document.querySelector('[data-ui="exp-status-filter"]');
    const clearBtn = document.querySelector('[data-ui="exp-clear"]');
    if (searchInput && !searchInput.dataset.bound) {
      searchInput.dataset.bound = 'true';
      searchInput.addEventListener('input', () => { _explorerFilter.text = searchInput.value.toLowerCase(); populateExplorer(); });
    }
    if (statusSelect && !statusSelect.dataset.bound) {
      statusSelect.dataset.bound = 'true';
      statusSelect.addEventListener('change', () => { _explorerFilter.status = statusSelect.value; populateExplorer(); });
    }
    if (clearBtn) {
      bindOnce(clearBtn, () => {
        _explorerFilter = { text: '', status: '' };
        if (searchInput) searchInput.value = '';
        if (statusSelect) statusSelect.value = '';
        populateExplorer();
      });
    }
  };

  // ─── Settings page ───
  const populateSettings = async () => {
    try {
      const [healthRes, bootstrapRes, workersRes] = await Promise.all([
        fetch('/health'), fetch('/ui/bootstrap'), fetch('/api/workers'),
      ]);
      const health = healthRes.ok ? await healthRes.json() : {};
      const bootstrap = bootstrapRes.ok ? await bootstrapRes.json() : {};
      const workersData = workersRes.ok ? await workersRes.json() : {};

      const set = (sel, v) => { const el = document.querySelector(sel); if (el) el.textContent = String(v ?? '—'); };
      set('[data-ui="st-version"]', health.version);
      set('[data-ui="st-status"]', health.status);
      // Apply status color
      const statusEl = document.querySelector('[data-ui="st-status"]');
      if (statusEl) {
        statusEl.className = `font-code-sm text-code-sm font-semibold ${(health.status || '') === 'ok' ? 'text-green-600' : 'text-error'}`;
      }
      set('[data-ui="st-uptime"]', bootstrap.backend?.uptime);
      set('[data-ui="st-workers-total"]', bootstrap.workers?.total);
      set('[data-ui="st-workers-busy"]', bootstrap.workers?.busy);
      set('[data-ui="st-chaos-level"]', bootstrap.health?.chaos_level);
      set('[data-ui="st-queue-total"]', bootstrap.queue?.total);

      const workerList = workersData.workers || [];
      const langCount = {};
      workerList.forEach((w) => { langCount[w.language || 'unknown'] = (langCount[w.language || 'unknown'] || 0) + 1; });
      const langBody = document.querySelector('[data-ui="st-lang-body"]');
      if (langBody) {
        langBody.innerHTML = Object.entries(langCount).map(([lang, count]) => `
          <tr class="border-b border-surface-variant">
            <td class="py-2 px-md font-code-sm text-code-sm">${lang}</td>
            <td class="py-2 px-md text-on-surface-variant">${count} worker${count > 1 ? 's' : ''}</td>
            <td class="py-2 px-md"><div class="h-2 bg-surface-container rounded-full overflow-hidden"><div class="h-full bg-primary" style="width:${Math.round(count / workerList.length * 100)}%"></div></div></td>
          </tr>
        `).join('') || '<tr><td colspan="3" class="py-4 text-center text-on-surface-variant">No workers</td></tr>';
      }

      const ngrokInput = document.querySelector('[data-ui="st-ngrok-url"]');
      if (ngrokInput) ngrokInput.value = window.location.origin;

      // Env var status inference
      const envBody = document.querySelector('[data-ui="st-env-body"]');
      const envVars = [
        { name: 'DATABASE_URL', inferred: bootstrap.backend?.status === 'RUNNING', desc: 'PostgreSQL connection string' },
        { name: 'REDIS_URL', inferred: bootstrap.backend?.status === 'RUNNING', desc: 'Celery broker URL' },
        { name: 'JENKINS_URL', inferred: false, desc: 'Jenkins base URL for log fetching' },
        { name: 'JENKINS_USER', inferred: false, desc: 'Jenkins username' },
        { name: 'JENKINS_TOKEN', inferred: false, desc: 'Jenkins API token' },
        { name: 'GROQ_API_KEY', inferred: false, desc: 'Primary LLM (Groq)' },
        { name: 'ANTHROPIC_API_KEY', inferred: false, desc: 'Secondary LLM fallback' },
        { name: 'SLACK_BOT_TOKEN', inferred: false, desc: 'Slack alert delivery' },
        { name: 'GITHUB_WEBHOOK_SECRET', inferred: false, desc: 'HMAC secret for GitHub webhooks' },
        { name: 'NGROK_URL', inferred: false, desc: 'Public tunnel URL for webhooks' },
      ];
      if (envBody) {
        envBody.innerHTML = envVars.map((v) => `
          <tr class="border-b border-surface-variant hover:bg-surface-container-low transition-colors">
            <td class="py-2 px-md font-code-sm text-code-sm">${v.name}</td>
            <td class="py-2 px-md"><span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${v.inferred ? 'bg-green-100 text-green-800' : 'bg-surface-container text-on-surface-variant'}">${v.inferred ? '✓ Set' : '— Not detected'}</span></td>
            <td class="py-2 px-md text-on-surface-variant text-xs">${v.desc}</td>
          </tr>
        `).join('');
      }

      // Dashboard prefs
      const pollInput = document.querySelector('[data-ui="st-poll-interval"]');
      const pollDisplay = document.querySelector('[data-ui="st-poll-display"]');
      if (pollInput) {
        const saved = localStorage.getItem('schedulerPollMs') || '5000';
        pollInput.value = saved;
        if (pollDisplay) pollDisplay.textContent = saved + 'ms';
        if (!pollInput.dataset.bound) {
          pollInput.dataset.bound = 'true';
          pollInput.addEventListener('input', () => {
            localStorage.setItem('schedulerPollMs', pollInput.value);
            if (pollDisplay) pollDisplay.textContent = pollInput.value + 'ms';
          });
        }
      }

      // Fetch live routing mode from backend (overrides stale localStorage value)
      try {
        const modeRes = await fetch('/ui/scheduler/mode');
        if (modeRes.ok) {
          const modeData = await modeRes.json();
          const routingEl = document.getElementById('st-routing-mode');
          const fallbackEl = document.getElementById('st-fallback-policy');
          if (routingEl) routingEl.textContent = modeData.mode || 'Priority';
          localStorage.setItem('schedulerMode', modeData.mode || 'Priority');
          if (fallbackEl && !fallbackEl.textContent.trim().replace('—', '')) {
            fallbackEl.textContent = localStorage.getItem('workerFallbackPolicy') || 'Queue if no match';
          }
        }
      } catch (_) { /* ignore, localStorage fallback already set in inline script */ }
    } catch (e) {
      console.error('populateSettings failed', e);
    }
  };

  const init = () => {
    rewriteNavigation();
    attachRefreshButtons();
    attachViewLogsButtons();
    attachQuickActionButtons();
    attachQueueActions();
    attachHeaderIconButtons();
    // Use fixed webhook handler that reads live form values; skip old hardcoded one
    if (currentPath().startsWith('/webhooks')) {
      attachWebhookActionsFixed();
      attachWebhookPageActions();
    } else {
      attachWebhookActions();
    }
    attachSimulationActions();

    if (currentPath().startsWith('/queue')) {
      if (document.querySelector('[data-ui="queue-table-body"]')) {
        populateQueueTable();
        populateQueueMetrics();
        attachQueueSearch();
        const qInterval = setInterval(() => {
          if (document.querySelector('[data-ui="queue-table-body"]')) { populateQueueTable(); populateQueueMetrics(); }
          else clearInterval(qInterval);
        }, 5000);
        _allPollingIntervals.push(qInterval);
      }
    }

    if (currentPath().startsWith('/scheduler')) {
      if (document.querySelector('[data-ui="kanban-queued-list"]')) {
        populateSchedulerKanban();
        const ms = Number(localStorage.getItem('schedulerPollMs') || 5000);
        _schedulerKanbanInterval = setInterval(() => {
          if (document.querySelector('[data-ui="kanban-queued-list"]')) populateSchedulerKanban();
          else clearInterval(_schedulerKanbanInterval);
        }, ms);
        _allPollingIntervals.push(_schedulerKanbanInterval);
        attachSchedulerControls();
      }
    }

    if (currentPath().startsWith('/workers')) {
      if (document.querySelector('[data-ui="workers-list"]')) {
        populateWorkers();
        attachWorkerControls();
        const wInterval = setInterval(() => {
          if (document.querySelector('[data-ui="workers-list"]')) populateWorkers();
          else clearInterval(wInterval);
        }, 5000);
        _allPollingIntervals.push(wInterval);
      }
    }

    if (currentPath().startsWith('/webhooks')) {
      if (document.querySelector('[data-ui="webhook-events-body"]')) {
        populateWebhookEvents();
        const hInterval = setInterval(() => {
          if (document.querySelector('[data-ui="webhook-events-body"]')) populateWebhookEvents();
          else clearInterval(hInterval);
        }, 5000);
        _allPollingIntervals.push(hInterval);
      }
    }

    if (currentPath().startsWith('/backend')) {
      attachBackendButtons();
    }

    if (currentPath().startsWith('/simulation')) {
      attachSimulationToggles();
      const simInterval = setInterval(() => {
        if (document.querySelector('[data-ui="simulation-live-log"]')) populateBootstrapData();
        else clearInterval(simInterval);
      }, 10000);
      _allPollingIntervals.push(simInterval);
    }

    if (currentPath().startsWith('/explorer')) {
      populateExplorer();
      attachExplorerFilters();
      const eInterval = setInterval(() => {
        if (document.querySelector('[data-ui="explorer-table-body"]')) populateExplorer();
        else clearInterval(eInterval);
      }, 5000);
      _allPollingIntervals.push(eInterval);
    }

    if (currentPath().startsWith('/settings')) {
      populateSettings();
    }

    // Populate global bootstrap/dashboard data when present
    try {
      populateBootstrapData();
      const bInterval = setInterval(() => {
        if (document.querySelector('[data-ui="last-updated"]')) populateBootstrapData();
        else clearInterval(bInterval);
      }, 10000);
      _allPollingIntervals.push(bInterval);
    } catch (e) { /* ignore */ }

    // Start polling live metrics every 5 seconds
    try {
      const origPollLiveMetrics = pollLiveMetrics;
      const guardedPoll = () => { if (!_metricsPaused) origPollLiveMetrics(); };
      guardedPoll();
      const metricsInterval = setInterval(guardedPoll, 5000);
      _allPollingIntervals.push(metricsInterval);
    } catch (e) {
      console.warn('Live metrics polling not available', e);
    }
  };

  window._populateSettings = populateSettings;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
