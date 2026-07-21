import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { listApiKeys } from "../services/apiKeys";
import { getErrorMessage } from "../services/api";
import { listMonitoredServices } from "../services/monitoredServices";

function MetricCard({ label, value, detail, accent = "amber" }) {
  const dot = accent === "green" ? "bg-emerald-400" : accent === "blue" ? "bg-sky-400" : "bg-amber-300";
  return (
    <article className="panel p-5">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500"><span className={`h-2 w-2 rounded-full ${dot}`} />{label}</div>
      <p className="mt-4 font-display text-4xl font-semibold text-white">{value}</p>
      <p className="mt-2 text-sm text-slate-500">{detail}</p>
    </article>
  );
}

export default function Home() {
  const { user } = useAuth();
  const [services, setServices] = useState([]);
  const [apiKeys, setApiKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [serviceData, keyData] = await Promise.all([listMonitoredServices(), listApiKeys()]);
      setServices(serviceData);
      setApiKeys(keyData);
    } catch (requestError) {
      setError(getErrorMessage(requestError, "Dashboard data could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const activeServices = useMemo(() => services.filter((service) => service.active).length, [services]);
  const activeKeys = useMemo(() => apiKeys.filter((key) => (
    !key.revoked_at && (!key.expires_at || new Date(key.expires_at) > new Date())
  )).length, [apiKeys]);
  const displayName = user?.display_name || user?.username || "operator";

  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900 to-slate-950 p-7 sm:p-9">
        <div className="absolute right-0 top-0 h-56 w-56 rounded-full bg-amber-300/5 blur-3xl" aria-hidden="true" />
        <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-300">Command overview</p>
        <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-white">Welcome back, {displayName}</h1>
        <p className="mt-3 max-w-2xl text-slate-400">Your profile owns every service, event stream, and API credential shown in this workspace.</p>
      </section>

      {error ? (
        <div role="alert" className="rounded-xl border border-red-400/20 bg-red-400/10 px-5 py-4 text-sm text-red-200">
          <p>{error}</p>
          <button type="button" onClick={loadData} className="secondary-button mt-4">Retry</button>
        </div>
      ) : (
        <section aria-label="Watchtower metrics" className="grid gap-4 md:grid-cols-3">
          <MetricCard label="Monitored services" value={loading ? "—" : activeServices} detail={`${services.length} registered total`} accent="green" />
          <MetricCard label="Active API keys" value={loading ? "—" : activeKeys} detail="Usable ingestion credentials" />
          <MetricCard label="Total API keys" value={loading ? "—" : apiKeys.length} detail="Includes expired and revoked keys" accent="blue" />
        </section>
      )}

      <section className="grid gap-4 lg:grid-cols-3">
        <article className="panel p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Event sources</p>
          <h2 className="mt-3 font-display text-2xl font-semibold text-white">Manage monitored services</h2>
          <p className="mt-3 text-sm leading-6 text-slate-400">Register source identities, maintain environment metadata, and pause or resume ingestion.</p>
          <Link to="/services" className="secondary-button mt-6 inline-flex">Open Services</Link>
        </article>
        <article className="panel p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Machine access</p>
          <h2 className="mt-3 font-display text-2xl font-semibold text-white">Manage ingestion keys</h2>
          <p className="mt-3 text-sm leading-6 text-slate-400">Issue service-bound credentials, inspect last-use timestamps, and revoke access immediately.</p>
          <Link to="/api-keys" className="secondary-button mt-6 inline-flex">Open API Keys</Link>
        </article>
        <article className="panel p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Profile identity</p>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Username</dt><dd className="truncate text-slate-200">{user?.username}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Profile ID</dt><dd className="truncate font-mono text-xs text-slate-300">{user?.profile_id}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-slate-500">Role</dt><dd className="text-slate-200">{user?.is_admin ? "Administrator" : "Operator"}</dd></div>
          </dl>
        </article>
      </section>
    </div>
  );
}
