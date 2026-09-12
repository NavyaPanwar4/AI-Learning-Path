import { useState, useEffect } from 'react';
import { FiCheckCircle } from 'react-icons/fi';
import { getUserSkills } from '../api/user';
import LoadingSpinner from '../components/LoadingSpinner';

export default function MySkillsPage() {
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    getUserSkills()
      .then((res) => setSkills(res.data))
      .catch(() => setError('Failed to load your skills.'))
      .finally(() => setLoading(false));
  }, []);

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
              {skills.map((s, i) => (
                <div key={i} className="skill-item" style={{ background: 'var(--color-surface)', padding: '12px 16px', borderRadius: '8px' }}>
                  <span className="skill-name" style={{ fontWeight: '600' }}>{s.skill_name}</span>
                  <div className="confidence-bar" style={{ maxWidth: '200px', marginLeft: 'auto' }}>
                    <div className="confidence-fill" style={{ width: `${Math.round(s.confidence * 100)}%` }} />
                  </div>
                  <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', minWidth: 32, textAlign: 'right' }}>
                    {Math.round(s.confidence * 100)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
