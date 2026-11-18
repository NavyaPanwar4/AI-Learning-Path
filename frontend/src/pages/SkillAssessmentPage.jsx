import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiSend, FiArrowRight, FiCheckCircle, FiShield, FiAlertCircle } from 'react-icons/fi';
import { extractSkills, getMyProfile } from '../api/user';
import {
  getPendingMasteryVerifications,
  issueMasteryVerificationQuiz,
  submitMasteryVerificationQuiz,
} from '../api/roadmap';

const EXAMPLE_TEXTS = [
  "I've been working with Python for a year and know some Pandas.",
  "I've built static sites with HTML, CSS, and JavaScript.",
  "I'm comfortable with SQL and data analysis.",
];

const uniqueSkills = (skills) => Array.from(new Map((skills || []).map((skill) => [
  skill.matched_skill_id || skill.skill_name.trim().toLowerCase(), skill,
])).values());

const aspectLabel = (aspect) => String(aspect || '').replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export default function SkillAssessmentPage() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [goalId, setGoalId] = useState(null);
  const [pendingSkills, setPendingSkills] = useState([]);
  const [activeSkill, setActiveSkill] = useState(null);
  const [activeQuiz, setActiveQuiz] = useState(null);
  const [answers, setAnswers] = useState({});
  const [issuing, setIssuing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [verificationResult, setVerificationResult] = useState(null);

  const refreshPending = async (selectedGoalId = null) => {
    let id = selectedGoalId || goalId;
    if (!id) {
      const profile = await getMyProfile();
      id = profile.data?.goal_id;
      setGoalId(id || null);
    }
    if (!id) {
      setPendingSkills([]);
      return [];
    }
    const response = await getPendingMasteryVerifications(id);
    const pending = response.data?.pending_skills || [];
    setPendingSkills(pending);
    return pending;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    setResult(null);
    setPendingSkills([]);
    setVerificationResult(null);
    setActiveQuiz(null);
    setActiveSkill(null);
    try {
      if (text.trim()) {
        const response = await extractSkills(text);
        setResult(response.data);
      } else {
        setResult({ extracted_skills: [], desired_skills: [] });
      }
      const profile = await getMyProfile();
      const id = profile.data?.goal_id;
      setGoalId(id || null);
      const pending = id ? await refreshPending(id) : [];
      if (!text.trim() && pending.length === 0) navigate('/roadmap');
    } catch (err) {
      setError(err.response?.data?.detail?.message || err.response?.data?.detail || err.message || 'Unable to analyze skills. Is your backend running?');
    } finally {
      setLoading(false);
    }
  };

  const startVerification = async (skill) => {
    if (!goalId) return;
    setIssuing(true);
    setError('');
    setVerificationResult(null);
    try {
      const response = await issueMasteryVerificationQuiz(goalId, skill.skill_id);
      setActiveSkill(skill);
      setActiveQuiz(response.data);
      setAnswers({});
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not generate the verification quiz. Please try again.');
    } finally {
      setIssuing(false);
    }
  };

  const handleVerificationSubmit = async (e) => {
    e.preventDefault();
    if (!activeQuiz || !activeSkill || !goalId) return;
    if (Object.keys(answers).length !== activeQuiz.questions.length) {
      setError('Answer all five questions before submitting.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const payload = activeQuiz.questions.map((question) => ({
        question_id: question.question_id,
        selected_index: Number(answers[question.question_id]),
      }));
      const response = await submitMasteryVerificationQuiz(goalId, activeSkill.skill_id, activeQuiz.quiz_id, payload);
      setVerificationResult(response.data);
      setActiveQuiz(null);
      setActiveSkill(null);
      await refreshPending(goalId);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not submit the verification quiz. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const continueToRoadmap = async () => {
    setLoading(true);
    setError('');
    try {
      const pending = await refreshPending();
      if (pending.length) {
        setError('Complete the required mastery verification quizzes before generating your roadmap.');
        return;
      }
      navigate('/roadmap');
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not check mastery verification status. Please try again.');
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
                {EXAMPLE_TEXTS.map((example, index) => (
                  <button
                    key={index}
                    type="button"
                    className="badge badge-accent"
                    onClick={() => setText(example)}
                    style={{ cursor: 'pointer', border: 'none', padding: '6px 14px', fontSize: '0.8rem' }}
                  >
                    Example {index + 1}
                  </button>
                ))}
              </div>
            </div>
            {error && <div className="alert alert-error" style={{ marginBottom: 12 }}>{error}</div>}
            <button className="btn btn-primary" type="submit" disabled={loading} style={{ width: '100%', padding: '16px', fontSize: '1rem' }}>
              {loading ? (
                <><span className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} /> Checking skills...</>
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
                  <h3 style={{ fontSize: '1rem' }}>Skills Identified</h3>
                  <span className="badge badge-primary" style={{ marginLeft: 'auto' }}>{uniqueSkills(result.extracted_skills).length}</span>
                </div>
                {(!result.extracted_skills || result.extracted_skills.length === 0) && (
                  <p style={{ color: 'var(--color-text-muted)', fontSize: '0.88rem' }}>No skills were mentioned in your description.</p>
                )}
                {uniqueSkills(result.extracted_skills).map((skill, index) => (
                  <div key={index} className="skill-item">
                    <span className="skill-name">{skill.skill_name}</span>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 110 }}>
                      <span style={{ fontSize: '0.68rem', color: 'var(--color-text-muted)' }}>Match confidence</span>
                      <div className="confidence-bar">
                        <div className="confidence-fill" style={{ width: `${Math.round(skill.confidence * 100)}%` }} />
                      </div>
                    </div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', minWidth: 32 }}>
                      {Math.round(skill.confidence * 100)}%
                    </span>
                  </div>
                ))}
                <p style={{ color: 'var(--color-text-muted)', fontSize: '0.8rem', lineHeight: 1.5, marginTop: 14, marginBottom: 0 }}>
                  Match confidence shows how confidently Traject matched a mentioned skill to its catalogue. It is not a measure of your proficiency or mastery.
                </p>
              </div>
            </div>

            {pendingSkills.length > 0 && (
              <div className="card" style={{ marginBottom: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 10 }}>
                  <FiShield size={20} color="var(--color-warning, #c58b28)" />
                  <h3 style={{ fontSize: '1rem', margin: 0 }}>Mastery Verification Required</h3>
                  <span className="badge badge-primary" style={{ marginLeft: 'auto' }}>{pendingSkills.length}</span>
                </div>
                <p style={{ color: 'var(--color-text-muted)', fontSize: '0.86rem', lineHeight: 1.5 }}>
                  These skills have a high estimated mastery probability, but have not yet been verified. Pass a five-question quiz covering different aspects of each skill to let Traject skip it in your roadmap.
                </p>
                {pendingSkills.map((skill) => (
                  <div key={skill.skill_id} className="skill-item" style={{ justifyContent: 'space-between', gap: 12 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                      <strong>{skill.skill_name}</strong>
                      <span style={{ color: 'var(--color-text-muted)', fontSize: '0.76rem' }}>Provisional mastery: {skill.mastery_pct}%</span>
                    </div>
                    <button className="btn btn-secondary" type="button" disabled={issuing || !!activeQuiz} onClick={() => startVerification(skill)}>
                      {issuing ? 'Preparing...' : 'Verify skill'}
                    </button>
                  </div>
                ))}
              </div>
            )}

            {activeQuiz && activeSkill && (
              <div className="card" style={{ marginBottom: 24 }}>
                <h3 style={{ marginTop: 0, marginBottom: 6 }}>Verify {activeSkill.skill_name}</h3>
                <p style={{ color: 'var(--color-text-muted)', fontSize: '0.85rem', marginTop: 0 }}>
                  Five questions cover core concepts, practical application, debugging, edge cases, and best practices. You need at least 4 correct answers (80%) to verify this skill.
                </p>
                <form onSubmit={handleVerificationSubmit}>
                  {activeQuiz.questions.map((question, index) => (
                    <div key={question.question_id} style={{ borderTop: '1px solid var(--color-border)', padding: '18px 0' }}>
                      <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', marginBottom: 7 }}>
                        Question {index + 1} · {aspectLabel(question.aspect)}
                      </div>
                      <p style={{ fontWeight: 600, marginTop: 0 }}>{question.question}</p>
                      <div style={{ display: 'grid', gap: 8 }}>
                        {question.options.map((option, optionIndex) => (
                          <label key={optionIndex} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '9px 12px', border: '1px solid var(--color-border)', borderRadius: 8, cursor: 'pointer' }}>
                            <input
                              type="radio"
                              name={question.question_id}
                              checked={String(answers[question.question_id]) === String(optionIndex)}
                              onChange={() => setAnswers((current) => ({ ...current, [question.question_id]: optionIndex }))}
                            />
                            <span>{option}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                  {error && <div className="alert alert-error" style={{ marginBottom: 12 }}>{error}</div>}
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <button className="btn btn-primary" type="submit" disabled={submitting}>
                      {submitting ? 'Submitting...' : 'Submit verification'}
                    </button>
                    <button className="btn btn-secondary" type="button" disabled={submitting} onClick={() => { setActiveQuiz(null); setActiveSkill(null); setAnswers({}); }}>
                      Cancel
                    </button>
                  </div>
                </form>
              </div>
            )}

            {verificationResult && (
              <div className="card" style={{ marginBottom: 24 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  {verificationResult.passed ? <FiCheckCircle color="var(--color-success)" size={20} /> : <FiAlertCircle color="var(--color-warning, #c58b28)" size={20} />}
                  <h3 style={{ margin: 0 }}>{verificationResult.passed ? 'Skill Verified' : 'Skill Not Yet Verified'}</h3>
                </div>
                <p style={{ margin: 0 }}>{verificationResult.message}</p>
                <p style={{ color: 'var(--color-text-muted)', fontSize: '0.82rem', marginBottom: 0 }}>
                  Score: {verificationResult.correct_answers}/{verificationResult.total_questions} ({verificationResult.score_pct}%). Updated BKT mastery: {verificationResult.mastery_pct}%.
                </p>
              </div>
            )}

            <button
              className="btn btn-primary"
              onClick={continueToRoadmap}
              disabled={loading || !!activeQuiz || pendingSkills.length > 0}
              style={{ width: '100%', padding: '16px', fontSize: '1rem' }}
            >
              {pendingSkills.length > 0 ? 'Verify skills to continue' : 'Generate My Roadmap'} <FiArrowRight size={18} />
            </button>
            {pendingSkills.length > 0 && (
              <p style={{ color: 'var(--color-text-muted)', fontSize: '0.78rem', textAlign: 'center', marginTop: 8 }}>
                You can continue after each provisionally mastered skill has been verified. Failed verifications will be included in your roadmap for revision.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
