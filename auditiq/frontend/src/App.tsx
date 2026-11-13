import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";

// Pages load on demand; the 3D views pull in three.js only where they are used.
const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const ReviewPage = lazy(() => import("./pages/ReviewPage").then((m) => ({ default: m.ReviewPage })));
const InvoicePage = lazy(() => import("./pages/InvoicePage").then((m) => ({ default: m.InvoicePage })));
const PolicyPage = lazy(() => import("./pages/PolicyPage").then((m) => ({ default: m.PolicyPage })));
const AskPage = lazy(() => import("./pages/AskPage").then((m) => ({ default: m.AskPage })));
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })));
const RingsPage = lazy(() => import("./pages/RingsPage").then((m) => ({ default: m.RingsPage })));
const KafkaPage = lazy(() => import("./pages/KafkaPage").then((m) => ({ default: m.KafkaPage })));
const AiLayerPage = lazy(() => import("./pages/AiLayerPage").then((m) => ({ default: m.AiLayerPage })));
const KnowledgePage = lazy(() => import("./pages/KnowledgePage").then((m) => ({ default: m.KnowledgePage })));
const GraphPage = lazy(() => import("./pages/GraphPage").then((m) => ({ default: m.GraphPage })));
const RagPage = lazy(() => import("./pages/RagPage").then((m) => ({ default: m.RagPage })));
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
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="rings" element={<RingsPage />} />
          <Route path="kafka" element={<KafkaPage />} />
          <Route path="ai" element={<AiLayerPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="graph" element={<GraphPage />} />
          <Route path="rag" element={<RagPage />} />
          <Route path="ask" element={<AskPage />} />
          <Route path="copilot" element={<Navigate to="/ask" replace />} />
          <Route path="pipeline" element={<PipelinePage />} />
          <Route path="results" element={<ResultsPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
