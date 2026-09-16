import { useState, useEffect } from 'react';
import { FiCheckCircle, FiTrash2 } from 'react-icons/fi';
import { getUserSkills, deleteUserSkill } from '../api/user';
import LoadingSpinner from '../components/LoadingSpinner';
import useSessionTimer from '../hooks/useSessionTimer';

export default function MySkillsPage() {
  useSessionTimer();
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    getUserSkills()
      .then((res) => setSkills(res.data))
      .catch(() => setError('Failed to load your skills.'))
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async (skillId) => {
    if (!window.confirm('Remove this skill from your profile? This cannot be undone.')) return;

    setDeletingId(skillId);
    try {
      await deleteUserSkill(skillId);
      setSkills((current) => current.filter((s) => s.skill_id !== skillId));
    } catch {
      setError('Failed to remove skill. Please try again.');
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) return <LoadingSpinner message="Loading your skills..." />;

  return (
    <div className="page">
      <div className="container">
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <h1 style={{ fontSize: '2rem', marginBottom: 8 }}>My Skills</h1>
          <p style={{ color: 'var(--color-text-muted)' }}>A comprehensive list of skills recognized by your AI tutor.</p>
        </div>

        {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div>}

        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <FiCheckCircle size={20} color="var(--color-success)" />
            <h3 style={{ fontSize: '1.1rem' }}>Identified Skills</h3>
            <span className="badge badge-primary" style={{ marginLeft: 'auto' }}>{skills.length}</span>
          </div>

          {skills.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted)', fontSize: '0.9rem', textAlign: 'center', padding: '20px 0' }}>
              No skills have been analyzed yet. Head to the Home page to start a new learning path!
            </p>
          ) : (
            <div className="skills-grid" style={{ gridTemplateColumns: '1fr', gap: '12px' }}>
              {skills.map((s) => (
                <div key={s.skill_id} className="skill-item" style={{ background: 'var(--color-surface)', padding: '12px 16px', borderRadius: '8px' }}>
                  <span className="skill-name" style={{ fontWeight: '600' }}>{s.skill_name}</span>
                  <div className="confidence-bar" style={{ maxWidth: '200px', marginLeft: 'auto' }}>
                    <div className="confidence-fill" style={{ width: `${Math.round(s.confidence * 100)}%` }} />
                  </div>
                  <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', minWidth: 32, textAlign: 'right' }}>
                    {Math.round(s.confidence * 100)}%
                  </span>
                  <button
                    onClick={() => handleDelete(s.skill_id)}
                    disabled={deletingId === s.skill_id}
                    title="Remove this skill"
                    style={{
                      background: 'none', border: 'none', cursor: deletingId === s.skill_id ? 'default' : 'pointer',
                      color: 'var(--color-text-muted)', padding: 6, marginLeft: 8, borderRadius: 6,
                      opacity: deletingId === s.skill_id ? 0.5 : 1,
                    }}
                  >
                    <FiTrash2 size={15} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}