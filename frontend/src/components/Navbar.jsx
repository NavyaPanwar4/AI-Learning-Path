import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { FiCompass, FiStar, FiLogOut, FiMap, FiHome, FiMessageSquare, FiUser, FiCalendar, FiCheckCircle } from 'react-icons/fi';
import { logout } from '../api/auth';
import { useAuth } from '../context/useAuth';
import { useRoadmapGeneration } from '../context/useRoadmapGeneration.js';

const PUBLIC_PATHS = new Set([
  '/',
  '/login',
  '/register',
  '/forgot-password',
  '/reset-password',
]);

export default function Navbar() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { authenticated, signOut } = useAuth();
  const { job, dismissJob } = useRoadmapGeneration();

  const handleLogout = () => {
    logout().catch(() => {});
    signOut();
    navigate('/');
  };

  const isPublicRoute = PUBLIC_PATHS.has(pathname) || pathname.startsWith('/share/');
  if (!authenticated || isPublicRoute) return null;

  return (
    <nav className="navbar" aria-label="Main navigation">
      <Link to="/" className="navbar-brand" aria-label="Traject landing page">
        <FiCompass size={22} />
        Traject
      </Link>
      <div className="navbar-links">
        {['queued', 'running', 'cancel_requested'].includes(job?.status) ? (
          <button
            type="button"
            className="btn btn-ghost roadmap-generation-status"
            onClick={() => navigate('/roadmap')}
            title="Return to your roadmap generation screen"
            aria-live="polite"
          >
            <span className="roadmap-generation-spinner" aria-hidden="true" />
            <span className="roadmap-generation-status-label">
              {job.status === 'cancel_requested' ? 'Cancelling...' : 'Generating roadmap · View'}
            </span>
          </button>
        ) : job?.status === 'completed' ? (
          <button
            type="button"
            className="btn btn-ghost roadmap-generation-status is-ready"
            onClick={() => {
              const destination = job.goal_id ? `/roadmap/${job.goal_id}` : '/saved-roadmaps';
              dismissJob();
              navigate(destination);
            }}
            title="Your roadmap is ready"
            aria-live="polite"
          >
            <FiCheckCircle size={16} />
            <span className="roadmap-generation-status-label">Roadmap ready · View</span>
          </button>
        ) : null}
        <span className="nav-section-label">Workspace</span>
        <NavLink className="btn btn-ghost" to="/home"><FiHome size={16} /> Overview</NavLink>
        <NavLink className="btn btn-ghost" to="/my-skills"><FiStar size={16} /> My skills</NavLink>
        <NavLink className="btn btn-ghost" to="/saved-roadmaps"><FiMap size={16} /> Learning paths</NavLink>
        <span className="nav-section-label">Activity</span>
        <NavLink className="btn btn-ghost" to="/my-reviews"><FiMessageSquare size={16} /> My reviews</NavLink>
        <NavLink className="btn btn-ghost" to="/study-planner"><FiCalendar size={16} /> Study planner</NavLink>
        <NavLink className="btn btn-ghost" to="/profile"><FiUser size={16} /> My profile</NavLink>
        <button className="btn btn-ghost logout-button" onClick={handleLogout}>
          <FiLogOut size={16} /> Sign out
        </button>
      </div>
    </nav>
  );
}
