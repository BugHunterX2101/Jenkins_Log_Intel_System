(() => {
  const normalize = (value = "") =>
    value.replace(/[\u200B-\u200D\uFEFF]/g, "").replace(/\s+/g, " ").trim().toLowerCase();

  const currentPath = () => window.location.pathname.replace(/\/$/, "") || "/";

  const resolveLinkTarget = (text) => {
    const label = normalize(text);
    if (label.includes("quick actions")) return "/webhooks";
    if (label.includes("refresh system")) return null;
    if (label.includes("dashboard") || label.includes("overview")) return "/";
    if (label.includes("webhooks")) return "/webhooks";
    if (label.includes("console") || label.includes("backend")) return "/backend";
    if (label.includes("explorer") || label.includes("logs")) return "/explorer";
    if (label.includes("queue")) return "/queue";
    if (label.includes("scheduler")) return "/scheduler";
    if (label.includes("workers")) return "/workers";
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

  const showToast = (message, isError = false, durationMs = 3000) => {
    const toast = document.createElement("div");
    toast.className = isError
      ? "fixed bottom-6 right-6 bg-error text-on-error px-4 py-2 rounded shadow-lg text-sm z-50"
      : "fixed bottom-6 right-6 bg-on-surface text-surface px-4 py-2 rounded shadow-lg text-sm z-50 flex items-center gap-2";
    if (typeof message === "string") {
      toast.textContent = message;
    } else {
      toast.appendChild(message);
    }
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), durationMs);
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
          return;
        }
        goTo("/webhooks");
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

  const attachWebhookActions = () => {};

  const populateQueueChart = async () => {
    const svg = document.getElementById('queue-depth-svg');
    const empty = document.getElementById('queue-depth-empty');
    if (!svg) return;
    try {
      const res = await fetch('/ui/metrics/history?period_minutes=60');
      if (!res.ok) return;
      const result = await res.json();
      const samples = (result.samples || []).slice(-40);

      if (!samples.length) {
        svg.innerHTML = '';
        if (empty) { empty.classList.remove('hidden'); empty.style.display = 'flex'; }
        return;
      }
      if (empty) { empty.classList.add('hidden'); empty.style.display = ''; }

      const values = samples.map(s => Number(s.queue_total || 0));
      const maxVal = Math.max(...values, 1);
      const pts = values.map((v, i) => {
        const x = (i / (values.length - 1)) * 100;
        const y = 100 - (v / maxVal) * 90;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(' ');

      svg.innerHTML = `
        <defs>
          <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#0058be" stop-opacity="0.3"/>
            <stop offset="100%" stop-color="#0058be" stop-opacity="0.02"/>
          </linearGradient>
        </defs>
        <polygon fill="url(#chartGrad)" points="0,100 ${pts} 100,100"/>
        <polyline fill="none" points="${pts}" stroke="#0058be" stroke-width="2" stroke-linejoin="round"/>
      `;
    } catch (e) {
      console.warn('populateQueueChart failed', e);
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
      // F6: show active queue depth only (not historical completed/failed count)
      if (totalEl) totalEl.textContent = String(active.length);

      const now = Date.now();
      const waitTimes = active
        .filter(r => r.queued_at)
        .map(r => Math.max(0, Math.floor((now - new Date(r.queued_at).getTime()) / 1000)));

      const avgWaitEl = document.querySelector('[data-ui="avg-wait-queue"]');
      if (avgWaitEl) {
        if (waitTimes.length) {
          const avg = (waitTimes.reduce((a, b) => a + b, 0) / waitTimes.length).toFixed(1);
          avgWaitEl.innerHTML = `${avg}<span class="text-headline-sm font-headline-sm text-on-surface-variant ml-1">sec</span>`;
        } else {
          avgWaitEl.innerHTML = `0<span class="text-headline-sm font-headline-sm text-on-surface-variant ml-1">sec</span>`;
        }
      }

      const longestEl = document.querySelector('[data-ui="longest-wait"]');
      if (longestEl) {
        if (waitTimes.length) {
          const max = Math.max(...waitTimes);
          longestEl.innerHTML = `${max}<span class="text-headline-sm font-headline-sm text-on-surface-variant ml-1">sec</span>`;
        } else {
          longestEl.innerHTML = `0<span class="text-headline-sm font-headline-sm text-on-surface-variant ml-1">sec</span>`;
        }
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
          const br = run.branch || '';
          let priority = 'P6 (Normal)';
          let priorityClass = 'bg-surface-container-highest text-on-surface-variant';
          if (br.startsWith('hotfix/')) { priority = 'P1 (Hotfix)'; priorityClass = 'bg-error text-on-error font-bold'; }
          else if (br === 'main' || br === 'master') { priority = 'P2 (Main)'; priorityClass = 'bg-primary-fixed text-on-primary-fixed font-bold'; }
          else if (br.startsWith('release/')) { priority = 'P3 (Release)'; priorityClass = 'bg-primary text-on-primary'; }
          else if (br === 'develop') { priority = 'P4 (Develop)'; priorityClass = 'bg-tertiary text-on-tertiary'; }
          else if (br.startsWith('feature/')) { priority = 'P5 (Feature)'; priorityClass = 'bg-secondary text-on-secondary'; }
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
          const cancelBtn = row.querySelector('button[title="Cancel Job"]');
          if (cancelBtn) {
            cancelBtn.addEventListener('click', async () => {
              cancelBtn.disabled = true;
              try {
                const res = await fetch(`/ui/queue/${run.id}/cancel`, { method: 'POST' });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                showToast(`Job #J-${run.id} cancelled`, false, 2500);
                populateQueueTable();
                populateQueueMetrics();
              } catch (err) {
                showToast(`Failed to cancel job #J-${run.id}`, true, 2500);
                cancelBtn.disabled = false;
              }
            });
          }
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
    const jobRows     = document.querySelector('[data-ui="queue-db-job-rows"]');
    const execRows    = document.querySelector('[data-ui="queue-db-exec-rows"]');
    const workerRows  = document.querySelector('[data-ui="queue-db-worker-rows"]');
    const webhookRows = document.querySelector('[data-ui="queue-db-webhook-rows"]');

    const findRows = (name) => {
      const t = (database.tables || []).find(t => t.name === name);
      return Number(t?.rows || 0).toLocaleString();
    };

    if (totalRecords) totalRecords.textContent = Number(database.total_records || 0).toLocaleString();
    if (jobRows)     jobRows.textContent     = `${findRows('pipeline_runs')} rows`;
    if (execRows)    execRows.textContent    = `${findRows('stage_executions')} rows`;
    if (workerRows)  workerRows.textContent  = `${findRows('build_events')} rows`;
    if (webhookRows) webhookRows.textContent = `${findRows('workers')} rows`;
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
      const tn = Array.from(status.childNodes).find(n => n.nodeType === 3 && n.textContent.trim());
      if (tn) tn.textContent = ` ${backend.status || 'RUNNING'}`;
    }
    if (uptime) uptime.textContent = backend.uptime || '-';
    if (technology) technology.textContent = backend.technology || 'FastAPI / Python';
    const techIcon = document.querySelector('[data-ui="backend-technology-icon"]');
    if (techIcon) {
      const t = (backend.technology || '').toLowerCase();
      techIcon.textContent = t.includes('node') || t.includes('javascript') ? 'javascript' : 'code';
    }
    if (port) port.textContent = backend.port || '8000';
    if (memory) {
      const used = Number(backend.memory_used || 0);
      const total = Number(backend.memory_total || 0);
      const pct = total > 0 ? Math.round((used / total) * 100) : 0;
      memory.innerHTML = `${formatBytes(used)} <span class="text-outline font-body-md text-body-md">/ ${formatBytes(total)}</span>`;
      if (memoryBar) memoryBar.style.setProperty('--bar-w', `${pct}%`);
    }

    const cpu = document.querySelector('[data-ui="backend-cpu"]');
    if (cpu) cpu.textContent = `${Math.round(backend.cpu_percent || 0)}%`;

    const buildEvents = data.build_events || [];
    const latest = buildEvents[0];
    const alertBar = document.querySelector('[data-ui="backend-alert-bar"]');
    if (alertBar) {
      if (latest) {
        alertBar.classList.remove('hidden');
        alertBar.classList.add('flex');
      } else {
        alertBar.classList.remove('flex');
        alertBar.classList.add('hidden');
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
      const feed = data.backend_request_feed || [];
      if (!feed.length) {
        requestBody.innerHTML = '<tr><td colspan="5" class="py-6 text-center text-on-surface-variant text-sm">No requests recorded yet — make any API call to start the feed</td></tr>';
      } else {
        feed.forEach((request) => {
          const tr = document.createElement('tr');
          const status = String(request.status || '200');
          const statusColor = status.startsWith('5') ? 'text-error' : status.startsWith('4') ? 'text-tertiary' : 'text-primary';
          const latency = request.latency_ms != null ? `${request.latency_ms}ms` : '-';
          tr.className = 'hover:bg-surface-container-low transition-colors';
          tr.innerHTML = `
            <td class="py-2 px-md text-outline font-code-sm text-code-sm">${request.id || '-'}</td>
            <td class="py-2 px-md text-on-surface-variant">${request.timestamp ? new Date(request.timestamp).toLocaleTimeString() : '-'}</td>
            <td class="py-2 px-md"><span class="bg-surface-container text-on-surface-variant px-1.5 py-0.5 rounded border border-outline-variant">${request.method || 'GET'}</span></td>
            <td class="py-2 px-md text-on-surface font-code-sm text-code-sm">${request.route || '-'}</td>
            <td class="py-2 px-md text-right flex items-center justify-end gap-2"><span class="text-on-surface-variant text-xs">${latency}</span><span class="${statusColor} font-bold">${status}</span></td>
          `;
          requestBody.appendChild(tr);
        });
      }
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
            <div class="absolute left-0 top-0 h-full bg-secondary-fixed-dim rounded opacity-80 border border-outline-variant bar-fill" style="--bar-w:${Math.max(10, 100 - load)}%" title="${currentJob} (Queued)"></div>
            <div class="absolute right-0 top-0 h-full bg-primary rounded border border-primary-container shadow-sm bar-fill" style="--bar-w:${load}%" title="${currentJob} (Running)"></div>
          </div>
        `;
        timelineRows.appendChild(row);
      });
    }
  };

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
        let capsList = [];
        try { capsList = JSON.parse(merged.capabilities || '[]'); } catch (_e) { capsList = []; }
        const capsHtml = capsList.length
          ? `<div class="flex flex-wrap gap-xs mt-xs">${capsList.map(c => `<span class="bg-surface-container-high px-1.5 py-0.5 rounded text-[9px] font-label-md text-on-surface-variant">${c}</span>`).join('')}</div>`
          : '';
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
              ${capsHtml}
              ${currentJobRow}
            </div>
            ${statusBadge}
          </div>
          <div class="mt-sm ${isBusy ? '' : 'opacity-40'}">
            <div class="flex justify-between font-label-md text-label-md text-on-surface-variant mb-1">
              <span>${isBusy ? 'Load' : 'Awaiting assignment'}</span>
              <span>${isBusy ? pct + '%' : '--'}</span>
            </div>
            <div class="h-2 bg-surface-container rounded-full overflow-hidden"><div class="h-full bg-primary bar-fill" style="--bar-w:${pct}%"></div></div>
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
              <div class="absolute left-0 top-0 h-full bg-secondary-fixed-dim rounded opacity-80 bar-fill" style="--bar-w:${Math.max(5, 100 - load)}%" title="Idle"></div>
              ${isBusy ? `<div class="absolute right-0 top-0 h-full bg-primary rounded bar-fill" style="--bar-w:${load}%" title="${w.current_job || 'running'}"></div>` : ''}
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

  // ─── Repositories Overview (dashboard) ───────────────────────────────────────
  const _priorityBadgeClass = (prio) => {
    const map = {
      1: 'bg-red-600 text-white',
      2: 'bg-blue-600 text-white',
      3: 'bg-violet-600 text-white',
      4: 'bg-amber-500 text-white',
      5: 'bg-teal-500 text-white',
      6: 'bg-slate-400 text-white',
    };
    return map[prio] || 'bg-slate-400 text-white';
  };

  const populateRepositories = async () => {
    const grid = document.querySelector('[data-ui="repos-grid"]');
    if (!grid) return;
    try {
      const res = await fetch('/ui/repositories');
      if (!res.ok) throw new Error('Failed to fetch repositories');
      const data = await res.json();
      const repos = data.repositories || [];

      // Update count badge
      const countEl = document.querySelector('[data-ui="repos-count"]');
      if (countEl) countEl.textContent = `${repos.length} repo${repos.length !== 1 ? 's' : ''}`;

      grid.innerHTML = '';
      if (!repos.length) {
        grid.innerHTML = '<div class="col-span-full text-center text-on-surface-variant text-sm py-8">No repositories found. Push a real change to a GitHub repo to get started.</div>';
        return;
      }

      repos.forEach((repo) => {
        const card = document.createElement('div');
        card.className = 'bg-surface-container-low border border-outline-variant rounded-xl p-md shadow-sm hover:shadow-md transition-shadow';

        const branchRows = (repo.branches || []).map((b) => {
          const badgeCls = _priorityBadgeClass(b.priority);
          const c = b.counts || {};
          return `
            <div class="flex items-center justify-between py-1.5 border-b border-outline-variant/40 last:border-0">
              <div class="flex items-center gap-2 min-w-0">
                <span class="inline-block px-1.5 py-0.5 ${badgeCls} font-label-md text-[9px] rounded flex-shrink-0">${b.priority_label}</span>
                <span class="font-code-sm text-code-sm text-on-surface truncate flex items-center gap-1">
                  <span class="material-symbols-outlined text-[12px] text-outline">call_split</span>
                  ${b.branch}
                </span>
              </div>
              <div class="flex items-center gap-1.5 flex-shrink-0 ml-2">
                ${c.QUEUED ? `<span class="px-1 py-0.5 bg-blue-100 text-blue-800 font-label-md text-[9px] rounded" title="Queued">${c.QUEUED}Q</span>` : ''}
                ${c.IN_PROGRESS ? `<span class="px-1 py-0.5 bg-amber-100 text-amber-800 font-label-md text-[9px] rounded" title="Running">${c.IN_PROGRESS}R</span>` : ''}
                ${c.COMPLETED ? `<span class="px-1 py-0.5 bg-green-100 text-green-800 font-label-md text-[9px] rounded" title="Completed">${c.COMPLETED}✓</span>` : ''}
                ${c.FAILED ? `<span class="px-1 py-0.5 bg-red-100 text-red-800 font-label-md text-[9px] rounded" title="Failed">${c.FAILED}✗</span>` : ''}
              </div>
            </div>
          `;
        }).join('');

        card.innerHTML = `
          <div class="flex items-start justify-between mb-sm">
            <div class="flex items-center gap-2">
              <span class="w-8 h-8 rounded-lg bg-surface-container-high flex items-center justify-center text-primary flex-shrink-0">
                <span class="material-symbols-outlined text-[16px]">folder_code</span>
              </span>
              <div>
                <div class="font-headline-sm text-[14px] text-on-surface font-semibold">${repo.repo_name}</div>
                <div class="font-code-sm text-[10px] text-outline truncate max-w-[180px]">${repo.repo_url}</div>
              </div>
            </div>
            <span class="bg-surface-container text-on-surface-variant font-code-sm text-[11px] px-2 py-0.5 rounded-full flex-shrink-0">${repo.total_runs} runs</span>
          </div>
          <div class="flex flex-col gap-0">
            ${branchRows || '<div class="text-on-surface-variant text-xs py-2">No branches</div>'}
          </div>
        `;
        grid.appendChild(card);
      });
    } catch (err) {
      console.error('populateRepositories failed', err);
      const grid2 = document.querySelector('[data-ui="repos-grid"]');
      if (grid2) grid2.innerHTML = '<div class="col-span-full text-center text-on-surface-variant text-sm py-6">Failed to load repositories.</div>';
    }
  };

  // ─── Priority Queue (scheduler page) ─────────────────────────────────────────
  const populatePriorityQueue = async () => {
    const tbody = document.querySelector('[data-ui="priority-queue-list"]');
    if (!tbody) return;
    try {
      const res = await fetch('/ui/priority-queue');
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();

      // Update mode badge
      const modeBadge = document.querySelector('[data-ui="pq-mode-badge"]');
      if (modeBadge) modeBadge.textContent = data.mode || 'Priority';
      const totalEl = document.querySelector('[data-ui="pq-total"]');
      if (totalEl) totalEl.textContent = `${data.total || 0} queued`;

      tbody.innerHTML = '';
      const jobs = data.jobs || [];
      if (!jobs.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="py-6 text-center text-on-surface-variant text-sm">Queue is empty — no jobs waiting</td></tr>';
        return;
      }
      jobs.forEach((job) => {
        const tr = document.createElement('tr');
        tr.className = 'border-b border-surface-variant hover:bg-surface-container-low transition-colors';
        const waitLabel = job.wait_seconds > 3600
          ? `${Math.floor(job.wait_seconds / 3600)}h ${Math.floor((job.wait_seconds % 3600) / 60)}m`
          : job.wait_seconds > 60
          ? `${Math.floor(job.wait_seconds / 60)}m ${job.wait_seconds % 60}s`
          : `${job.wait_seconds}s`;
        tr.innerHTML = `
          <td class="py-2 px-md font-bold text-on-surface-variant">#${job.rank}</td>
          <td class="py-2 px-md"><span class="px-2 py-0.5 ${job.priority_color} font-label-md text-[10px] rounded">${job.priority_label}</span></td>
          <td class="py-2 px-md font-code-sm text-code-sm text-on-surface">${job.repo}</td>
          <td class="py-2 px-md">
            <span class="flex items-center gap-1 font-code-sm text-code-sm">
              <span class="material-symbols-outlined text-[12px] text-outline">call_split</span>
              ${job.branch}
            </span>
          </td>
          <td class="py-2 px-md text-on-surface-variant font-code-sm">${job.author}</td>
          <td class="py-2 px-md text-right font-code-sm text-on-surface-variant">${waitLabel}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.error('populatePriorityQueue failed', err);
    }
  };

  // ─── Scheduler mode buttons ───────────────────────────────────────────────────
  const _MODES = ['FIFO', 'Priority', 'Load-Balanced'];

  const _highlightModeBtn = (activeMode) => {
    document.querySelectorAll('[data-scheduler-mode]').forEach((btn) => {
      const isActive = btn.dataset.schedulerMode === activeMode;
      btn.classList.toggle('bg-surface-container-lowest', isActive);
      btn.classList.toggle('text-on-surface', isActive);
      btn.classList.toggle('shadow-sm', isActive);
      btn.classList.toggle('border', isActive);
      btn.classList.toggle('border-outline-variant/30', isActive);
      btn.classList.toggle('text-on-surface-variant', !isActive);
    });
    // Also update the pq-mode-badge if on scheduler page
    const badge = document.querySelector('[data-ui="pq-mode-badge"]');
    if (badge) badge.textContent = activeMode;
  };

  const attachSchedulerModeButtons = () => {
    // Stamp data-scheduler-mode onto the three mode buttons (FIFO / Priority / Load-Balanced)
    const modeContainer = document.querySelector('.flex.bg-surface-container.rounded-lg.p-1');
    if (modeContainer) {
      const btns = modeContainer.querySelectorAll('button');
      btns.forEach((btn, i) => {
        const mode = _MODES[i];
        if (mode) btn.dataset.schedulerMode = mode;
      });
    }

    // Fetch current mode from backend and highlight
    fetch('/ui/scheduler/mode')
      .then(r => r.json())
      .then(d => _highlightModeBtn(d.mode || 'Priority'))
      .catch(() => _highlightModeBtn('Priority'));

    // Attach click handlers
    document.querySelectorAll('[data-scheduler-mode]').forEach((btn) => {
      bindOnce(btn, async () => {
        const mode = btn.dataset.schedulerMode;
        try {
          const res = await fetch('/ui/scheduler/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode }),
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          _highlightModeBtn(mode);
          // Refresh the priority queue to reflect new ordering
          populatePriorityQueue();
          const modeMsg = document.createDocumentFragment();
          const modeIcon = document.createElement('span');
          modeIcon.className = 'material-symbols-outlined text-[16px]';
          modeIcon.textContent = 'check_circle';
          modeMsg.appendChild(modeIcon);
          modeMsg.appendChild(document.createTextNode(` Scheduler mode set to `));
          const b = document.createElement('strong');
          b.textContent = mode;
          modeMsg.appendChild(b);
          showToast(modeMsg, false, 2500);
        } catch (err) {
          console.error('Failed to set scheduler mode', err);
        }
      });
    });
  };

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

      // System health icon — green when ok, red otherwise
      const healthIcon = document.querySelector('[data-ui="health-status-icon"]');
      if (healthIcon) {
        const ok = (data.health?.status === 'ok');
        healthIcon.textContent = ok ? 'check_circle' : 'error';
        healthIcon.className = `material-symbols-outlined ${ok ? 'text-green-600 bg-green-50' : 'text-error bg-error-container'} rounded-full p-1 text-[18px]`;
      }

      // Queue counts — show active depth (QUEUED + IN_PROGRESS), not historical total
      const qDepth = document.querySelector('[data-ui="queue-depth"]');
      if (qDepth && data.queue) {
        const activeDepth = (data.queue.queued || 0) + (data.queue.in_progress || 0);
        qDepth.textContent = String(activeDepth);
      }
      const topologyCount = document.querySelector('[data-ui="topology-queue-count"]');
      if (topologyCount && data.queue && typeof data.queue.queued !== 'undefined') {
        topologyCount.textContent = String(data.queue.queued);
      }
      const avgWait = document.querySelector('[data-ui="avg-wait"]');
      if (avgWait && data.queue && typeof data.queue.avg_wait_seconds !== 'undefined') {
        avgWait.textContent = `Avg wait: ${Number(data.queue.avg_wait_seconds).toFixed(1)}s`;
      }

      // System uptime — show actual server uptime (backend.uptime), falling back
      // to the SLA percentage if uptime isn't available
      const uptime = document.querySelector('[data-ui="system-uptime"]');
      if (uptime) {
        uptime.textContent = data.backend?.uptime || data.health?.uptime_percentage || '—';
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
        if (workerBar) workerBar.style.setProperty('--bar-w', `${pct}%`);
        if (workerNodeCount) workerNodeCount.textContent = `${busy} of ${total} nodes active`;
      }
      // initialize page-specific panels if present
      try { renderQueueDatabaseState(data); } catch (err) { console.warn('renderQueueDatabaseState failed', err); }
      try { renderBackendPanel(data); } catch (err) { console.warn('renderBackendPanel failed', err); }
      try { renderWorkersPanels(data); } catch (err) { console.warn('renderWorkersPanels failed', err); }
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
          memBar.style.setProperty('--bar-w', `${pct}%`);
        }
      }

      // F3: update CPU element now that it exists in backend.html
      const cpuEl = document.querySelector('[data-ui="backend-cpu"]');
      if (cpuEl) cpuEl.textContent = `${(data.cpu_percent || 0).toFixed(1)}%`;

      const chaosLevelEl = document.querySelector('[data-ui="chaos-level"]');
      if (chaosLevelEl) chaosLevelEl.textContent = data.chaos_level || '';

    } catch (error) {
      console.warn('Live metrics polling failed', error);
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
      container.innerHTML = `<div class="text-error">Error loading analysis: ${error.message}</div>`;
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
    if (!searchInput || searchInput.dataset.bound) return;
    searchInput.dataset.bound = 'true';
    let statusFilter = false;
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.toLowerCase();
      document.querySelectorAll('[data-ui="queue-table-body"] tr').forEach((row) => {
        const text = row.textContent.toLowerCase();
        row.classList.toggle('hidden', !(!q || text.includes(q)));
      });
    });
    const filterButton = Array.from(document.querySelectorAll('button')).find(b => b.querySelector('.material-symbols-outlined')?.textContent?.trim() === 'filter_list');
    if (filterButton) {
      bindOnce(filterButton, () => {
        statusFilter = !statusFilter;
        filterButton.classList.toggle('text-primary', statusFilter);
        document.querySelectorAll('[data-ui="queue-table-body"] tr').forEach((row) => {
          if (!statusFilter) { row.classList.remove('hidden'); return; }
          const isQueued = row.textContent.includes('QUEUED');
          row.classList.toggle('hidden', !isQueued);
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

    const slider = document.querySelector('[data-ui="scheduler-poll-slider"]') || document.querySelector('input[type="range"][min="100"][max="5000"]');
    const sliderLabel = document.querySelector('[data-ui="scheduler-poll-label"]') || slider?.closest('div')?.querySelector('span');
    if (slider) {
      const saved = localStorage.getItem('schedulerPollMs') || '5000';
      slider.value = saved;
      if (sliderLabel) sliderLabel.textContent = saved + 'ms';
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
          if (kanbanSection) kanbanSection.classList.add('opacity-40');
        } else {
          const ms = Number(localStorage.getItem('schedulerPollMs') || 5000);
          _schedulerKanbanInterval = setInterval(() => {
            if (document.querySelector('[data-ui="kanban-queued-list"]')) populateSchedulerKanban();
            else clearInterval(_schedulerKanbanInterval);
          }, ms);
          _allPollingIntervals.push(_schedulerKanbanInterval);
          if (kanbanSection) kanbanSection.classList.remove('opacity-40');
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
          if (el) el.closest('.flex-col')?.classList.toggle('hidden', runningOnly);
        });
      });
    }

    // "View Full Logs" button in Decision Log footer → Explorer page
    const viewLogsBtn = Array.from(document.querySelectorAll('button')).find(
      b => normalize(b.textContent).includes('view full logs')
    );
    if (viewLogsBtn) bindOnce(viewLogsBtn, () => goTo('/explorer'));
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
        showToast('Policy saved', false, 2000);
      });
    }
  };

  // ─── Webhooks page: copy URL, visibility toggle ───
  const attachWebhookPageActions = () => {
    const webhookUrl = window.location.origin + '/github-webhook/';
    document.querySelectorAll('[data-ui="ngrok-url"]').forEach((el) => {
      const isInput = el.tagName === 'INPUT';
      if (isInput && el.value.includes('[configure')) el.value = webhookUrl;
      if (!isInput && el.textContent.includes('[configure')) el.textContent = webhookUrl;
    });
    const ngrokInput = document.querySelector('input[data-ui="ngrok-url"]');

    const whSecretInput = document.querySelector('input[type="password"]');
    if (whSecretInput && !whSecretInput.value) {
      fetch('/ui/webhook-config')
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (d && whSecretInput && !whSecretInput.value) {
            whSecretInput.value = d.secret_hint || '';
            whSecretInput.placeholder = d.secret_configured
              ? 'Secret configured — copy hint to use in GitHub'
              : 'Not configured — set GITHUB_WEBHOOK_SECRET in .env';
          }
        })
        .catch(() => {});
    }

    const copyBtn = Array.from(document.querySelectorAll('button')).find(b => normalize(b.textContent).includes('copy url'));
    if (copyBtn && ngrokInput) {
      bindOnce(copyBtn, () => {
        navigator.clipboard.writeText(ngrokInput.value).catch(() => {});
        const orig = copyBtn.innerHTML;
        copyBtn.innerHTML = '<span class="material-symbols-outlined text-[16px]">check</span> Copied!';
        setTimeout(() => { copyBtn.innerHTML = orig; }, 1500);
      });
    }

    const secretInput = document.querySelector('input[type="password"]');
    const visBtn = secretInput?.closest('div')?.querySelector('button[type="button"]');
    if (visBtn && secretInput) {
      bindOnce(visBtn, () => {
        const isHidden = secretInput.type === 'password';
        secretInput.type = isHidden ? 'text' : 'password';
        const icon = visBtn.querySelector('.material-symbols-outlined');
        if (icon) icon.textContent = isHidden ? 'visibility_off' : 'visibility';
      });
    }
  };


  // ─── Backend console: Start / Pause / Stop / View All ───
  const attachBackendButtons = () => {
    // "View All" in the Endpoint Health Monitor header → open FastAPI interactive docs
    const viewAllBtn = Array.from(document.querySelectorAll('button')).find(b => normalize(b.textContent) === 'view all');
    if (viewAllBtn) bindOnce(viewAllBtn, () => window.open('/docs', '_blank'));

    // "Load More History" in the Live Request Feed footer → re-fetch bootstrap to refresh feed
    const loadMoreBtn = Array.from(document.querySelectorAll('button')).find(
      b => normalize(b.textContent).includes('load more history')
    );
    if (loadMoreBtn) {
      bindOnce(loadMoreBtn, async () => {
        loadMoreBtn.textContent = 'Refreshing…';
        await populateBootstrapData();
        loadMoreBtn.textContent = 'Load More History';
      });
    }

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
        startBtn.innerHTML = '<span class="material-symbols-outlined text-[16px] icon-filled">sync</span> Syncing…';
        setTimeout(() => { startBtn.innerHTML = orig; }, 1500);
        if (pauseBtn) { pauseBtn.textContent = ''; pauseBtn.innerHTML = '<span class="material-symbols-outlined icon-filled">pause</span> Pause'; }
      });
    }

    if (pauseBtn) {
      bindOnce(pauseBtn, () => {
        _metricsPaused = !_metricsPaused;
        pauseBtn.innerHTML = _metricsPaused
          ? '<span class="material-symbols-outlined icon-filled">play_arrow</span> Resume'
          : '<span class="material-symbols-outlined icon-filled">pause</span> Pause';
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
        const matchStatus = !status || String(r.status || '').toUpperCase() === status;
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
        const trigger = (run.triggered_by || 'api')
          .replace('github-push', 'github')
          .replace('github-pull_request', 'github-pr')
          .replace('jenkins-push', 'jenkins')
          .replace('manual-webhook', 'manual');
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
      statusSelect.addEventListener('change', () => { _explorerFilter.status = String(statusSelect.value || '').toUpperCase(); populateExplorer(); });
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
      const [healthRes, bootstrapRes, workersRes, configRes] = await Promise.all([
        fetch('/health'), fetch('/ui/bootstrap'), fetch('/api/workers'), fetch('/ui/config-status'),
      ]);
      const health = healthRes.ok ? await healthRes.json() : {};
      const bootstrap = bootstrapRes.ok ? await bootstrapRes.json() : {};
      const workersData = workersRes.ok ? await workersRes.json() : {};
      const configStatus = configRes.ok ? (await configRes.json()).vars || {} : {};

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
            <td class="py-2 px-md"><div class="h-2 bg-surface-container rounded-full overflow-hidden"><div class="h-full bg-primary bar-fill" style="--bar-w:${Math.round(count / workerList.length * 100)}%"></div></div></td>
          </tr>
        `).join('') || '<tr><td colspan="3" class="py-4 text-center text-on-surface-variant">No workers</td></tr>';
      }

      const ngrokInput = document.querySelector('[data-ui="st-ngrok-url"]');
      if (ngrokInput) ngrokInput.value = window.location.origin + '/github-webhook/';

      // Env var status inference
      const envBody = document.querySelector('[data-ui="st-env-body"]');
      const envVars = [
        { name: 'DATABASE_URL',          inferred: configStatus['DATABASE_URL']          ?? (bootstrap.backend?.status === 'RUNNING'), desc: 'PostgreSQL connection string' },
        { name: 'REDIS_URL',             inferred: configStatus['REDIS_URL']             ?? (bootstrap.backend?.status === 'RUNNING'), desc: 'Celery broker URL' },
        { name: 'JENKINS_URL',           inferred: configStatus['JENKINS_URL']           ?? false, desc: 'Jenkins base URL for log fetching' },
        { name: 'JENKINS_USER',          inferred: configStatus['JENKINS_USER']          ?? false, desc: 'Jenkins username' },
        { name: 'JENKINS_TOKEN',         inferred: configStatus['JENKINS_TOKEN']         ?? false, desc: 'Jenkins API token' },
        { name: 'GROQ_API_KEY',          inferred: configStatus['GROQ_API_KEY']          ?? false, desc: 'Primary LLM (Groq)' },
        { name: 'ANTHROPIC_API_KEY',     inferred: configStatus['ANTHROPIC_API_KEY']     ?? false, desc: 'Secondary LLM fallback' },
        { name: 'SLACK_BOT_TOKEN',       inferred: configStatus['SLACK_BOT_TOKEN']       ?? false, desc: 'Slack alert delivery' },
        { name: 'GITHUB_WEBHOOK_SECRET', inferred: configStatus['GITHUB_WEBHOOK_SECRET'] ?? false, desc: 'HMAC secret for GitHub webhooks' },
        { name: 'NGROK_URL',             inferred: configStatus['NGROK_URL']             ?? false, desc: 'Public tunnel URL for webhooks' },
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
    if (currentPath().startsWith('/webhooks')) {
      attachWebhookPageActions();
    }

    if (currentPath().startsWith('/queue')) {
      if (document.querySelector('[data-ui="queue-table-body"]')) {
        populateQueueTable();
        populateQueueMetrics();
        populateQueueChart();
        attachQueueSearch();
        const qInterval = setInterval(() => {
          if (document.querySelector('[data-ui="queue-table-body"]')) {
            populateQueueTable();
            populateQueueMetrics();
          }
          else clearInterval(qInterval);
        }, 5000);
        _allPollingIntervals.push(qInterval);
        const chartInterval = setInterval(() => {
          if (document.getElementById('queue-depth-svg')) populateQueueChart();
          else clearInterval(chartInterval);
        }, 30000);
        _allPollingIntervals.push(chartInterval);
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
        attachSchedulerModeButtons();
      }
      // Priority queue panel — always present on scheduler page
      populatePriorityQueue();
      const pqInterval = setInterval(() => {
        if (document.querySelector('[data-ui="priority-queue-list"]')) populatePriorityQueue();
        else clearInterval(pqInterval);
      }, 5000);
      _allPollingIntervals.push(pqInterval);
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
      // Refresh backend console data every 5s (faster than the global 10s bootstrap poll)
      const beInterval = setInterval(() => {
        if (document.querySelector('[data-ui="backend-request-body"]')) populateBootstrapData();
        else clearInterval(beInterval);
      }, 5000);
      _allPollingIntervals.push(beInterval);
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

    // Populate global bootstrap/dashboard data on every page, every 10 s.
    // Previously this was guarded by [data-ui="last-updated"] which only exists
    // on index.html — causing the interval to stop immediately on all other pages
    // and leaving backend/queue/scheduler panels with stale data.
    try {
      populateBootstrapData();
      const bInterval = setInterval(populateBootstrapData, 10000);
      _allPollingIntervals.push(bInterval);
    } catch (e) { /* ignore */ }

    // Repositories overview — only on dashboard (index)
    if (currentPath() === '/' || currentPath() === '' || currentPath() === '/index.html') {
      populateRepositories();
      const repoInterval = setInterval(() => {
        if (document.querySelector('[data-ui="repos-grid"]')) populateRepositories();
        else clearInterval(repoInterval);
      }, 10000);
      _allPollingIntervals.push(repoInterval);
    }

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
