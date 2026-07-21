import { Navigate, Outlet, useLocation } from "react-router";
import { useAuth } from "../auth/AuthProvider";

export default function ProtectedRoute() {
  const { isAuthenticated, authLoading } = useAuth();
  const location = useLocation();

  if (authLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-950 text-slate-300">
        <div className="flex items-center gap-3" role="status">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-amber-400" />
          Contacting the tower…
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
