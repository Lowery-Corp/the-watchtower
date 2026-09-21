import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Dialog from "../components/Dialog";
import { getErrorMessage } from "../services/api";
import { listMonitoredServices } from "../services/monitoredServices";
import {
  createUptimeMonitor,
  deactivateUptimeMonitor,
  listUptimeMonitors,
} from "../services/uptimeMonitors";

function formatDate(value) {
  if (!value) return "Not checked yet";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function MonitorStatus({ monitor }) {
  if (monitor.last_is_up === null) {
    return <span className="status-badge border-slate-400/20 bg-slate-400/10 text-slate-400">Pending</span>;
  }
  return monitor.last_is_up
    ? <span className="status-badge border-emerald-400/20 bg-emerald-400/10 text-emerald-300">Up</span>
    : <span className="status-badge border-red-400/20 bg-red-400/10 text-red-300">Down</span>;
}

function CreateMonitorDialog({ services, onClose, onCreated }) {
  const [url, setUrl] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    const payload = { url: url.trim(), service_id: serviceId };
    setError("");
    if (!payload.url || !payload.service_id) {
      setError("Enter a website URL and choose an existing service.");
      return;
    }
    setSubmitting(true);
    try {
      onCreated(await createUptimeMonitor(payload));
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The website monitor could not be created."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      labelledBy="create-uptime-monitor-title"
      onClose={onClose}
      dismissible={!submitting}
      initialFocusSelector="#uptime-url"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Active check</p>
          <h2 id="create-uptime-monitor-title" className="mt-2 font-display text-2xl font-semibold text-white">Add website monitor</h2>
        </div>
        <button type="button" disabled={submitting} onClick={onClose} className="icon-button" aria-label="Close add website monitor dialog">×</button>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-400">Watchtower checks public HTTP and HTTPS websites every minute.</p>
      <form onSubmit={handleSubmit} className="mt-6 space-y-5">
        <div>
          <label htmlFor="uptime-url" className="field-label">Website URL</label>
          <input id="uptime-url" type="url" className="field" required maxLength={2048} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com" />
        </div>
        <div>
          <label htmlFor="uptime-service" className="field-label">Existing service</label>
          <select id="uptime-service" className="field" required value={serviceId} onChange={(event) => setServiceId(event.target.value)}>
            <option value="">Choose a service</option>
            {services.map((service) => (
              <option key={service.id} value={service.id}>{service.display_name}{service.active ? "" : " (inactive)"}</option>
            ))}
          </select>
        </div>
        {error && <div role="alert" className="error-banner">{error}</div>}
        <div className="flex justify-end gap-3">
          <button type="button" disabled={submitting} onClick={onClose} className="secondary-button">Cancel</button>
          <button type="submit" disabled={submitting} className="primary-button">{submitting ? "Creating…" : "Create monitor"}</button>
        </div>
      </form>
    </Dialog>
  );
}

function StopMonitorDialog({ monitor, onClose, onStopped }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const stop = async () => {
    setSubmitting(true);
    setError("");
    try {
      await deactivateUptimeMonitor(monitor.id);
      onStopped(monitor.id);
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The website monitor could not be stopped."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog labelledBy="stop-uptime-monitor-title" onClose={onClose} dismissible={!submitting} initialFocusSelector="[data-stop-monitor]">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-red-300">Stop checks</p>
      <h2 id="stop-uptime-monitor-title" className="mt-2 font-display text-2xl font-semibold text-white">Stop monitoring this website?</h2>
      <p className="mt-3 break-all text-sm text-slate-300">{monitor.url}</p>
      <p className="mt-3 text-sm leading-6 text-slate-400">A check that already started may finish before stopping completes. No checks start after stopping completes, and existing history remains available for retention and audit purposes.</p>
      {error && <div role="alert" className="error-banner mt-5">{error}</div>}
      <div className="mt-6 flex justify-end gap-3">
        <button type="button" disabled={submitting} onClick={onClose} className="secondary-button">Cancel</button>
        <button type="button" data-stop-monitor disabled={submitting} onClick={stop} className="danger-button">{submitting ? "Stopping…" : "Stop monitor"}</button>
      </div>
    </Dialog>
  );
}

export default function UptimeMonitors() {
  const [monitors, setMonitors] = useState([]);
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingStop, setPendingStop] = useState(null);
  const fullLoadVersion = useRef(0);
  const monitorVersion = useRef(0);

  const loadData = useCallback(async () => {
    const fullVersion = ++fullLoadVersion.current;
    const monitorsVersion = ++monitorVersion.current;
    setLoading(true);
    setError("");
    setRefreshError("");
    try {
      const [loadedServices, loadedMonitors] = await Promise.all([
        listMonitoredServices(),
        listUptimeMonitors(),
      ]);
      if (fullVersion !== fullLoadVersion.current) return;
      setServices(loadedServices);
      if (monitorsVersion === monitorVersion.current) setMonitors(loadedMonitors);
    } catch (requestError) {
      if (fullVersion !== fullLoadVersion.current) return;
      setError(getErrorMessage(requestError, "Website uptime could not be loaded."));
    } finally {
      if (fullVersion === fullLoadVersion.current) setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => {
    let cancelled = false;
    let timeout;
    const refresh = async () => {
      const version = ++monitorVersion.current;
      try {
        const refreshed = await listUptimeMonitors();
        if (!cancelled && version === monitorVersion.current) {
          setMonitors(refreshed);
          setRefreshError("");
        }
      } catch {
        if (!cancelled && version === monitorVersion.current) {
          setRefreshError("Uptime data may be out of date. Refresh to try again.");
        }
      } finally {
        if (!cancelled) timeout = window.setTimeout(refresh, 30_000);
      }
    };
    timeout = window.setTimeout(refresh, 30_000);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, []);

  const summary = useMemo(() => ({
    up: monitors.filter((monitor) => monitor.last_is_up === true).length,
    down: monitors.filter((monitor) => monitor.last_is_up === false).length,
    pending: monitors.filter((monitor) => monitor.last_is_up === null).length,
  }), [monitors]);

  const handleCreated = (created) => {
    monitorVersion.current += 1;
    setMonitors((current) => [created, ...current]);
    setCreating(false);
  };
  const handleStopped = (monitorId) => {
    monitorVersion.current += 1;
    setMonitors((current) => current.filter((monitor) => monitor.id !== monitorId));
    setPendingStop(null);
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">External availability</p>
          <h1 className="mt-2 font-display text-4xl font-semibold text-white">Website Uptime</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Track public website reachability from Watchtower with secure one-minute checks and a rolling 24-hour uptime view.</p>
        </div>
        <button type="button" disabled={loading || Boolean(error) || services.length === 0} onClick={() => setCreating(true)} className="primary-button">Add website monitor</button>
      </header>

      {!loading && !error && monitors.length > 0 && (
        <section aria-label="Uptime summary" className="grid gap-4 sm:grid-cols-3">
          {[["Up", summary.up, "text-emerald-300"], ["Down", summary.down, "text-red-300"], ["Pending", summary.pending, "text-slate-300"]].map(([label, value, tone]) => (
            <article key={label} className="panel p-5"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">{label}</p><p className={`mt-3 font-display text-3xl font-semibold ${tone}`}>{value}</p></article>
          ))}
        </section>
      )}

      {error && <div role="alert" className="error-banner"><p>{error}</p><button type="button" onClick={loadData} className="secondary-button mt-4">Retry</button></div>}
      {!error && refreshError && <div role="alert" className="error-banner"><p>{refreshError}</p><button type="button" onClick={loadData} className="secondary-button mt-4">Retry</button></div>}

      <section className="panel overflow-hidden" aria-label="Website uptime monitors">
        {loading ? (
          <div className="p-10 text-center text-sm text-slate-500" role="status">Loading website uptime…</div>
        ) : error ? (
          <div className="p-10 text-center text-sm text-slate-500">Website uptime unavailable.</div>
        ) : services.length === 0 ? (
          <div className="p-12 text-center"><p className="font-display text-xl font-semibold text-slate-200">Add a monitored service first</p><p className="mt-2 text-sm text-slate-500">Every website monitor must belong to an existing service.</p></div>
        ) : monitors.length === 0 ? (
          <div className="p-12 text-center"><p className="font-display text-xl font-semibold text-slate-200">No website monitors yet</p><p className="mt-2 text-sm text-slate-500">Add a public HTTP or HTTPS URL to begin one-minute checks.</p></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="border-b border-white/10 bg-white/[0.02] text-xs uppercase tracking-[0.14em] text-slate-500"><tr><th className="px-5 py-4 font-semibold">Website</th><th className="px-5 py-4 font-semibold">Service</th><th className="px-5 py-4 font-semibold">Status</th><th className="px-5 py-4 font-semibold">24h uptime</th><th className="px-5 py-4 font-semibold">Latency</th><th className="px-5 py-4 font-semibold">Last check</th><th className="px-5 py-4 font-semibold"><span className="sr-only">Actions</span></th></tr></thead>
              <tbody className="divide-y divide-white/5">
                {monitors.map((monitor) => (
                  <tr key={monitor.id} className="transition hover:bg-white/[0.025]">
                    <td className="px-5 py-4"><a href={monitor.url} target="_blank" rel="noreferrer noopener" className="break-all font-medium text-amber-200 transition hover:text-amber-100">{monitor.url}</a>{monitor.last_status_code && <p className="mt-1 text-xs text-slate-500">HTTP {monitor.last_status_code}</p>}</td>
                    <td className="px-5 py-4"><p className="text-slate-200">{monitor.service_display_name}</p><p className="mt-1 font-mono text-xs text-slate-500">{monitor.service_slug}</p></td>
                    <td className="px-5 py-4"><MonitorStatus monitor={monitor} /></td>
                    <td className="px-5 py-4 text-slate-300">{monitor.uptime_24h_percent === null ? "—" : `${monitor.uptime_24h_percent.toFixed(2)}%`}</td>
                    <td className="px-5 py-4 text-slate-400">{monitor.last_response_time_ms === null ? "—" : `${monitor.last_response_time_ms} ms`}</td>
                    <td className="px-5 py-4 text-slate-400">{formatDate(monitor.last_checked_at)}</td>
                    <td className="px-5 py-4 text-right"><button type="button" onClick={() => setPendingStop(monitor)} className="text-sm font-medium text-red-300 transition hover:text-red-200" aria-label={`Stop monitoring ${monitor.url}`}>Stop</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {creating && <CreateMonitorDialog services={services} onClose={() => setCreating(false)} onCreated={handleCreated} />}
      {pendingStop && <StopMonitorDialog monitor={pendingStop} onClose={() => setPendingStop(null)} onStopped={handleStopped} />}
    </div>
  );
}
