import { useCallback, useEffect, useMemo, useState } from "react";
import Dialog from "../components/Dialog";
import { getErrorMessage } from "../services/api";
import {
  createMonitoredService,
  deactivateMonitoredService,
  listMonitoredServices,
  updateMonitoredService,
} from "../services/monitoredServices";

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function CreateServiceDialog({ onClose, onCreated }) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [environment, setEnvironment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    const payload = {
      slug: slug.trim(),
      display_name: displayName.trim(),
      environment: environment.trim(),
    };
    if (!payload.slug || !payload.display_name || !payload.environment) {
      setError("Complete every service field.");
      return;
    }
    setSubmitting(true);
    try {
      onCreated(await createMonitoredService(payload));
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The monitored service could not be created."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      labelledBy="create-service-title"
      onClose={onClose}
      dismissible={!submitting}
      initialFocusSelector="#service-slug"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Event source</p>
          <h2 id="create-service-title" className="mt-2 font-display text-2xl font-semibold text-white">Add monitored service</h2>
        </div>
        <button type="button" disabled={submitting} onClick={onClose} className="icon-button" aria-label="Close add monitored service dialog">×</button>
      </div>
      <form onSubmit={handleSubmit} className="mt-6 space-y-5">
        <div>
          <label htmlFor="service-slug" className="field-label">Service slug</label>
          <input id="service-slug" className="field" required maxLength={100} pattern="[a-z0-9]+([._-][a-z0-9]+)*" value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="payments-api" />
          <p className="mt-2 text-xs text-slate-500">Stable lowercase identity used in webhook headers. It cannot be changed later.</p>
        </div>
        <div>
          <label htmlFor="service-display-name" className="field-label">Display name</label>
          <input id="service-display-name" className="field" required maxLength={255} value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Payments API" />
        </div>
        <div>
          <label htmlFor="service-environment" className="field-label">Environment</label>
          <input id="service-environment" className="field" required maxLength={64} pattern="[a-z0-9]+([._-][a-z0-9]+)*" value={environment} onChange={(event) => setEnvironment(event.target.value)} placeholder="production" />
        </div>
        {error && <div role="alert" className="error-banner">{error}</div>}
        <div className="flex justify-end gap-3">
          <button type="button" disabled={submitting} onClick={onClose} className="secondary-button">Cancel</button>
          <button type="submit" disabled={submitting} className="primary-button">{submitting ? "Creating…" : "Create service"}</button>
        </div>
      </form>
    </Dialog>
  );
}

function EditServiceDialog({ service, onClose, onUpdated }) {
  const [displayName, setDisplayName] = useState(service.display_name);
  const [environment, setEnvironment] = useState(service.environment);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    const payload = {
      display_name: displayName.trim(),
      environment: environment.trim(),
    };
    if (!payload.display_name || !payload.environment) {
      setError("Complete every service field.");
      return;
    }
    setSubmitting(true);
    try {
      onUpdated(await updateMonitoredService(service.id, payload));
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The monitored service could not be updated."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog labelledBy="edit-service-title" onClose={onClose} dismissible={!submitting} initialFocusSelector="#edit-service-display-name">
      <p className="eyebrow">Service metadata</p>
      <h2 id="edit-service-title" className="mt-2 font-display text-2xl font-semibold text-white">Edit monitored service</h2>
      <p className="mt-3 text-sm leading-6 text-slate-400">The source slug <code className="text-amber-200">{service.slug}</code> is permanent. Display metadata can change without breaking senders.</p>
      <form onSubmit={handleSubmit} className="mt-6 space-y-5">
        <div>
          <label htmlFor="edit-service-display-name" className="field-label">Display name</label>
          <input id="edit-service-display-name" className="field" required maxLength={255} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
        </div>
        <div>
          <label htmlFor="edit-service-environment" className="field-label">Environment</label>
          <input id="edit-service-environment" className="field" required maxLength={64} pattern="[a-z0-9]+([._-][a-z0-9]+)*" value={environment} onChange={(event) => setEnvironment(event.target.value)} />
        </div>
        {error && <div role="alert" className="error-banner">{error}</div>}
        <div className="flex justify-end gap-3">
          <button type="button" disabled={submitting} onClick={onClose} className="secondary-button">Cancel</button>
          <button type="submit" disabled={submitting} className="primary-button">{submitting ? "Saving…" : "Save changes"}</button>
        </div>
      </form>
    </Dialog>
  );
}

function DeactivateServiceDialog({ service, onClose, onDeactivated }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleDeactivate = async () => {
    setSubmitting(true);
    setError("");
    try {
      await deactivateMonitoredService(service.id);
      onDeactivated(service.id);
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The monitored service could not be deactivated."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog labelledBy="deactivate-service-title" onClose={onClose} dismissible={!submitting} initialFocusSelector="[data-deactivate-service]">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-red-300">Stop ingestion</p>
      <h2 id="deactivate-service-title" className="mt-2 font-display text-2xl font-semibold text-white">Deactivate {service.display_name}?</h2>
      <p className="mt-3 text-sm leading-6 text-slate-400">New events for this source will be rejected immediately, including requests using service-bound keys. Historical events remain available, and the service can be reactivated later.</p>
      {error && <div role="alert" className="error-banner mt-5">{error}</div>}
      <div className="mt-6 flex justify-end gap-3">
        <button type="button" disabled={submitting} onClick={onClose} className="secondary-button">Cancel</button>
        <button type="button" data-deactivate-service disabled={submitting} onClick={handleDeactivate} className="danger-button">{submitting ? "Deactivating…" : "Deactivate service"}</button>
      </div>
    </Dialog>
  );
}

function ServiceStatus({ active }) {
  return active
    ? <span className="status-badge border-emerald-400/20 bg-emerald-400/10 text-emerald-300">Active</span>
    : <span className="status-badge border-slate-400/20 bg-slate-400/10 text-slate-400">Inactive</span>;
}

export default function MonitoredServices() {
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [serviceBeingEdited, setServiceBeingEdited] = useState(null);
  const [servicePendingDeactivation, setServicePendingDeactivation] = useState(null);
  const [reactivatingId, setReactivatingId] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setServices(await listMonitoredServices());
    } catch (requestError) {
      setError(getErrorMessage(requestError, "Monitored services could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const activeCount = useMemo(() => services.filter((service) => service.active).length, [services]);
  const replaceService = (updated) => {
    setServices((current) => current.map((service) => (
      service.id === updated.id ? updated : service
    )));
  };
  const handleCreated = (created) => {
    setServices((current) => [created, ...current]);
    setCreating(false);
  };
  const handleUpdated = (updated) => {
    replaceService(updated);
    setServiceBeingEdited(null);
  };
  const handleDeactivated = (serviceId) => {
    setServices((current) => current.map((service) => (
      service.id === serviceId ? { ...service, active: false } : service
    )));
    setServicePendingDeactivation(null);
  };
  const handleReactivate = async (service) => {
    setReactivatingId(service.id);
    setError("");
    try {
      replaceService(await updateMonitoredService(service.id, { active: true }));
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The monitored service could not be reactivated."));
    } finally {
      setReactivatingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">Source registry</p>
          <h1 className="mt-2 font-display text-4xl font-semibold text-white">Monitored Services</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Register profile-owned event sources, maintain their display metadata, and control whether ingestion is accepted.</p>
        </div>
        <button type="button" disabled={loading || Boolean(error)} onClick={() => setCreating(true)} className="primary-button">Add monitored service</button>
      </header>

      {!loading && !error && services.length > 0 && (
        <section aria-label="Service summary" className="grid gap-4 sm:grid-cols-2">
          <article className="panel p-5"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Active sources</p><p className="mt-3 font-display text-3xl font-semibold text-white">{activeCount}</p></article>
          <article className="panel p-5"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Registered total</p><p className="mt-3 font-display text-3xl font-semibold text-white">{services.length}</p></article>
        </section>
      )}

      {error && (
        <div role="alert" className="error-banner">
          <p>{error}</p>
          <button type="button" onClick={loadData} className="secondary-button mt-4">Retry</button>
        </div>
      )}

      <section className="panel overflow-hidden" aria-label="Monitored service registry">
        {loading ? (
          <div className="p-10 text-center text-sm text-slate-500" role="status">Loading service registry…</div>
        ) : error ? (
          <div className="p-10 text-center text-sm text-slate-500">Service registry unavailable.</div>
        ) : services.length === 0 ? (
          <div className="p-12 text-center"><p className="font-display text-xl font-semibold text-slate-200">No monitored services registered</p><p className="mt-2 text-sm text-slate-500">Add an event source before issuing a service-bound API key.</p></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="border-b border-white/10 bg-white/[0.02] text-xs uppercase tracking-[0.14em] text-slate-500">
                <tr><th className="px-5 py-4 font-semibold">Service</th><th className="px-5 py-4 font-semibold">Environment</th><th className="px-5 py-4 font-semibold">Updated</th><th className="px-5 py-4 font-semibold">Status</th><th className="px-5 py-4 font-semibold"><span className="sr-only">Actions</span></th></tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {services.map((service) => (
                  <tr key={service.id} className="transition hover:bg-white/[0.025]">
                    <td className="px-5 py-4"><p className="font-medium text-slate-200">{service.display_name}</p><p className="mt-1 font-mono text-xs text-slate-500">{service.slug}</p></td>
                    <td className="px-5 py-4 text-slate-400">{service.environment}</td>
                    <td className="px-5 py-4 text-slate-400">{formatDate(service.updated_at)}</td>
                    <td className="px-5 py-4"><ServiceStatus active={service.active} /></td>
                    <td className="px-5 py-4 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <button type="button" onClick={() => setServiceBeingEdited(service)} className="text-sm font-medium text-slate-300 transition hover:text-amber-200" aria-label={`Edit ${service.display_name}`}>Edit</button>
                        {service.active ? (
                          <button type="button" onClick={() => setServicePendingDeactivation(service)} className="text-sm font-medium text-red-300 transition hover:text-red-200" aria-label={`Deactivate ${service.display_name}`}>Deactivate</button>
                        ) : (
                          <button type="button" disabled={reactivatingId === service.id} onClick={() => handleReactivate(service)} className="text-sm font-medium text-emerald-300 transition hover:text-emerald-200 disabled:opacity-50" aria-label={`Reactivate ${service.display_name}`}>{reactivatingId === service.id ? "Reactivating…" : "Reactivate"}</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {creating && <CreateServiceDialog onClose={() => setCreating(false)} onCreated={handleCreated} />}
      {serviceBeingEdited && <EditServiceDialog service={serviceBeingEdited} onClose={() => setServiceBeingEdited(null)} onUpdated={handleUpdated} />}
      {servicePendingDeactivation && <DeactivateServiceDialog service={servicePendingDeactivation} onClose={() => setServicePendingDeactivation(null)} onDeactivated={handleDeactivated} />}
    </div>
  );
}
