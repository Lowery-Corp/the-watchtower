import { useCallback, useEffect, useMemo, useState } from "react";
import Dialog from "../components/Dialog";
import { createApiKey, listApiKeys, revokeApiKey, updateApiKey } from "../services/apiKeys";
import { getErrorMessage } from "../services/api";
import { listMonitoredServices } from "../services/monitoredServices";

function formatDate(value) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function KeyStatus({ apiKey }) {
  if (apiKey.revoked_at) return <span className="status-badge border-red-400/20 bg-red-400/10 text-red-300">Revoked</span>;
  if (apiKey.expires_at && new Date(apiKey.expires_at) <= new Date()) return <span className="status-badge border-orange-400/20 bg-orange-400/10 text-orange-300">Expired</span>;
  return <span className="status-badge border-emerald-400/20 bg-emerald-400/10 text-emerald-300">Active</span>;
}

function CreateKeyDialog({ services, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Enter a key name.");
      return;
    }
    setSubmitting(true);
    try {
      const created = await createApiKey({
        name: trimmedName,
        service_id: serviceId || null,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      onCreated(created);
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The API key could not be issued."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      labelledBy="create-key-title"
      onClose={onClose}
      dismissible={!submitting}
      initialFocusSelector="#key-name"
    >
      <div className="flex items-start justify-between gap-4">
        <div><p className="eyebrow">Machine credential</p><h2 id="create-key-title" className="mt-2 font-display text-2xl font-semibold text-white">Create API key</h2></div>
        <button type="button" disabled={submitting} onClick={onClose} className="icon-button" aria-label="Close create API key dialog">×</button>
      </div>
      <form onSubmit={handleSubmit} className="mt-6 space-y-5">
        <div><label htmlFor="key-name" className="field-label">Key name</label><input id="key-name" className="field" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} placeholder="Production ingestion" /></div>
        <div><label htmlFor="bound-service" className="field-label">Bound service</label><select id="bound-service" className="field" value={serviceId} onChange={(event) => setServiceId(event.target.value)}><option value="">All profile services</option>{services.filter((service) => service.active).map((service) => <option key={service.id} value={service.id}>{service.display_name} · {service.environment}</option>)}</select><p className="mt-2 text-xs text-slate-500">Service binding is permanent after the key is issued.</p></div>
        <div><label htmlFor="expires-at" className="field-label">Expires at <span className="text-slate-600">(optional)</span></label><input id="expires-at" className="field" type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></div>
        {error && <div role="alert" className="error-banner">{error}</div>}
        <div className="flex justify-end gap-3"><button type="button" disabled={submitting} onClick={onClose} className="secondary-button">Cancel</button><button type="submit" disabled={submitting} className="primary-button">{submitting ? "Issuing…" : "Issue key"}</button></div>
      </form>
    </Dialog>
  );
}

function copyWithLegacySelection(value) {
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  return copied;
}

function SecretDialog({ apiKey, onClose }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const copySecret = async () => {
    setCopyError("");
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(apiKey.api_key);
      } else if (!copyWithLegacySelection(apiKey.api_key)) {
        throw new Error("Legacy clipboard copy failed");
      }
      setCopied(true);
    } catch {
      setCopied(false);
      setCopyError("Copy failed. Select the secret above and copy it manually.");
    }
  };
  return (
    <Dialog label="Copy your API key now" onClose={onClose} initialFocusSelector="[data-copy-secret]" className="border-amber-300/20">
      <p className="eyebrow">One-time disclosure</p>
      <h2 className="mt-2 font-display text-2xl font-semibold text-white">Copy your API key now</h2>
      <p className="mt-3 text-sm leading-6 text-slate-400">This secret will never be shown again. Store it in your service’s secret manager before closing this dialog.</p>
      <div className="mt-6 rounded-xl border border-amber-300/20 bg-slate-950 p-4"><code className="block break-all text-sm leading-6 text-amber-200">{apiKey.api_key}</code></div>
      <button type="button" data-copy-secret onClick={copySecret} className="secondary-button mt-4 w-full">{copied ? "Copied to clipboard" : "Copy secret"}</button>
      {copyError && <p role="alert" className="mt-3 text-sm text-red-300">{copyError}</p>}
      <button type="button" onClick={onClose} className="primary-button mt-3 w-full">I have saved this key</button>
    </Dialog>
  );
}

function EditKeyDialog({ apiKey, onClose, onUpdated }) {
  const [name, setName] = useState(apiKey.name);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Enter a key name.");
      return;
    }
    setSubmitting(true);
    try {
      const updated = await updateApiKey(apiKey.id, { name: trimmedName });
      onUpdated(updated);
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The API key could not be updated."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog labelledBy="edit-key-title" onClose={onClose} dismissible={!submitting} initialFocusSelector="#edit-key-name">
      <p className="eyebrow">Safe metadata</p>
      <h2 id="edit-key-title" className="mt-2 font-display text-2xl font-semibold text-white">Edit API key</h2>
      <p className="mt-3 text-sm leading-6 text-slate-400">Only the display name can change here. Service binding, secret material, and expiry restrictions remain fixed.</p>
      <form onSubmit={handleSubmit} className="mt-6 space-y-5">
        <div><label htmlFor="edit-key-name" className="field-label">Key name</label><input id="edit-key-name" className="field" required maxLength={100} value={name} onChange={(event) => setName(event.target.value)} /></div>
        {error && <div role="alert" className="error-banner">{error}</div>}
        <div className="flex justify-end gap-3"><button type="button" disabled={submitting} onClick={onClose} className="secondary-button">Cancel</button><button type="submit" disabled={submitting} className="primary-button">{submitting ? "Saving…" : "Save changes"}</button></div>
      </form>
    </Dialog>
  );
}

function RevokeKeyDialog({ apiKey, onClose, onRevoked }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleRevoke = async () => {
    setSubmitting(true);
    setError("");
    try {
      await revokeApiKey(apiKey.id);
      onRevoked(apiKey.id);
    } catch (requestError) {
      setError(getErrorMessage(requestError, "The API key could not be revoked."));
      setSubmitting(false);
    }
  };

  return (
    <Dialog labelledBy="revoke-key-title" onClose={onClose} dismissible={!submitting} initialFocusSelector="[data-revoke-key]">
      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-red-300">Immediate revocation</p>
      <h2 id="revoke-key-title" className="mt-2 font-display text-2xl font-semibold text-white">Revoke {apiKey.name}?</h2>
      <p className="mt-3 text-sm leading-6 text-slate-400">Requests using this credential will fail immediately. Revocation cannot be reversed, and historical usage metadata will be retained.</p>
      {error && <div role="alert" className="error-banner mt-5">{error}</div>}
      <div className="mt-6 flex justify-end gap-3">
        <button type="button" disabled={submitting} onClick={onClose} className="secondary-button">Cancel</button>
        <button type="button" data-revoke-key onClick={handleRevoke} disabled={submitting} className="danger-button">{submitting ? "Revoking…" : "Revoke key"}</button>
      </div>
    </Dialog>
  );
}

export default function ApiKeys() {
  const [apiKeys, setApiKeys] = useState([]);
  const [services, setServices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [disclosedKey, setDisclosedKey] = useState(null);
  const [keyBeingEdited, setKeyBeingEdited] = useState(null);
  const [keyPendingRevocation, setKeyPendingRevocation] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [keys, serviceData] = await Promise.all([listApiKeys(), listMonitoredServices()]);
      setApiKeys(keys);
      setServices(serviceData);
    } catch (requestError) {
      setError(getErrorMessage(requestError, "API keys could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const servicesById = useMemo(() => new Map(services.map((service) => [service.id, service])), [services]);
  const handleCreated = (created) => {
    const { api_key: secret, ...metadata } = created;
    setApiKeys((current) => [metadata, ...current]);
    setCreating(false);
    setDisclosedKey({ ...metadata, api_key: secret });
  };
  const handleRevoked = (apiKeyId) => {
    const revokedAt = new Date().toISOString();
    setApiKeys((current) => current.map((apiKey) => (
      apiKey.id === apiKeyId ? { ...apiKey, revoked_at: revokedAt } : apiKey
    )));
    setKeyPendingRevocation(null);
  };
  const handleUpdated = (updatedKey) => {
    setApiKeys((current) => current.map((apiKey) => (
      apiKey.id === updatedKey.id ? updatedKey : apiKey
    )));
    setKeyBeingEdited(null);
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div><p className="eyebrow">Credential registry</p><h1 className="mt-2 font-display text-4xl font-semibold text-white">API Keys</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Issue and revoke machine credentials for authenticated event ingestion. Plaintext keys are disclosed once.</p></div>
        <button type="button" disabled={loading || Boolean(error)} onClick={() => setCreating(true)} className="primary-button">Create API key</button>
      </header>

      {error && (
        <div role="alert" className="error-banner">
          <p>{error}</p>
          <button type="button" onClick={loadData} className="secondary-button mt-4">Retry</button>
        </div>
      )}
      <section className="panel overflow-hidden" aria-label="API key registry">
        {loading ? <div className="p-10 text-center text-sm text-slate-500" role="status">Loading credential registry…</div> : error ? <div className="p-10 text-center text-sm text-slate-500">Credential registry unavailable.</div> : apiKeys.length === 0 ? <div className="p-12 text-center"><p className="font-display text-xl font-semibold text-slate-200">No API keys issued</p><p className="mt-2 text-sm text-slate-500">Create a key to authenticate your first event source.</p></div> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="border-b border-white/10 bg-white/[0.02] text-xs uppercase tracking-[0.14em] text-slate-500">
                <tr>
                  <th className="px-5 py-4 font-semibold">Key</th>
                  <th className="px-5 py-4 font-semibold">Scope</th>
                  <th className="px-5 py-4 font-semibold">Service</th>
                  <th className="px-5 py-4 font-semibold">Last used</th>
                  <th className="px-5 py-4 font-semibold">Status</th>
                  <th className="px-5 py-4 font-semibold"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {apiKeys.map((apiKey) => (
                  <tr key={apiKey.id} className="transition hover:bg-white/[0.025]">
                    <td className="px-5 py-4"><p className="font-medium text-slate-200">{apiKey.name}</p><p className="mt-1 font-mono text-xs text-slate-600">{apiKey.public_prefix}…</p></td>
                    <td className="px-5 py-4 font-mono text-xs text-slate-400">{apiKey.scopes.join(", ")}</td>
                    <td className="px-5 py-4 text-slate-400">{servicesById.get(apiKey.service_id)?.display_name || "All services"}</td>
                    <td className="px-5 py-4 text-slate-400">{formatDate(apiKey.last_used_at)}</td>
                    <td className="px-5 py-4"><KeyStatus apiKey={apiKey} /></td>
                    <td className="px-5 py-4 text-right">
                      <div className="flex items-center justify-end gap-3">
                        {!apiKey.revoked_at && (
                          <button type="button" onClick={() => setKeyBeingEdited(apiKey)} className="text-sm font-medium text-slate-300 transition hover:text-amber-200" aria-label={`Edit ${apiKey.name}`}>
                            Edit
                          </button>
                        )}
                        {!apiKey.revoked_at && (
                          <button type="button" onClick={() => setKeyPendingRevocation(apiKey)} className="text-sm font-medium text-red-300 transition hover:text-red-200" aria-label={`Revoke ${apiKey.name}`}>
                            Revoke
                          </button>
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

      {creating && <CreateKeyDialog services={services} onClose={() => setCreating(false)} onCreated={handleCreated} />}
      {disclosedKey && <SecretDialog apiKey={disclosedKey} onClose={() => setDisclosedKey(null)} />}
      {keyBeingEdited && <EditKeyDialog apiKey={keyBeingEdited} onClose={() => setKeyBeingEdited(null)} onUpdated={handleUpdated} />}
      {keyPendingRevocation && <RevokeKeyDialog apiKey={keyPendingRevocation} onClose={() => setKeyPendingRevocation(null)} onRevoked={handleRevoked} />}
    </div>
  );
}
