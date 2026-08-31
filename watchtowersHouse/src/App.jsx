import { Navigate, Route, Routes } from "react-router";
import ProtectedRoute from "./components/ProtectedRoute";
import AppLayout from "./layouts/AppLayout";
import Home from "./pages/Home";
import ApiKeys from "./pages/ApiKeys";
import About from "./pages/About";
import Login from "./pages/Login";
import MonitoredServices from "./pages/MonitoredServices";

function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center bg-slate-950 px-6 text-center text-slate-200">
      <div><p className="text-sm uppercase tracking-[0.3em] text-amber-300">404</p><h1 className="mt-3 font-display text-4xl font-semibold">Signal not found</h1></div>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/home" replace />} />
          <Route path="home" element={<Home />} />
          <Route path="services" element={<MonitoredServices />} />
          <Route path="api-keys" element={<ApiKeys />} />
          <Route path="about" element={<About />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
