/**
 * Routing and page transitions.
 *
 * Five routes, one per decision, so the browser's back button and a shareable URL
 * both work. Everything shown comes from a real API response, which in turn traces
 * to the bundled ERA5 record — there is no mock data anywhere in this build. When a
 * dependency is missing, the backend's typed error is displayed instead.
 */
import { AnimatePresence } from 'motion/react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { RequireSite } from '@/components/Shell';
import ExposurePage from '@/pages/ExposurePage';
import LocationPage from '@/pages/LocationPage';
import MaterialsPage from '@/pages/MaterialsPage';
import ModePage from '@/pages/ModePage';
import ScorePage from '@/pages/ScorePage';

export default function App() {
  const location = useLocation();

  return (
    // `mode="wait"` so the outgoing page finishes leaving before the next arrives.
    // Overlapping them would briefly show two headings, and on the globe route it
    // would mount a second WebGL context.
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/" element={<LocationPage />} />
        <Route
          path="/exposure"
          element={
            <RequireSite>
              <ExposurePage />
            </RequireSite>
          }
        />
        <Route
          path="/mode"
          element={
            <RequireSite>
              <ModePage />
            </RequireSite>
          }
        />
        <Route
          path="/materials"
          element={
            <RequireSite>
              <MaterialsPage />
            </RequireSite>
          }
        />
        <Route
          path="/score"
          element={
            <RequireSite>
              <ScorePage />
            </RequireSite>
          }
        />
        {/* An unknown URL returns to the start rather than rendering nothing. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AnimatePresence>
  );
}
