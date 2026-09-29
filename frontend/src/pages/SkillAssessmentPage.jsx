import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiSend, FiArrowRight, FiCheckCircle } from 'react-icons/fi';
import { extractSkills } from '../api/user';

const EXAMPLE_TEXTS = [
  "I've been working with Python for a year and know some Pandas.",
  "I've built static sites with HTML, CSS, and JavaScript.",
  "I'm comfortable with SQL and data analysis.",
];

export default function SkillAssessmentPage() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!text.trim()) {
      navigate('/roadmap');
      return;
    }
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await extractSkills(text);
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Skill extraction failed. Is your backend running?');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <div className="container">
        <div style={{ marginBottom: 36, textAlign: 'center' }}>
          <h1 style={{ fontSize: '1.9rem', marginBottom: 8 }}>Your Current Skills (Optional)</h1>
          <p style={{ color: 'var(--color-text-muted)' }}>
            Tell us about any skills you already know. If you are starting from scratch, just click Skip.
          </p>
        </div>

        <div className="card" style={{ marginBottom: 24 }}>
          <form onSubmit={handleSubmit}>
            <div className="input-group" style={{ marginBottom: 16 }}>
              <label>Describe your current skills (leave blank if none)</label>
              <textarea
                value={text}
                onChange={(e) => { setText(e.target.value); setError(''); }}
                placeholder="e.g. I have been working with Python for a year and know some Pandas..."
                style={{ minHeight: 140 }}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <p style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Try an example:
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {EXAMPLE_TEXTS.map((ex, i) => (
                  <button
                    key={i}
                    type="button"
                    className="badge badge-accent"
                    onClick={() => setText(ex)}
                    style={{ cursor: 'pointer', border: 'none', padding: '6px 14px', fontSize: '0.8rem' }}
                  >
                    Example {i + 1}
                  </button>
                ))}
              </div>
            </div>

            {error && <div className="alert alert-error" style={{ marginBottom: 12 }}>{error}</div>}

            <button className="btn btn-primary" type="submit" disabled={loading} style={{ width: '100%', padding: '16px', fontSize: '1rem' }}>
              {loading ? (
                <><span className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} /> Analyzing skills...</>
              ) : (
                <>{text.trim() ? <><FiSend size={16} /> Analyze My Skills</> : <>Skip & Generate Roadmap <FiArrowRight size={18} /></>}</>
              )}
            </button>
          </form>
        </div>

        {result && (
          <>
            <div className="skills-grid" style={{ marginBottom: 24 }}>
              <div className="card" style={{ gridColumn: '1 / -1' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                  <FiCheckCircle size={20} color="var(--color-success)" />
                  <h3 style={{ fontSize: '1rem' }}>Skills You Know</h3>
                  <span className="badge badge-primary" style={{ marginLeft: 'auto' }}>{result.extracted_skills?.length || 0}</span>
                </div>
                {(!result.extracted_skills || result.extracted_skills.length === 0) && (
                  <p style={{ color: 'var(--color-text-muted)', fontSize: '0.88rem' }}>No existing skills detected.</p>
                )}
                {result.extracted_skills && result.extracted_skills.map((s, i) => (
                  <div key={i} className="skill-item">
                    <span className="skill-name">{s.skill_name}</span>
                    <div className="confidence-bar">
                      <div className="confidence-fill" style={{ width: `${Math.round(s.confidence * 100)}%` }} />
                    </div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', minWidth: 32 }}>
                      {Math.round(s.confidence * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <button
              className="btn btn-primary"
              onClick={() => navigate('/roadmap')}
              style={{ width: '100%', padding: '16px', fontSize: '1rem' }}
            >
              Generate My Roadmap <FiArrowRight size={18} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
