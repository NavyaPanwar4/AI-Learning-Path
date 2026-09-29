import { useParams } from 'react-router-dom';
import { FiExternalLink, FiBook, FiCode, FiStar, FiX, FiRefreshCw, FiClock, FiCheckCircle, FiFileText, FiHelpCircle } from 'react-icons/fi';
import { generateRoadmap, submitFeedback, getSavedRoadmap, updatePhaseStatus, completeRoadmap, generateStudyNotes, generateQuiz, submitQuiz, insertRemedialPhase } from '../api/roadmap';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate } from 'react-router-dom';
import { useCallback, useRef, useState } from 'react';
import { useEffect } from 'react';
import useSessionTimer from '../hooks/useSessionTimer';

function StarRating({ value, onChange }) {
  const [hovered, setHovered] = useState(0);
  return (
    <div className="star-rating">
      {[1, 2, 3, 4, 5].map((s) => (
        <span
          key={s}
          className={`star ${s <= (hovered || value) ? 'active' : ''}`}
          onMouseEnter={() => setHovered(s)}
          onMouseLeave={() => setHovered(0)}
          onClick={() => onChange(s)}
        >★</span>
      ))}
    </div>
  );
}

function FeedbackModal({ resource, onClose }) {
  const [rating, setRating] = useState(0);
  const [comments, setComments] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const handleSubmit = async () => {
    if (!rating) return;
    setSubmitting(true);
    try {
      await submitFeedback({
        content_id: resource.url || resource.title,
        content_type: resource.type || 'resource',
        rating,
        comments,
      });
      setDone(true);
      setTimeout(onClose, 1500);
    } catch {
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(45,58,53,0.4)', backdropFilter: 'blur(4px)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div className="card" style={{ maxWidth: 440, width: '100%', position: 'relative' }}>
        <button onClick={onClose} style={{ position: 'absolute', top: 16, right: 16, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}>
          <FiX size={20} />
        </button>
        {done ? (
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <h3 style={{ marginTop: 16 }}>Thanks for your feedback!</h3>
          </div>
        ) : (
          <>
            <h3 style={{ marginBottom: 4 }}>Rate this resource</h3>
            <p style={{ color: 'var(--color-text-muted)', fontSize: '0.88rem', marginBottom: 20 }}>{resource.title}</p>
            <StarRating value={rating} onChange={setRating} />
            <div className="input-group" style={{ marginTop: 16, marginBottom: 20 }}>
              <label>Comments (optional)</label>
              <textarea value={comments} onChange={(e) => setComments(e.target.value)} placeholder="What did you think?" style={{ minHeight: 80 }} />
            </div>
            <button className="btn btn-primary" style={{ width: '100%' }} disabled={!rating || submitting} onClick={handleSubmit}>
              {submitting ? 'Submitting...' : 'Submit Feedback'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function StudyNotesCard({ notes }) {
  return (
    <section className="study-notes-card">
      <div className="study-notes-heading">
        <span className="study-notes-icon"><FiFileText size={17} /></span>
        <div>
          <span className="study-notes-label">AI study guide</span>
          <h4>{notes.title}</h4>
        </div>
      </div>
      <p className="study-notes-overview">{notes.overview}</p>

      <div className="study-notes-grid">
        {notes.learning_objectives?.length > 0 && (
          <div>
            <h5>What you&apos;ll learn</h5>
            <ul>{notes.learning_objectives.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </div>
        )}
        {notes.quick_recap?.length > 0 && (
          <div>
            <h5>Quick recap</h5>
            <ul>{notes.quick_recap.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </div>
        )}
      </div>

      {notes.key_concepts?.length > 0 && (
        <div className="study-notes-section">
          <h5>Key concepts</h5>
          <div className="concept-list">
            {notes.key_concepts.map((concept, index) => (
              <div key={index} className="concept-item"><strong>{concept.term}</strong><span>{concept.explanation}</span></div>
            ))}
          </div>
        </div>
      )}

      {notes.study_plan?.length > 0 && (
        <div className="study-notes-section">
          <h5>Your study plan</h5>
          <ol className="study-plan-list">
            {notes.study_plan.map((item, index) => <li key={index}><strong>{item.step}</strong><span>{item.action}</span></li>)}
          </ol>
        </div>
      )}

      {notes.practice_prompts?.length > 0 && (
        <div className="study-notes-section">
          <h5>Practice prompts</h5>
          <ul>{notes.practice_prompts.map((item, index) => <li key={index}>{item}</li>)}</ul>
        </div>
      )}
    </section>
  );
}

function QuizModal({ questions, phaseTitle, onClose, onSubmitScore, onAcceptRemedial }) {
  const [answers, setAnswers] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [skillsUpdated, setSkillsUpdated] = useState([]);
  const [recommendation, setRecommendation] = useState(null);
  const [addingRemedial, setAddingRemedial] = useState(false);
  const [remedialAdded, setRemedialAdded] = useState(false);

  const allAnswered = questions.every((_, i) => answers[i] !== undefined);
  const correctCount = questions.reduce((count, q, i) => count + (answers[i] === q.correct_index ? 1 : 0), 0);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const result = await onSubmitScore(questions.length, correctCount);
      setSkillsUpdated(result?.skills_updated || []);
      setRecommendation(result?.recommendation || null);
    } finally {
      setSubmitting(false);
      setSubmitted(true);
    }
  };

  const handleAddRemedial = async () => {
    setAddingRemedial(true);
    try {
      await onAcceptRemedial();
      setRemedialAdded(true);
    } finally {
      setAddingRemedial(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(45,58,53,0.4)', backdropFilter: 'blur(4px)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, overflowY: 'auto' }}>
      <div className="card" style={{ maxWidth: 560, width: '100%', position: 'relative', maxHeight: '85vh', overflowY: 'auto' }}>
        <button onClick={onClose} style={{ position: 'absolute', top: 16, right: 16, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}>
          <FiX size={20} />
        </button>
        <h3 style={{ marginBottom: 4 }}>Practice Quiz</h3>
        <p style={{ color: 'var(--color-text-muted)', fontSize: '0.88rem', marginBottom: 20 }}>{phaseTitle}</p>

        {submitted ? (
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <h2 style={{ marginBottom: 8 }}>{correctCount} / {questions.length} correct</h2>
            <p style={{ color: 'var(--color-text-muted)', marginBottom: 24 }}>Score: {Math.round((correctCount / questions.length) * 100)}%</p>
            {skillsUpdated.length > 0 && (
              <div style={{ textAlign: 'left', marginBottom: 20, padding: 14, borderRadius: 10, background: 'var(--color-accent-soft)' }}>
                <p style={{ fontWeight: 700, fontSize: '0.82rem', marginBottom: 6, color: '#a65241' }}>Skill mastery updated:</p>
                {skillsUpdated.map((s) => (
                  <p key={s.skill_name} style={{ fontSize: '0.82rem', color: '#a65241' }}>
                    {s.skill_name} → Level {s.new_level}/5 {s.direction === 'down' ? '↓' : '↑'}
                  </p>
                ))}
              </div>
            )}
            {recommendation?.type === 'remedial' && !remedialAdded && (
              <div style={{ textAlign: 'left', marginBottom: 20, padding: 14, borderRadius: 10, background: '#fdecea' }}>
                <p style={{ fontWeight: 700, fontSize: '0.82rem', marginBottom: 6, color: '#c0574a' }}>Recommendation</p>
                <p style={{ fontSize: '0.84rem', color: '#c0574a', marginBottom: 10 }}>{recommendation.message}</p>
                <button className="btn btn-outline" style={{ width: '100%' }} disabled={addingRemedial} onClick={handleAddRemedial}>
                  {addingRemedial ? 'Adding review phase...' : 'Add a Quick Review Phase'}
                </button>
              </div>
            )}
            {remedialAdded && (
              <div style={{ textAlign: 'left', marginBottom: 20, padding: 14, borderRadius: 10, background: '#eaf6ee' }}>
                <p style={{ fontSize: '0.84rem', color: '#4d9e6e' }}>Review phase added to your roadmap.</p>
              </div>
            )}
            <div style={{ display: 'grid', gap: 14, textAlign: 'left', marginBottom: 20 }}>
              {questions.map((q, i) => {
                const isCorrect = answers[i] === q.correct_index;
                return (
                  <div key={i} style={{ padding: 12, borderRadius: 8, background: isCorrect ? '#eaf6ee' : '#fdecea' }}>
                    <p style={{ fontWeight: 600, fontSize: '0.88rem', marginBottom: 4 }}>{q.question}</p>
                    <p style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>
                      Correct answer: {q.options[q.correct_index]}
                      {q.explanation ? ` — ${q.explanation}` : ''}
                    </p>
                  </div>
                );
              })}
            </div>
            <button className="btn btn-primary" style={{ width: '100%' }} onClick={onClose}>Close</button>
          </div>
        ) : (
          <>
            <div style={{ display: 'grid', gap: 20, marginBottom: 20 }}>
              {questions.map((q, i) => (
                <div key={i}>
                  <p style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: 10 }}>{i + 1}. {q.question}</p>
                  <div style={{ display: 'grid', gap: 8 }}>
                    {q.options.map((opt, oi) => (
                      <label
                        key={oi}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8,
                          border: `1px solid ${answers[i] === oi ? 'var(--color-primary)' : 'var(--color-surface-hover)'}`,
                          background: answers[i] === oi ? 'var(--color-accent)' : 'transparent',
                          cursor: 'pointer', fontSize: '0.86rem',
                        }}
                      >
                        <input
                          type="radio"
                          name={`quiz-q-${i}`}
                          checked={answers[i] === oi}
                          onChange={() => setAnswers((prev) => ({ ...prev, [i]: oi }))}
                        />
                        {opt}
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <button
              className="btn btn-primary"
              style={{ width: '100%' }}
              disabled={!allAnswered || submitting}
              onClick={handleSubmit}
            >
              {submitting ? 'Submitting...' : 'Submit Quiz'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function RoadmapPage() {
  const navigate = useNavigate();
  useSessionTimer();

  const [roadmap, setRoadmap] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [feedbackResource, setFeedbackResource] = useState(null);
  const [generatingNotes, setGeneratingNotes] = useState(null);
  const [notesError, setNotesError] = useState('');
  const [quizPhaseIndex, setQuizPhaseIndex] = useState(null);
  const [quizQuestions, setQuizQuestions] = useState([]);
  const [loadingQuiz, setLoadingQuiz] = useState(null);
  const [quizError, setQuizError] = useState('');
  const fetchedRoadmapKey = useRef(null);

  const { goalId } = useParams();

  const fetchRoadmap = useCallback(async () => {
    setLoading(true);
    setError('');
    setRoadmap(null);
    try {
      let res;
      if (goalId) {
        res = await getSavedRoadmap(goalId);
      } else {
        res = await generateRoadmap();
      }
      setRoadmap(res.data);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 400 || (detail && detail.includes('profile'))) {
        navigate('/onboarding');
      } else {
        setError(detail || 'Failed to generate or retrieve roadmap.');
      }
    } finally {
      setLoading(false);
    }
  }, [goalId, navigate]);

  const handlePhaseToggle = async (index, currentStatus) => {
    try {
      const res = await updatePhaseStatus(goalId || roadmap.goal_id || 'default', index, !currentStatus);
      setRoadmap(res.data);
    } catch (err) {
      console.error('Failed to update phase status', err);
    }
  };

  const handleCompleteRoadmap = async () => {
    try {
      const res = await completeRoadmap(goalId || roadmap.goal_id || 'default');
      setRoadmap(res.data);
      alert('Congratulations! Roadmap marked as complete.');
    } catch (err) {
      console.error('Failed to complete roadmap', err);
    }
  };

  const handleGenerateNotes = async (phaseIndex) => {
    setGeneratingNotes(phaseIndex);
    setNotesError('');
    try {
      const roadmapGoalId = goalId || roadmap?.goal_id;

      if (!roadmapGoalId) {
        throw new Error('The roadmap goal ID is missing. Please regenerate the roadmap.');
      }

      const res = await generateStudyNotes(roadmapGoalId, phaseIndex);
      setRoadmap((current) => ({
        ...current,
        phases: current.phases.map((phase, index) => index === phaseIndex ? { ...phase, ai_notes: res.data } : phase),
      }));
    } catch (err) {
      setNotesError(
        err.response?.data?.detail ||
        err.message ||
        'Could not generate study notes. Please try again.'
      );
    } finally {
      setGeneratingNotes(null);
    }
  };

  const handleTakeQuiz = async (phaseIndex) => {
    setLoadingQuiz(phaseIndex);
    setQuizError('');
    try {
      const roadmapGoalId = goalId || roadmap?.goal_id;

      if (!roadmapGoalId) {
        throw new Error('The roadmap goal ID is missing. Please regenerate the roadmap.');
      }

      const res = await generateQuiz(roadmapGoalId, phaseIndex);
      setQuizQuestions(res.data.questions);
      setQuizPhaseIndex(phaseIndex);
    } catch (err) {
      setQuizError(
        err.response?.data?.detail ||
        err.message ||
        'Could not generate a quiz right now. Please try again.'
      );
    } finally {
      setLoadingQuiz(null);
    }
  };

  const handleSubmitQuizScore = async (totalQuestions, correctAnswers) => {
    try {
      const roadmapGoalId = goalId || roadmap?.goal_id;

      if (!roadmapGoalId) {
        throw new Error('The roadmap goal ID is missing.');
      }

      const res = await submitQuiz(roadmapGoalId, quizPhaseIndex, totalQuestions, correctAnswers);
      return res.data;
    } catch (err) {
      console.error('Failed to record quiz attempt', err);
      return null;
    }
  };

  const handleAcceptRemedial = async () => {
    try {
      const roadmapGoalId = goalId || roadmap?.goal_id;
      if (!roadmapGoalId || quizPhaseIndex === null) return;

      const res = await insertRemedialPhase(roadmapGoalId, quizPhaseIndex);
      setRoadmap(res.data);
    } catch (err) {
      console.error('Failed to insert remedial phase', err);
    }
  };

  useEffect(() => {
    const requestKey = goalId || '__new-roadmap__';
    if (fetchedRoadmapKey.current === requestKey) return;
    fetchedRoadmapKey.current = requestKey;
    fetchRoadmap();
  }, [fetchRoadmap, goalId]);

  if (loading) return <LoadingSpinner message="Generating your personalized roadmap... This may take up to 30 seconds" />;

  if (error) return (
    <div className="page">
      <div className="container-sm" style={{ textAlign: 'center', paddingTop: 60 }}>
        <h2 style={{ marginBottom: 8 }}>Couldn't load roadmap</h2>
        <p style={{ color: 'var(--color-text-muted)', marginBottom: 24 }}>{error}</p>
        <button className="btn btn-primary" onClick={fetchRoadmap}><FiRefreshCw size={16} /> Try Again</button>
      </div>
    </div>
  );

  const phases = roadmap?.phases || [];
  const allPhasesComplete = phases.length > 0 && phases.every(p => p.completed);
  const isRoadmapFinished = roadmap?.is_complete;

  return (
    <div className="page">
      {feedbackResource && <FeedbackModal resource={feedbackResource} onClose={() => setFeedbackResource(null)} />}
      {quizPhaseIndex !== null && (
        <QuizModal
          questions={quizQuestions}
          phaseTitle={phases[quizPhaseIndex]?.title || ''}
          onClose={() => setQuizPhaseIndex(null)}
          onSubmitScore={handleSubmitQuizScore}
          onAcceptRemedial={handleAcceptRemedial}
        />
      )}

      <div className="container">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 36, flexWrap: 'wrap', gap: 16 }}>
          <div>
            <h1 style={{ fontSize: '1.9rem', marginBottom: 6, display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
              Your Learning Roadmap
              {isRoadmapFinished !== undefined && (
                <span className={`badge ${isRoadmapFinished ? 'badge-primary' : 'badge-surface'}`} style={{ fontSize: '0.9rem' }}>
                  {isRoadmapFinished ? 'Completed' : 'In Progress'}
                </span>
              )}
            </h1>
            <p style={{ color: 'var(--color-text-muted)' }}>
              {phases.length} phases • Personalized just for you
            </p>
          </div>
          <button className="btn btn-outline" onClick={fetchRoadmap} style={{ gap: 8 }}>
            <FiRefreshCw size={16} /> Regenerate
          </button>
        </div>

        {notesError && <div className="alert alert-error" style={{ marginBottom: 18 }}>{notesError}</div>}
        {quizError && <div className="alert alert-error" style={{ marginBottom: 18 }}>{quizError}</div>}

        {phases.length === 0 && !roadmap?.roadmap_text ? (
          <div className="card" style={{ textAlign: 'center', padding: 60 }}>
            <p style={{ color: 'var(--color-text-muted)' }}>No phases returned. Try adding more skills first!</p>
            <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => navigate('/skills')}>
              Add Skills
            </button>
          </div>
        ) : (
          <>
            {roadmap?.roadmap_text && (
              <div className="card" style={{ marginBottom: 24, padding: 32 }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '0.95rem', lineHeight: '1.6', color: 'var(--color-text)' }}>
                  {roadmap.roadmap_text}
                </pre>
              </div>
            )}

            {phases.length > 0 && (
              <div className="timeline">
                {phases.map((phase, i) => (
                  <div key={i} className="phase-card" style={{ animationDelay: `${i * 0.08}s` }}>
                    <div className="card">
                      <div className="phase-header">
                        <span className="badge badge-primary">Phase {i + 1}</span>
                        {phase.is_remedial && (
                          <span className="badge" style={{ background: '#fdecea', color: '#c0574a' }}>Review</span>
                        )}
                        <h3 className="phase-title" style={{ textDecoration: phase.completed ? 'line-through' : 'none', color: phase.completed ? 'var(--color-text-muted)' : 'inherit' }}>{phase.title}</h3>
                        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
                          {phase.duration && (
                            <span className="badge badge-accent" style={{ display: 'flex', alignItems: 'center', gap: 4 }}><FiClock size={12} /> {phase.duration}</span>
                          )}
                          <button
                            className={`btn ${phase.completed ? 'btn-primary' : 'btn-outline'}`}
                            style={{ padding: '4px 12px', fontSize: '0.75rem', height: 'auto', gap: 6 }}
                            onClick={() => handlePhaseToggle(i, phase.completed)}
                          >
                            <FiCheckCircle size={14} /> {phase.completed ? 'Completed' : 'Mark Complete'}
                          </button>
                          <button
                            className="btn btn-outline"
                            style={{ padding: '4px 12px', fontSize: '0.75rem', height: 'auto', gap: 6 }}
                            onClick={() => handleGenerateNotes(i)}
                            disabled={generatingNotes === i || !!phase.ai_notes}
                          >
                            <FiFileText size={14} /> {generatingNotes === i ? 'Creating notes...' : phase.ai_notes ? 'Study notes ready' : 'Generate study notes'}
                          </button>
                          <button
                            className="btn btn-outline"
                            style={{ padding: '4px 12px', fontSize: '0.75rem', height: 'auto', gap: 6 }}
                            onClick={() => handleTakeQuiz(i)}
                            disabled={loadingQuiz === i}
                          >
                            <FiHelpCircle size={14} /> {loadingQuiz === i ? 'Building quiz...' : 'Take Practice Quiz'}
                          </button>
                        </div>
                      </div>

                      {/* Skill Tags */}
                      {phase.skills?.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
                          {phase.skills.map((sk, si) => (
                            <span key={si} className="badge badge-surface">{sk}</span>
                          ))}
                        </div>
                      )}

                      {phase.ai_notes && <StudyNotesCard notes={phase.ai_notes} />}

                      <div className="phase-body">
                        {/* Resources */}
                        {phase.resources?.length > 0 && (
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
                              <FiBook size={15} color="var(--color-primary)" />
                              <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Resources</span>
                            </div>
                            {phase.resources.map((r, ri) => (
                              <div key={ri} className="resource-item">
                                <FiExternalLink size={14} className="resource-icon" />
                                <div style={{ flex: 1 }}>
                                  <a href={r.url} target="_blank" rel="noreferrer" style={{ fontSize: '0.88rem', fontWeight: 500, color: 'var(--color-text)', display: 'block' }}>
                                    {r.title}
                                  </a>
                                  {r.type && <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>{r.type}</span>}
                                </div>
                                <button
                                  onClick={() => setFeedbackResource(r)}
                                  title="Rate this resource"
                                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', padding: 4 }}
                                >
                                  <FiStar size={15} />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Projects */}
                        {phase.projects?.length > 0 && (
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
                              <FiCode size={15} color="var(--color-primary)" />
                              <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Projects</span>
                            </div>
                            {phase.projects.map((p, pi) => (
                              <div key={pi} className="resource-item">
                                <FiCode size={14} className="resource-icon" />
                                <div>
                                  <p style={{ fontSize: '0.88rem', fontWeight: 600, marginBottom: 2 }}>{p.title}</p>
                                  <p style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>{p.description}</p>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {phases.length > 0 && (
              <div className="card" style={{ marginTop: 40, padding: 32, textAlign: 'center', border: allPhasesComplete ? '2px solid var(--color-primary)' : '1px solid var(--color-surface-hover)' }}>
                <h3 style={{ marginBottom: 12 }}>Roadmap Completion</h3>
                <p style={{ color: 'var(--color-text-muted)', marginBottom: 24 }}>
                  {allPhasesComplete
                    ? "Great job! You've completed every phase in this roadmap."
                    : "Complete all phases to unlock the final roadmap feedback and completion."}
                </p>
                <div style={{ display: 'flex', justifyContent: 'center', gap: 16 }}>
                  <button
                    className="btn btn-primary"
                    disabled={!allPhasesComplete || isRoadmapFinished}
                    onClick={handleCompleteRoadmap}
                    style={{ opacity: allPhasesComplete ? 1 : 0.5 }}
                  >
                    {isRoadmapFinished ? 'Roadmap Completed!' : 'Mark Roadmap as Complete'}
                  </button>
                  <button
                    className="btn btn-outline"
                    disabled={!allPhasesComplete}
                    onClick={() => setFeedbackResource({ title: roadmap.goal_name || 'This Roadmap', type: 'roadmap', url: goalId })}
                    style={{ opacity: allPhasesComplete ? 1 : 0.5 }}
                  >
                    Submit Roadmap Feedback
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}