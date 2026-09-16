import { NavLink, useNavigate } from 'react-router-dom';
import { FiCompass, FiStar, FiLogOut, FiMap, FiHome, FiMessageSquare, FiUser } from 'react-icons/fi';

export default function Navbar() {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    navigate('/');
  };

  const token = localStorage.getItem('token');
  if (!token) return null;

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <FiCompass size={22} />
        Learning Path
      </div>
      <div className="navbar-links">
        <span className="nav-section-label">Workspace</span>
        <NavLink className="btn btn-ghost" to="/home"><FiHome size={16} /> Overview</NavLink>
        <NavLink className="btn btn-ghost" to="/my-skills"><FiStar size={16} /> My skills</NavLink>
        <NavLink className="btn btn-ghost" to="/saved-roadmaps"><FiMap size={16} /> Learning paths</NavLink>
        <span className="nav-section-label">Activity</span>
        <NavLink className="btn btn-ghost" to="/my-reviews"><FiMessageSquare size={16} /> My reviews</NavLink>
        <NavLink className="btn btn-ghost" to="/profile"><FiUser size={16} /> My profile</NavLink>
        <button className="btn btn-ghost logout-button" onClick={handleLogout}>
          <FiLogOut size={16} /> Sign out
        </button>
      </div>
    </nav>
  );
}
