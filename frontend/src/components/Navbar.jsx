import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  FiCompass,
  FiStar,
  FiLogOut,
  FiMap,
  FiHome,
  FiMessageSquare,
  FiUser,
  FiCalendar,
} from 'react-icons/fi';
import { logout } from '../api/auth';
import { useAuth } from '../context/useAuth';

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
        <NavLink className="btn btn-ghost" to="/" end>
          <FiCompass size={16} /> Landing page
        </NavLink>
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
