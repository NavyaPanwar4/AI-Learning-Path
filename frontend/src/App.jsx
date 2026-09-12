import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Navbar from './components/Navbar';
import AuthPage from './pages/AuthPage';
import LandingPage from './pages/LandingPage';
import HomePage from './pages/HomePage';
import SkillAssessmentPage from './pages/SkillAssessmentPage';
import MySkillsPage from './pages/MySkillsPage';
import RoadmapPage from './pages/RoadmapPage';
import SavedRoadmapsPage from './pages/SavedRoadmapsPage';
import MyReviewsPage from './pages/MyReviewsPage';
import './styles/global.css';

function ProtectedRoute({ children }) {
  const token = localStorage.getItem('token');
  return token ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Navbar />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<AuthPage />} />
        <Route path="/home" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
        <Route path="/onboarding" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
        <Route path="/assess-skills" element={<ProtectedRoute><SkillAssessmentPage /></ProtectedRoute>} />
        <Route path="/my-skills" element={<ProtectedRoute><MySkillsPage /></ProtectedRoute>} />
        <Route path="/roadmap" element={<ProtectedRoute><RoadmapPage /></ProtectedRoute>} />
        <Route path="/roadmap/:goalId" element={<ProtectedRoute><RoadmapPage /></ProtectedRoute>} />
        <Route path="/saved-roadmaps" element={<ProtectedRoute><SavedRoadmapsPage /></ProtectedRoute>} />
        <Route path="/my-reviews" element={<ProtectedRoute><MyReviewsPage /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
