import { Link, Navigate, Route, Routes } from "react-router";
import { useAuth } from "./auth/AuthProvider";
import ProtectedRoute from "./components/ProtectedRoute";
import UserLayout from "./layouts/UserLayout";
import AuthLayout from "./layouts/AuthLayout";
import Login from "./pages/Login";
import About from "./pages/About";
import Unauthorized from "./pages/Unauthorized";

export default function App() {
  const { user, logout, isAuthenticated, authLoading} = useAuth();

  if (authLoading) {
    return <div>Loading...</div>;
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Navigation Bar */}
      <nav className="bg-white dark:bg-gray-800 shadow-lg border-b border-gray-200 dark:border-gray-700">
        <div className="mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            {/* Logo/Brand */}
            <div className="flex min-w-0 items-center gap-8">
              <div className="flex shrink-0 items-center">
                {isAuthenticated ? (
                <Link
                  to="/"
                  className="text-xl font-bold text-purple-600 dark:text-purple-400 hover:text-purple-700 dark:hover:text-purple-300 transition-colors"
                >
                 The Watchtower
                </Link>
              ) : (
                <Link
                  to="/user/login"
                  className="text-xl font-bold text-purple-600 dark:text-purple-400 hover:text-purple-700 dark:hover:text-purple-300 transition-colors"
                >
                 The Watchtower
                </Link>
                )}
              </div>

              {/* Navigation Links */}
              <div className="hidden min-w-0 items-center space-x-2 md:flex">
              {isAuthenticated ? (
                <>
                  <Link
                    to="/about"
                    className="text-gray-700 dark:text-gray-300 hover:text-purple-600 dark:hover:text-purple-400 px-3 py-2 rounded-md text-sm font-medium transition-colors"
                  >
                    About
                  </Link>
                  {user?.permissions?.includes("read:admin") && (
                    <Link
                      to="/auth/admin"
                      className="text-gray-700 dark:text-gray-300 hover:text-purple-600 dark:hover:text-purple-400 px-3 py-2 rounded-md text-sm font-medium transition-colors"
                    >
                      Admin
                    </Link>
                  )}
                </>
              ) : (
                <Link
                  to="/about"
                  className="text-gray-700 dark:text-gray-300 hover:text-purple-600 dark:hover:text-purple-400 px-3 py-2 rounded-md text-sm font-medium transition-colors"
                >
                  About
                </Link>
              )}
              </div>
            </div>

            {/* User Menu */}
            <div className="flex items-center space-x-4">
              {isAuthenticated ? (
                <div className="flex items-center space-x-3">
                  <Link
                    to="/"
                    className="rounded-md px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-100 hover:text-purple-600 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-purple-400"
                  >
                    Welcome, {user?.username}
                  </Link>
                  <button
                    onClick={logout}
                    className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors"
                  >
                    Logout
                  </button>
                </div>
              ) : (
                <Link
                  to="/user/login"
                  className="bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors"
                >
                  Login
                </Link>
              )}
            </div>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="flex-1">
        <Routes>
          <Route path="user" element={<UserLayout />}>
            {/* <Route path="login" element={<Login />} />
            <Route path="create" element={<CreateUser />} /> */}
          </Route>

          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<About />} />
          </Route>

          <Route path="unauthorized" element={<Unauthorized />} />
          <Route path="about" element={<About />} />
          <Route path="*" element={<Navigate to="/about" replace />} />
        </Routes>
      </main>
    </div>
  );
}