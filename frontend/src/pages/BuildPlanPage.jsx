import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiArrowRight } from 'react-icons/fi';
import { getGoals, updateProfile } from '../api/user';
import { getExistingRoadmap } from '../api/roadmap';
import LoadingSpinner from '../components/LoadingSpinner';

const EXPERIENCE_OPTS = ['beginner', 'intermediate', 'advanced'];
const STYLE_OPTS = ['visual', 'reading', 'interactive'];

export default function BuildPlanPage() {
  const navigate = useNavigate();
  const [goals, setGoals] = useState([]);
  const [loadingGoals, setLoadingGoals] = useState(true);
  
  const [selectedGoalId, setSelectedGoalId] = useState('');
  const [experience, setExperience] = useState('beginner');
  const [style, setStyle] = useState('visual');
  const [hours, setHours] = useState(10);
  
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [existingRoadmap, setExistingRoadmap] = useState(null);
  const [checkingExistingRoadmap, setCheckingExistingRoadmap] = useState(false);
  const [roadmapCheckError, setRoadmapCheckError] = useState('');
  const [roadmapCheckAttempt, setRoadmapCheckAttempt] = useState(0);

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


  // Check the selected goal immediately, before profile save and skill assessment.
  useEffect(() => {
    if (!selectedGoalId) {
      setExistingRoadmap(null);
      setCheckingExistingRoadmap(false);
      setRoadmapCheckError('');
      return undefined;
    }

    let active = true;
    setCheckingExistingRoadmap(true);
    setExistingRoadmap(null);
    setRoadmapCheckError('');

    getExistingRoadmap(selectedGoalId)
      .then(({ data }) => {
        if (active) setExistingRoadmap(data?.exists ? data : null);
      })
      .catch((err) => {
        if (active) {
          setRoadmapCheckError(
            err.response?.data?.detail || 'Could not verify whether this learning path already exists. Please retry.'
          );
        }
      })
      .finally(() => {
        if (active) setCheckingExistingRoadmap(false);
      });

    return () => { active = false; };
  }, [selectedGoalId, roadmapCheckAttempt]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedGoalId) { setError('Please select a learning goal.'); return; }
    if (hours < 5 || hours > 80) { setError('Hours must be between 5 and 80.'); return; }
    if (checkingExistingRoadmap) { setError('Please wait while we check this learning path.'); return; }
    if (roadmapCheckError) { setError(roadmapCheckError); return; }
    if (existingRoadmap?.exists) return;
    
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
              <label htmlFor="plan-goal">What do you want to achieve?</label>
              <select id="plan-goal" value={selectedGoalId} onChange={(e) => setSelectedGoalId(e.target.value)}>
                {goals.map((g) => (
                  <option key={g.goal_id} value={g.goal_id}>
                    {g.goal_name}
                  </option>
                ))}
              </select>
              {checkingExistingRoadmap && (
                <p role="status" style={{ color: 'var(--color-text-muted)', marginTop: 8 }}>
                  Checking whether this learning path has already been generated...
                </p>
              )}
              {roadmapCheckError && (
                <div className="alert alert-error" role="alert" style={{ marginTop: 12 }}>
                  {roadmapCheckError}
                  <button
                    type="button"
                    className="btn btn-outline"
                    style={{ marginLeft: 12 }}
                    onClick={() => setRoadmapCheckAttempt((attempt) => attempt + 1)}
                  >
                    Retry
                  </button>
                </div>
              )}
              {existingRoadmap?.exists && (
                <div className="card" role="alert" style={{ marginTop: 16, padding: 20, border: '1px solid var(--color-warning, #d69e2e)' }}>
                  <h3 style={{ marginBottom: 8 }}>This learning path is already generated</h3>
                  <p style={{ color: 'var(--color-text-muted)', lineHeight: 1.6, marginBottom: 16 }}>
                    {existingRoadmap.goal_name || 'This learning path'} is already saved in your account. Delete the existing roadmap before generating it again.
                  </p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => navigate(`/roadmap/${encodeURIComponent(existingRoadmap.goal_id)}`)}
                    >
                      View Existing Roadmap
                    </button>
                    <button type="button" className="btn btn-outline" onClick={() => navigate('/saved-roadmaps')}>
                      Manage Saved Roadmaps
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 20, marginBottom: 24 }}>
              <div className="input-group">
                <label htmlFor="plan-experience">Experience Level</label>
                <select id="plan-experience" value={experience} onChange={(e) => setExperience(e.target.value)}>
                  {EXPERIENCE_OPTS.map((o) => (
                    <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div className="input-group">
                <label htmlFor="plan-style">Learning Style</label>
                <select id="plan-style" value={style} onChange={(e) => setStyle(e.target.value)}>
                  {STYLE_OPTS.map((o) => (
                    <option key={o} value={o}>{o.charAt(0).toUpperCase() + o.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div className="input-group">
                <label htmlFor="plan-hours">Hours Available Per Week</label>
                <input 
                  id="plan-hours"
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
              disabled={submitting || checkingExistingRoadmap || Boolean(existingRoadmap?.exists) || Boolean(roadmapCheckError)}
              style={{ width: '100%', padding: '16px', fontSize: '1rem' }}
            >
              {checkingExistingRoadmap ? 'Checking existing roadmap...' : existingRoadmap?.exists ? 'Roadmap Already Exists' : roadmapCheckError ? 'Unable to Verify Roadmap' : submitting ? 'Saving...' : (<>Continue to Skill Assessment <FiArrowRight size={18} /></>)}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
