import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import BrandMark from "../components/BrandMark";

function navClass({ isActive }) {
  return `rounded-lg px-3 py-2 text-sm font-medium transition ${
    isActive
      ? "bg-amber-300/10 text-amber-200"
      : "text-slate-400 hover:bg-white/5 hover:text-white"
  }`;
}

export default function AppLayout() {
  const { user, authError, logout } = useAuth();
  const navigate = useNavigate();
  const [signingOut, setSigningOut] = useState(false);

  const handleLogout = async () => {
    setSigningOut(true);
    const result = await logout();
    if (result.ok) navigate("/login", { replace: true });
    else setSigningOut(false);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-40 border-b border-white/5 bg-slate-950/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:flex-nowrap sm:px-6 lg:px-8">
          <BrandMark compact />
          <nav aria-label="Primary navigation" className="order-3 flex w-full items-center justify-center gap-1 border-t border-white/5 pt-2 sm:order-none sm:w-auto sm:border-0 sm:pt-0">
            <NavLink to="/home" className={navClass}>Home</NavLink>
            <NavLink to="/api-keys" className={navClass}>API Keys</NavLink>
          </nav>
          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium text-slate-200">{user?.profile?.display_name || user?.username}</p>
              <p className="text-xs text-slate-500">{user?.is_admin ? "Administrator" : "Operator"}</p>
            </div>
            <button type="button" disabled={signingOut} onClick={handleLogout} className="rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:border-amber-300/30 hover:text-amber-200 disabled:opacity-60">
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {authError && <div role="alert" className="error-banner mb-6">{authError}</div>}
        <Outlet />
      </main>
    </div>
  );
}
