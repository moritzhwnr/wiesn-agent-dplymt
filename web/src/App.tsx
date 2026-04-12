import { lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Portals from './pages/Portals';
import Settings from './pages/Settings';

const Statistics = lazy(() => import('./pages/Statistics'));

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="welcome" element={<WelcomePage />} />
        <Route path="portals" element={<Portals />} />
        <Route path="statistics" element={
          <Suspense fallback={
            <div className="space-y-6">
              <div className="skeleton h-8 w-48 rounded-lg" />
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="skeleton h-24 rounded-2xl" />
                ))}
              </div>
              <div className="skeleton h-80 rounded-2xl" />
            </div>
          }>
            <Statistics />
          </Suspense>
        } />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}

function WelcomePage() {
  const Welcome = lazy(() => import('./pages/Welcome'));
  return (
    <Suspense fallback={<div className="skeleton h-96 rounded-2xl" />}>
      <Welcome />
    </Suspense>
  );
}
