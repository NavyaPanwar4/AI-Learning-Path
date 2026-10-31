import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Navbar from './components/Navbar';
import AuthPage from './pages/AuthPage';
import LandingPage from './pages/LandingPage';
import HomePage from './pages/HomePage';
import BuildPlanPage from './pages/BuildPlanPage';
import SkillAssessmentPage from './pages/SkillAssessmentPage';
import MySkillsPage from './pages/MySkillsPage';
import RoadmapPage from './pages/RoadmapPage';
import SavedRoadmapsPage from './pages/SavedRoadmapsPage';
import MyReviewsPage from './pages/MyReviewsPage';
import './styles/global.css';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import ProfilePage from './pages/ProfilePage';
import ChatWidget from './components/ChatWidget';
import LearningInsightsPage from './pages/LearningInsightsPage';
import StudyPlannerPage from './pages/StudyPlannerPage';
import SharedProgressPage from './pages/SharedProgressPage';
import { AuthProvider } from './context/AuthContext.jsx';
import { useAuth } from './context/useAuth';

function ProtectedRoute({ children }) {
  const { authenticated } = useAuth();
  return authenticated ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Navbar />
        <Routes>
          {/* The public landing page is the entry point for both signed-out and signed-in users. */}
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<AuthPage initialMode="login" />} />
          <Route path="/register" element={<AuthPage initialMode="register" />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/share/:token" element={<SharedProgressPage />} />
          <Route path="/home" element={<ProtectedRoute><HomePage /></ProtectedRoute>} />
          <Route path="/onboarding" element={<ProtectedRoute><BuildPlanPage /></ProtectedRoute>} />
          <Route path="/assess-skills" element={<ProtectedRoute><SkillAssessmentPage /></ProtectedRoute>} />
          <Route path="/my-skills" element={<ProtectedRoute><MySkillsPage /></ProtectedRoute>} />
          <Route path="/roadmap" element={<ProtectedRoute><RoadmapPage /></ProtectedRoute>} />
          <Route path="/roadmap/:goalId" element={<ProtectedRoute><RoadmapPage /></ProtectedRoute>} />
          <Route path="/insights/:goalId" element={<ProtectedRoute><LearningInsightsPage /></ProtectedRoute>} />
          <Route path="/study-planner" element={<ProtectedRoute><StudyPlannerPage /></ProtectedRoute>} />
          <Route path="/saved-roadmaps" element={<ProtectedRoute><SavedRoadmapsPage /></ProtectedRoute>} />
          <Route path="/my-reviews" element={<ProtectedRoute><MyReviewsPage /></ProtectedRoute>} />
          <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <ChatWidget />
      </BrowserRouter>
    </AuthProvider>
  );
}
