import { lazy, Suspense } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";

// Pages load on demand; the 3D views pull in three.js only where they are used.
const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const ReviewPage = lazy(() => import("./pages/ReviewPage").then((m) => ({ default: m.ReviewPage })));
const InvoicePage = lazy(() => import("./pages/InvoicePage").then((m) => ({ default: m.InvoicePage })));
const PolicyPage = lazy(() => import("./pages/PolicyPage").then((m) => ({ default: m.PolicyPage })));
const CopilotPage = lazy(() => import("./pages/CopilotPage").then((m) => ({ default: m.CopilotPage })));
const PipelinePage = lazy(() => import("./pages/PipelinePage").then((m) => ({ default: m.PipelinePage })));
const ResultsPage = lazy(() => import("./pages/ResultsPage").then((m) => ({ default: m.ResultsPage })));

function NotFound() {
  return (
    <div className="page">
      <h1>Not found</h1>
      <p className="muted">
        There is no page here. <Link to="/">Back to the overview</Link>
      </p>
    </div>
  );
}

export function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="review" element={<ReviewPage />} />
          <Route path="invoice" element={<InvoicePage />} />
          <Route path="invoice/:id" element={<InvoicePage />} />
          <Route path="policy" element={<PolicyPage />} />
          <Route path="copilot" element={<CopilotPage />} />
          <Route path="pipeline" element={<PipelinePage />} />
          <Route path="results" element={<ResultsPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
