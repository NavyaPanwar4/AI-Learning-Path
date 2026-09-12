import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiArrowRight } from 'react-icons/fi';
import { getGoals, updateProfile } from '../api/user';
import LoadingSpinner from '../components/LoadingSpinner';

const EXPERIENCE_OPTS = ['beginner', 'intermediate', 'advanced'];
const STYLE_OPTS = ['visual', 'reading', 'interactive'];

export default function HomePage() {
  const navigate = useNavigate();
  const [goals, setGoals] = useState([]);
  const [loadingGoals, setLoadingGoals] = useState(true);
  
  const [selectedGoalId, setSelectedGoalId] = useState('');
  const [experience, setExperience] = useState('beginner');
  const [style, setStyle] = useState('visual');
  const [hours, setHours] = useState(10);
  
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    getGoals()
      .then((res) => {
        setGoals(res.data);
        if (res.data.length > 0) {
          setSelectedGoalId(res.data[0].goal_id.toString());
        }
      })
      .catch(() => setError('Could not load goals. Is your backend running?'))
      .finally(() => setLoadingGoals(false));
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedGoalId) { setError('Please select a learning goal.'); return; }
    if (hours < 5 || hours > 80) { setError('Hours must be between 5 and 80.'); return; }
    
    setSubmitting(true);
    setError('');
    try {
      await updateProfile({
        goal_id: String(selectedGoalId),
        experience_level: experience,
        available_hours_per_week: Number(hours),
        learning_style: style,
      });
      navigate('/assess-skills');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save profile.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingGoals) return <LoadingSpinner message="Loading goals..." />;

  return (
    <div className="page">
      <div className="container">
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <h1 style={{ fontSize: '2rem', marginBottom: 8 }}>Build Your Learning Plan</h1>
          <p style={{ color: 'var(--color-text-muted)' }}>Choose your goal and we'll generate a personalized roadmap just for you.</p>
        </div>

        <div className="card" style={{ marginBottom: 24 }}>
          <form onSubmit={handleSubmit}>
            {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div>}
            
            <div className="input-group" style={{ marginBottom: 20 }}>
              <label>What do you want to achieve?</label>
              <select value={selectedGoalId} onChange={(e) => setSelectedGoalId(e.target.value)}>
                {goals.map((g) => (
                  <option key={g.goal_id} value={g.goal_id}>
                    {g.goal_name} ({g.category})
                  </option>
                ))}
              </select>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 20, marginBottom: 24 }}>
              <div className="input-group">
                <label>Experience Level</label>
                <select value={experience} onChange={(e) => setExperience(e.target.value)}>
                  {EXPERIENCE_OPTS.map((o) => (
                    <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div className="input-group">
                <label>Learning Style</label>
                <select value={style} onChange={(e) => setStyle(e.target.value)}>
                  {STYLE_OPTS.map((o) => (
                    <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div className="input-group">
                <label>Hours Available Per Week</label>
                <input 
                  type="number" 
                  min="5" 
                  max="80" 
                  value={hours} 
                  onChange={(e) => setHours(e.target.value)} 
                  required
                />
              </div>
            </div>

            <button
              className="btn btn-primary"
              type="submit"
              disabled={submitting}
              style={{ width: '100%', padding: '16px', fontSize: '1rem' }}
            >
              {submitting ? 'Saving...' : (<>Continue to Skill Assessment <FiArrowRight size={18} /></>)}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
