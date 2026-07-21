import { useState } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import BrandMark from "../components/BrandMark";

export default function Login() {
  const { isAuthenticated, authLoading, authError, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const location = useLocation();
  const destination = location.state?.from?.pathname || "/home";

  if (!authLoading && isAuthenticated) return <Navigate to={destination} replace />;

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    await login({ email: email.trim(), password });
    setSubmitting(false);
  };

  return (
    <main className="relative grid min-h-screen overflow-hidden bg-slate-950 lg:grid-cols-[1.15fr_0.85fr]">
      <div className="tower-grid absolute inset-0 opacity-40" aria-hidden="true" />
      <section className="relative hidden min-h-screen flex-col justify-between border-r border-white/5 p-12 lg:flex">
        <BrandMark />
        <div className="max-w-xl">
          <p className="mb-5 text-xs font-semibold uppercase tracking-[0.3em] text-amber-300">Signal intelligence</p>
          <h1 className="font-display text-6xl font-semibold leading-[1.02] tracking-tight text-white">
            Keep watch over<br />every critical signal.
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-slate-400">
            Secure event ingestion, tenant-isolated service monitoring, and machine credentials from one control plane.
          </p>
        </div>
        <p className="text-xs uppercase tracking-[0.2em] text-slate-600">Lowery Corp · Systems nominal</p>
      </section>

      <section className="relative flex min-h-screen items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          <div className="mb-10 lg:hidden"><BrandMark /></div>
          <div className="rounded-2xl border border-white/10 bg-slate-900/80 p-7 shadow-2xl shadow-black/30 backdrop-blur sm:p-9">
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-300">Restricted access</p>
            <h2 className="mt-3 font-display text-3xl font-semibold text-white">Sign in to Watchtower</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">Use your DB Management account. Credentials are forwarded securely and never stored here.</p>

            <form onSubmit={handleSubmit} className="mt-8 space-y-5">
              <div>
                <label htmlFor="email" className="mb-2 block text-sm font-medium text-slate-300">Email</label>
                <input id="email" name="email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} className="field" placeholder="operator@example.com" />
              </div>
              <div>
                <label htmlFor="password" className="mb-2 block text-sm font-medium text-slate-300">Password</label>
                <input id="password" name="password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} className="field" placeholder="Enter your password" />
              </div>
              {authError && <div role="alert" className="rounded-lg border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-200">{authError}</div>}
              <button type="submit" disabled={submitting || authLoading} className="primary-button w-full">
                {submitting ? "Authenticating…" : "Sign in"}
              </button>
            </form>
          </div>
          <p className="mt-6 text-center text-xs text-slate-600">Sessions are protected with secure, HttpOnly cookies.</p>
        </div>
      </section>
    </main>
  );
}
