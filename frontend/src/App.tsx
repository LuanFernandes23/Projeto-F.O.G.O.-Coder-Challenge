import { lazy, Suspense } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { Skeleton } from "@/components/ui/primitives";
import { LoginPage } from "@/features/auth/LoginPage";
import { useAuth } from "@/lib/auth";

// A Central (mapa + gráficos) é carregada sob demanda: o login abre instantâneo.
const OperationsPage = lazy(() =>
  import("@/features/operations/OperationsPage").then((m) => ({ default: m.OperationsPage })),
);
const EquipmentListPage = lazy(() =>
  import("@/features/inventory/EquipmentListPage").then((m) => ({ default: m.EquipmentListPage })),
);
const EquipmentFormPage = lazy(() =>
  import("@/features/inventory/EquipmentFormPage").then((m) => ({ default: m.EquipmentFormPage })),
);
const AgentListPage = lazy(() =>
  import("@/features/inventory/AgentListPage").then((m) => ({ default: m.AgentListPage })),
);
const AgentFormPage = lazy(() =>
  import("@/features/inventory/AgentFormPage").then((m) => ({ default: m.AgentFormPage })),
);
const PredictionsPage = lazy(() =>
  import("@/features/prediction/PredictionsPage").then((m) => ({ default: m.PredictionsPage })),
);
const AdminPage = lazy(() =>
  import("@/features/admin/AdminPage").then((m) => ({ default: m.AdminPage })),
);
const HelpPage = lazy(() =>
  import("@/features/help/HelpPage").then((m) => ({ default: m.HelpPage })),
);

function RequireAuth() {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) return <Skeleton className="m-6 h-24" />;
  if (!isAuthenticated)
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <Outlet />;
}

const fallback = <Skeleton className="m-6 h-[60vh]" />;

export function App() {
  return (
    <Suspense fallback={fallback}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<AppShell />}>
            <Route index element={<OperationsPage />} />
            <Route path="inventario/equipamentos" element={<EquipmentListPage />} />
            <Route path="inventario/equipamentos/novo" element={<EquipmentFormPage />} />
            <Route path="inventario/equipamentos/:id" element={<EquipmentFormPage />} />
            <Route path="inventario/agentes" element={<AgentListPage />} />
            <Route path="inventario/agentes/novo" element={<AgentFormPage />} />
            <Route path="inventario/agentes/:id" element={<AgentFormPage />} />
            <Route path="previsoes" element={<PredictionsPage />} />
            <Route path="administracao/:section?" element={<AdminPage />} />
            <Route path="ajuda" element={<HelpPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
