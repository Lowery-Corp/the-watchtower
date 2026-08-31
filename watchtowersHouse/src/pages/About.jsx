import { Link } from "react-router";

const architecture = [
  {
    label: "Identity",
    title: "Profile-owned control plane",
    detail: "External authentication establishes the operator identity. Watchtower provisions a local profile that owns monitored services, credentials, and event history.",
  },
  {
    label: "Sources",
    title: "Explicit service boundaries",
    detail: "Every sender is registered as a monitored service. Its stable slug becomes the source identity carried by each event envelope.",
  },
  {
    label: "Ingestion",
    title: "Authenticated event intake",
    detail: "Service-bound managed keys authenticate versioned JSON envelopes before schema, ownership, activity, and replay checks run.",
  },
  {
    label: "Durability",
    title: "Atomic event and outbox writes",
    detail: "Accepted events and their outbox records are committed together in PostgreSQL, preserving the handoff boundary for downstream processing.",
  },
];

const implementationSteps = [
  {
    number: "01",
    title: "Register a monitored service",
    detail: "Create a service with a stable lowercase slug that identifies the sender in Watchtower and in every event payload.",
    action: { to: "/services", label: "Open Services" },
  },
  {
    number: "02",
    title: "Issue a service-bound API key",
    detail: "Create a managed ingestion key for that service, copy the plaintext value once, and store it in the sender's secret manager.",
    action: { to: "/api-keys", label: "Open API Keys" },
  },
  {
    number: "03",
    title: "Send version 1 events",
    detail: "POST a versioned envelope over TLS. Use a fresh UUID event_id for idempotency and keep the header source slug equal to the payload source.",
  },
];

const exampleRequest = `curl --request POST \
  https://dwatchtower.johnmgrubbs.io/api/v1/webhooks/events \
  --header "Content-Type: application/json" \
  --header "X-Watchtower-Service: payments-api" \
  --header "X-Watchtower-API-Key: $WATCHTOWER_API_KEY" \
  --data '{
    "spec_version": "1.0",
    "event_id": "70e99d5a-2e9e-4a3a-b81e-c834179a63cf",
    "event_type": "service.heartbeat",
    "source": "payments-api",
    "subject": "api-1",
    "occurred_at": "2026-08-31T18:00:00Z",
    "severity": "info",
    "environment": "production",
    "data": { "status": "healthy", "latency_ms": 42 }
  }'`;

export default function About() {
  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900 p-7 sm:p-10">
        <div className="absolute -right-20 -top-20 h-72 w-72 rounded-full bg-amber-300/10 blur-3xl" aria-hidden="true" />
        <div className="relative max-w-3xl">
          <p className="eyebrow">System briefing</p>
          <h1 className="mt-4 font-display text-4xl font-semibold tracking-tight text-white sm:text-5xl">About Watchtower</h1>
          <p className="mt-5 text-lg leading-8 text-slate-300">
            Watchtower is a tenant-aware control plane for receiving, authenticating, and preserving operational events from the services you run.
          </p>
          <p className="mt-4 max-w-2xl leading-7 text-slate-400">
            It gives operators one place to define source identities and machine credentials while giving applications a small, versioned ingestion contract built for retries and durable history.
          </p>
        </div>
      </section>

      <section aria-labelledby="how-watchtower-works" className="space-y-5">
        <div>
          <p className="eyebrow">Architecture</p>
          <h2 id="how-watchtower-works" className="mt-2 font-display text-3xl font-semibold text-white">How Watchtower works</h2>
          <p className="mt-3 max-w-3xl leading-7 text-slate-400">
            Human administration, machine authentication, event validation, and durable persistence stay separate so each boundary can fail closed.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {architecture.map((item) => (
            <article key={item.label} className="panel p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-amber-300">{item.label}</p>
              <h3 className="mt-3 font-display text-xl font-semibold text-white">{item.title}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-400">{item.detail}</p>
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="implement-watchtower" className="panel overflow-hidden">
        <div className="border-b border-white/10 p-6 sm:p-8">
          <p className="eyebrow">Integration guide</p>
          <h2 id="implement-watchtower" className="mt-2 font-display text-3xl font-semibold text-white">Implement Watchtower in your service</h2>
          <p className="mt-3 max-w-3xl leading-7 text-slate-400">
            A new sender needs one registered source, one scoped secret, and a small HTTPS client. No Watchtower SDK is required.
          </p>
        </div>
        <ol className="divide-y divide-white/10">
          {implementationSteps.map((step) => (
            <li key={step.number} className="grid gap-4 p-6 sm:grid-cols-[3.5rem_1fr_auto] sm:items-start sm:p-8">
              <span className="font-mono text-sm font-semibold text-amber-300">{step.number}</span>
              <div>
                <h3 className="font-display text-xl font-semibold text-white">{step.title}</h3>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">{step.detail}</p>
              </div>
              {step.action && <Link to={step.action.to} className="secondary-button inline-flex w-fit">{step.action.label}</Link>}
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-5 lg:grid-cols-[minmax(0,1.65fr)_minmax(17rem,0.7fr)]">
        <article className="overflow-hidden rounded-2xl border border-white/10 bg-slate-950 shadow-2xl shadow-black/20">
          <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
            <span className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Example request</span>
            <span className="rounded-full bg-emerald-400/10 px-2.5 py-1 text-xs font-semibold text-emerald-300">Managed key</span>
          </div>
          <pre className="overflow-x-auto p-5 text-xs leading-6 text-slate-300 sm:text-sm"><code>{exampleRequest}</code></pre>
        </article>

        <aside className="panel p-6" aria-labelledby="implementation-safeguards">
          <p className="eyebrow">Before shipping</p>
          <h2 id="implementation-safeguards" className="mt-2 font-display text-2xl font-semibold text-white">Implementation safeguards</h2>
          <ul className="mt-5 space-y-4 text-sm leading-6 text-slate-400">
            <li><strong className="text-slate-200">Use TLS.</strong> Never send managed keys over plaintext networks.</li>
            <li><strong className="text-slate-200">Keep keys secret.</strong> Store the one-time plaintext value outside source control and logs.</li>
            <li><strong className="text-slate-200">Retry safely.</strong> Reuse the same event_id when retrying the same event; Watchtower reports duplicates without creating a second record.</li>
            <li><strong className="text-slate-200">Stay bounded.</strong> Keep request bodies below the configured 256 KiB default and set a short client timeout.</li>
          </ul>
        </aside>
      </section>
    </div>
  );
}
