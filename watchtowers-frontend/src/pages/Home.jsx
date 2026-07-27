import { useAuth } from "../auth/AuthProvider";

export default function Home() {
  const { user } = useAuth();

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-gradient-to-br from-purple-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800">
      <div className="container mx-auto px-4 py-16">
        <div className="max-w-2xl mx-auto text-center">
          {/* Hero Section */}
          <div className="mb-12">
            <h1 className="text-5xl font-bold text-gray-900 dark:text-white mb-6">
              Welcome Home
            </h1>
            <p className="text-xl text-gray-600 dark:text-gray-300 mb-8">
              Hello, <span className="text-purple-600 dark:text-purple-400 font-semibold">{user?.username}</span>!
              You're successfully logged in.
            </p>
          </div>

          {/* User Card */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8 mb-8">
            <div className="flex items-center justify-center mb-6">
              <div className="w-20 h-20 bg-gradient-to-r from-purple-500 to-indigo-500 rounded-full flex items-center justify-center">
                <span className="text-2xl font-bold text-white">
                  {user?.username?.charAt(0).toUpperCase()}
                </span>
              </div>
            </div>

            <h2 className="text-2xl font-semibold text-gray-900 dark:text-white mb-2">
              {user?.username}
            </h2>

            <div className="flex flex-wrap justify-center gap-2 mb-6">
              {user?.permissions?.map((permission) => (
                <span
                  key={permission}
                  className="px-3 py-1 bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 text-sm rounded-full"
                >
                  {permission}
                </span>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-lg hover:shadow-xl transition-shadow">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Quick Stats
              </h3>
              <p className="text-gray-600 dark:text-gray-300">
                Session active since login
              </p>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-lg hover:shadow-xl transition-shadow">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
                Permissions
              </h3>
              <p className="text-gray-600 dark:text-gray-300">
                {user?.permissions?.length || 0} active permissions
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}