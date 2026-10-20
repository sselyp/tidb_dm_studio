import { Spin } from "antd";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import AccountPage from "../pages/AccountPage";
import DataSourcesPage from "../pages/DataSourcesPage";
import LoginPage from "../pages/LoginPage";
import TaskDetailPage from "../pages/TaskDetailPage";
import TaskLogsPage from "../pages/TaskLogsPage";
import TaskWizardPage from "../pages/TaskWizardPage";
import TasksPage from "../pages/TasksPage";
import AppLayout from "./AppLayout";

function RequireAuth() {
  const { me, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
        <Spin />
      </div>
    );
  }
  if (!me) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (me.mustChangePassword && location.pathname !== "/account") {
    return <Navigate to="/account" replace />;
  }
  return <Outlet />;
}

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/tasks" replace />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/tasks/new" element={<TaskWizardPage />} />
          <Route path="/tasks/:name" element={<TaskDetailPage />} />
          <Route path="/tasks/:name/logs" element={<TaskLogsPage />} />
          <Route path="/datasources" element={<DataSourcesPage />} />
          <Route path="/account" element={<AccountPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
