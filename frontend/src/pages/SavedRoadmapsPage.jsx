import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiCompass, FiArrowRight, FiTrash2 } from 'react-icons/fi';
import { getSavedRoadmaps, deleteRoadmap } from '../api/roadmap';
import LoadingSpinner from '../components/LoadingSpinner';

export default function SavedRoadmapsPage() {
  const navigate = useNavigate();
  const [roadmaps, setRoadmaps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    getSavedRoadmaps()
      .then((res) => setRoadmaps(res.data))
      .catch(() => setError('Failed to load saved roadmaps.'))
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async (e, goalId) => {
    e.stopPropagation();
    if (!window.confirm('Delete this learning path? This cannot be undone.')) return;

    setDeletingId(goalId);
    try {
      await deleteRoadmap(goalId);
      setRoadmaps((current) => current.filter((r) => r.goal_id !== goalId));
    } catch {
      setError('Failed to delete roadmap. Please try again.');
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) return <LoadingSpinner message="Loading your saved roadmaps..." />;

  return (
    <div className="page">
      <div className="container">
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <h1 style={{ fontSize: '2rem', marginBottom: 8 }}>My Roadmaps</h1>
          <p style={{ color: 'var(--color-text-muted)' }}>Review your previously generated learning paths.</p>
        </div>

        {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div>}

        {roadmaps.length === 0 && !error ? (
          <div className="card" style={{ textAlign: 'center', padding: 40 }}>
            <p style={{ color: 'var(--color-text-muted)', marginBottom: 20 }}>You haven't generated any roadmaps yet.</p>
            <button className="btn btn-primary" onClick={() => navigate('/onboarding')}>
              Create a New Plan
            </button>
          </div>
        ) : (
          <div className="goals-grid">
            {roadmaps.map((r, i) => (
              <div
                key={i}
                className="goal-card"
                onClick={() => navigate(`/roadmap/${r.goal_id}`)}
                style={{ position: 'relative' }}
              >
                <button
                  onClick={(e) => handleDelete(e, r.goal_id)}
                  disabled={deletingId === r.goal_id}
                  title="Delete this learning path"
                  style={{
                    position: 'absolute', top: 10, right: 10, background: 'none', border: 'none',
                    cursor: deletingId === r.goal_id ? 'default' : 'pointer', color: 'var(--color-text-muted)',
                    padding: 6, borderRadius: 6, opacity: deletingId === r.goal_id ? 0.5 : 1,
                  }}
                >
                  <FiTrash2 size={16} />
                </button>
                <div style={{ padding: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
                    <FiCompass size={32} color="var(--color-primary)" />
                  </div>
                  <div className="goal-name" style={{ fontSize: '1.2rem', marginBottom: 8, textAlign: 'center' }}>
                    {r.goal_name}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
                    <span className={`badge ${r.is_complete ? 'badge-primary' : 'badge-surface'}`} style={{ fontSize: '0.75rem' }}>
                      {r.is_complete ? 'Completed' : 'In Progress'}
                    </span>
                  </div>
                  <button className="btn btn-outline" style={{ width: '100%', padding: '10px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px' }}>
                    View <FiArrowRight size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}