import { useParams } from 'react-router-dom';
import { FiExternalLink, FiBook, FiCode, FiStar, FiX, FiRefreshCw, FiClock, FiCheckCircle, FiFileText, FiHelpCircle, FiDownload, FiBarChart2, FiCalendar } from 'react-icons/fi';
import { generateRoadmap, submitFeedback, getSavedRoadmap, updatePhaseStatus, completeRoadmap, generateStudyNotes, generateQuiz, submitQuiz, insertRemedialPhase, downloadLearningReport } from '../api/roadmap';
import { setRoadmapDeadline } from '../api/learning';
import { explainQuizAnswer } from '../api/chat';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate } from 'react-router-dom';
import { useCallback, useRef, useState } from 'react';
import { useEffect } from 'react';
import useSessionTimer from '../hooks/useSessionTimer';

function formatDeadline(value) {
  if (!value) return '';
  const dateOnly = String(value).slice(0, 10);
  const date = new Date(`${dateOnly}T12:00:00`);
  return Number.isNaN(date.getTime())
    ? dateOnly
    : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function StarRating({ value, onChange }) {
  const [hovered, setHovered] = useState(0);
  return (
    <div className="star-rating">
      {[1, 2, 3, 4, 5].map((s) => (
        <button
          type="button"
          key={s}
          className={`star ${s <= (hovered || value) ? 'active' : ''}`}
          aria-label={`${s} star${s === 1 ? '' : 's'}`}
          onMouseEnter={() => setHovered(s)}
          onMouseLeave={() => setHovered(0)}
          onClick={() => onChange(s)}
        >★</button>
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
        content_type: 'resource',
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
        <button aria-label="Close feedback dialog" onClick={onClose} style={{ position: 'absolute', top: 16, right: 16, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}>
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
              <label htmlFor="feedback-comments">Comments (optional)</label>
              <textarea id="feedback-comments" value={comments} onChange={(e) => setComments(e.target.value)} placeholder="What did you think?" style={{ minHeight: 80 }} />
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

function QuizModal({ quizId, questions, phaseTitle, difficulty, onClose, onSubmitScore, onAcceptRemedial }) {
  const [answers, setAnswers] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [skillsUpdated, setSkillsUpdated] = useState([]);
  const [recommendation, setRecommendation] = useState(null);
  const [addingRemedial, setAddingRemedial] = useState(false);
  const [remedialAdded, setRemedialAdded] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [quizResult, setQuizResult] = useState(null);
  const [gradedQuestions, setGradedQuestions] = useState([]);
  const [explanations, setExplanations] = useState({});

  const handleExplain = async (q) => {
    setExplanations((prev) => ({ ...prev, [q.question_id]: { loading: true } }));
    try {
      const { data } = await explainQuizAnswer(quizId, q.question_id, q.selected_index);
      setExplanations((prev) => ({ ...prev, [q.question_id]: { text: data.reply } }));
    } catch (error) {
      const message = error?.response?.data?.detail || 'The tutor could not explain this right now. Please try again.';
      setExplanations((prev) => ({ ...prev, [q.question_id]: { error: message } }));
    }
  };

  const allAnswered = questions.every((question) => answers[question.question_id] !== undefined);

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError('');
    try {
      const submittedAnswers = questions.map((question) => ({
        question_id: question.question_id,
        selected_index: answers[question.question_id],
      }));
      const result = await onSubmitScore(quizId, submittedAnswers);
      if (!result) throw new Error('The quiz result could not be saved. Please try again.');
      setQuizResult(result);
      setGradedQuestions(result.graded_questions || []);
      setSkillsUpdated(result?.skills_updated || []);
      setRecommendation(result?.recommendation || null);
      setSubmitted(true);
    } catch (error) {
      setSubmitError(error.message || 'The quiz result could not be saved. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleAddRemedial = async () => {
    setAddingRemedial(true);
    try {
      await onAcceptRemedial();
      setRemedialAdded(true);
    } catch (error) {
      setSubmitError(error.message || 'The review phase could not be added. Please try again.');
    } finally {
      setAddingRemedial(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(45,58,53,0.4)', backdropFilter: 'blur(4px)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, overflowY: 'auto' }}>
      <div className="card" role="dialog" aria-modal="true" aria-labelledby="quiz-title" style={{ maxWidth: 560, width: '100%', position: 'relative', maxHeight: '85vh', overflowY: 'auto' }}>
        <button aria-label="Close quiz dialog" onClick={onClose} style={{ position: 'absolute', top: 16, right: 16, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}>
          <FiX size={20} />
        </button>
        <h3 id="quiz-title" style={{ marginBottom: 4 }}>Practice Quiz</h3>
        <p style={{ color: 'var(--color-text-muted)', fontSize: '0.88rem', marginBottom: 20 }}>{phaseTitle} <span className="badge badge-accent" style={{ marginLeft: 8 }}>{difficulty}</span></p>
        {submitError && <div className="alert alert-error" role="alert" style={{ marginBottom: 16 }}>{submitError}</div>}

        {submitted ? (
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <h2 style={{ marginBottom: 8 }}>{quizResult?.correct_answers ?? 0} / {quizResult?.total_questions ?? questions.length} correct</h2>
            <p style={{ color: 'var(--color-text-muted)', marginBottom: 24 }}>Score: {quizResult?.score_pct ?? 0}%</p>
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
              {gradedQuestions.map((q, i) => (
                <div key={q.question_id || i} style={{ padding: 12, borderRadius: 8, background: q.is_correct ? '#eaf6ee' : '#fdecea' }}>
                  <p style={{ fontWeight: 600, fontSize: '0.88rem', marginBottom: 4 }}>{q.question}</p>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-muted)' }}>
                    Your answer: {q.options[q.selected_index]} · Correct answer: {q.options[q.correct_index]}
                    {q.explanation ? ` — ${q.explanation}` : ''}
                  </p>
                  {!q.is_correct && !explanations[q.question_id]?.text && (
                    <button
                      className="btn btn-outline"
                      style={{ marginTop: 8, padding: '4px 10px', fontSize: '0.8rem' }}
                      disabled={explanations[q.question_id]?.loading}
                      onClick={() => handleExplain(q)}
                    >
                      {explanations[q.question_id]?.loading ? 'Asking the tutor...' : 'Explain this to me'}
                    </button>
                  )}
                  {explanations[q.question_id]?.error && (
                    <p style={{ marginTop: 6, fontSize: '0.8rem', color: '#c0574a' }}>{explanations[q.question_id].error}</p>
                  )}
                  {explanations[q.question_id]?.text && (
                    <p style={{ marginTop: 8, fontSize: '0.84rem', whiteSpace: 'pre-wrap' }}>{explanations[q.question_id].text}</p>
                  )}
                </div>
              ))}
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
                          border: `1px solid ${answers[q.question_id] === oi ? 'var(--color-primary)' : 'var(--color-surface-hover)'}`,
                          background: answers[q.question_id] === oi ? 'var(--color-accent)' : 'transparent',
                          cursor: 'pointer', fontSize: '0.86rem',
                        }}
                      >
                        <input
                          type="radio"
                          name={`quiz-q-${q.question_id}`}
                          checked={answers[q.question_id] === oi}
                          onChange={() => setAnswers((prev) => ({ ...prev, [q.question_id]: oi }))}
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
  const [generationStatus, setGenerationStatus] = useState('queued');
  const [error, setError] = useState('');
  const [feedbackResource, setFeedbackResource] = useState(null);
  const [generatingNotes, setGeneratingNotes] = useState(null);
  const [notesError, setNotesError] = useState('');
  const [quizPhaseIndex, setQuizPhaseIndex] = useState(null);
  const [quizQuestions, setQuizQuestions] = useState([]);
  const [quizId, setQuizId] = useState(null);
  const [quizDifficulty, setQuizDifficulty] = useState('beginner');
  const [loadingQuiz, setLoadingQuiz] = useState(null);
  const [quizError, setQuizError] = useState('');
  const [deadlineDraft, setDeadlineDraft] = useState('');
  const [managementBusy, setManagementBusy] = useState(false);
  const [managementError, setManagementError] = useState('');
  const [managementMessage, setManagementMessage] = useState('');
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
        res = await generateRoadmap({ onStatus: setGenerationStatus });
      }
      setRoadmap(res.data);
      setDeadlineDraft(typeof res.data.deadline === 'string' ? res.data.deadline.slice(0, 10) : '');
      setManagementError('');
      setManagementMessage('');
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 400 || (detail && detail.includes('profile'))) {
        navigate('/onboarding');
      } else {
        setError(detail || err.message || 'Failed to generate or retrieve roadmap.');
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
      setQuizId(res.data.quiz_id);
      setQuizDifficulty(res.data.difficulty || 'beginner');
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

  const getCurrentGoalId = () => goalId || roadmap?.goal_id;

  const handleSaveDeadline = async () => {
    const roadmapGoalId = getCurrentGoalId();
    if (!roadmapGoalId) {
      setManagementError('This roadmap does not have a goal ID yet. Open a saved roadmap and try again.');
      return;
    }
    if (!deadlineDraft) {
      setManagementError('Choose a target completion date, or use Remove deadline to clear the saved date.');
      return;
    }
    setManagementBusy(true);
    setManagementError('');
    setManagementMessage('');
    try {
      const response = await setRoadmapDeadline(roadmapGoalId, deadlineDraft);
      setRoadmap(response.data);
      const savedDeadline = typeof response.data.deadline === 'string' ? response.data.deadline.slice(0, 10) : deadlineDraft;
      setDeadlineDraft(savedDeadline);
      setManagementMessage(`Target completion date saved: ${formatDeadline(savedDeadline)}.`);
    } catch (err) {
      setManagementError(err.response?.data?.detail || 'Could not save the roadmap deadline.');
    } finally {
      setManagementBusy(false);
    }
  };

  const handleRemoveDeadline = async () => {
    const roadmapGoalId = getCurrentGoalId();
    if (!roadmapGoalId) {
      setManagementError('This roadmap does not have a goal ID yet. Open a saved roadmap and try again.');
      return;
    }
    if (!roadmap?.deadline) {
      setDeadlineDraft('');
      return;
    }
    if (!window.confirm(`Remove the target completion date${formatDeadline(roadmap.deadline) ? ` (${formatDeadline(roadmap.deadline)})` : ''}?`)) return;
    setManagementBusy(true);
    setManagementError('');
    setManagementMessage('');
    try {
      const response = await setRoadmapDeadline(roadmapGoalId, null);
      setRoadmap(response.data);
      setDeadlineDraft('');
      setManagementMessage('Target completion date removed.');
    } catch (err) {
      setManagementError(err.response?.data?.detail || 'Could not remove the roadmap deadline.');
    } finally {
      setManagementBusy(false);
    }
  };

  const handleDownloadReport = async () => {
    const roadmapGoalId = goalId || roadmap?.goal_id;
    if (!roadmapGoalId) return;
    try {
      const res = await downloadLearningReport(roadmapGoalId);
      const url = URL.createObjectURL(res.data);
      const link = document.createElement('a');
      link.href = url;
      link.download = `learning-report-${roadmapGoalId}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not generate your learning report.');
    }
  };

  const handleSubmitQuizScore = async (issuedQuizId, answers) => {
    const roadmapGoalId = goalId || roadmap?.goal_id;

    if (!roadmapGoalId) {
      throw new Error('The roadmap goal ID is missing.');
    }
    if (!issuedQuizId) {
      throw new Error('The quiz session is missing. Please generate a new quiz.');
    }

    const res = await submitQuiz(roadmapGoalId, quizPhaseIndex, issuedQuizId, answers);
    return res.data;
  };

  const handleAcceptRemedial = async () => {
    const roadmapGoalId = goalId || roadmap?.goal_id;
    if (!roadmapGoalId || quizPhaseIndex === null) throw new Error('The roadmap goal ID is missing.');

    const res = await insertRemedialPhase(roadmapGoalId, quizPhaseIndex);
    setRoadmap(res.data);
  };

  useEffect(() => {
    const requestKey = goalId || '__new-roadmap__';
    if (fetchedRoadmapKey.current === requestKey) return;
    fetchedRoadmapKey.current = requestKey;
    fetchRoadmap();
  }, [fetchRoadmap, goalId]);

  if (loading) return <LoadingSpinner message={goalId
    ? "Loading your saved roadmap..."
    : `Roadmap generation ${generationStatus}. This may take a few minutes.`} />;

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
          quizId={quizId}
          questions={quizQuestions}
          phaseTitle={phases[quizPhaseIndex]?.title || ''}
          difficulty={quizDifficulty}
          onClose={() => setQuizPhaseIndex(null)}
          onSubmitScore={handleSubmitQuizScore}
          onAcceptRemedial={handleAcceptRemedial}
        />
      )}

      <div className="container">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 36, flexWrap: 'wrap', gap: 16 }}>
          <div style={{ minWidth: 0, flex: '1 1 320px' }}>
            <p style={{ margin: '0 0 6px', color: 'var(--color-text-muted)', fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
              Currently viewing
            </p>
            <h1 style={{ fontSize: '1.9rem', lineHeight: 1.2, marginBottom: 8, display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', overflowWrap: 'anywhere' }}>
              {roadmap?.goal_name || 'Your Learning Roadmap'}
              {isRoadmapFinished !== undefined && (
                <span className={`badge ${isRoadmapFinished ? 'badge-primary' : 'badge-surface'}`} style={{ fontSize: '0.9rem' }}>
                  {isRoadmapFinished ? 'Completed' : 'In Progress'}
                </span>
              )}
              {roadmap?.deadline && (
                <span className="badge badge-accent roadmap-target-badge" title="Target completion date">
                  Target: {formatDeadline(roadmap.deadline)}
                </span>
              )}
            </h1>
            <p style={{ color: 'var(--color-text-muted)' }}>
              Learning roadmap • {phases.length} phases • Personalized just for you
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn btn-outline" onClick={handleDownloadReport} style={{ gap: 8 }}>
              <FiDownload size={16} /> Learning Report
            </button>
            <button className="btn btn-outline" onClick={() => navigate(`/insights/${goalId || roadmap?.goal_id}`)} style={{ gap: 8 }}>
              <FiBarChart2 size={16} /> Insights
            </button>
            <button className="btn btn-outline" onClick={fetchRoadmap} style={{ gap: 8 }}>
              <FiRefreshCw size={16} /> Refresh
            </button>
          </div>
        </div>

        {notesError && <div className="alert alert-error" style={{ marginBottom: 18 }}>{notesError}</div>}
        {quizError && <div className="alert alert-error" style={{ marginBottom: 18 }}>{quizError}</div>}
        {managementError && <div className="alert alert-error" role="alert" style={{ marginBottom: 18 }}>{managementError}</div>}
        {managementMessage && <div className="alert alert-success" role="status" style={{ marginBottom: 18 }}>{managementMessage}</div>}

        <section className="card roadmap-management-card" aria-labelledby="roadmap-management-title">
          <div className="roadmap-management-heading">
            <div>
              <h3 id="roadmap-management-title"><FiCalendar /> Plan and manage</h3>
              <p>Set or update your target completion date, or remove it when your schedule changes.</p>
            </div>
            <button className="btn btn-outline roadmap-planner-link" onClick={() => navigate('/study-planner')}>
              <FiCalendar size={15} /> Study planner
            </button>
          </div>

          <div className="roadmap-current-deadline" role="status" aria-live="polite">
            <span className="roadmap-current-deadline-label">Current target completion date</span>
            {roadmap?.deadline ? (
              <strong>{formatDeadline(roadmap.deadline)}</strong>
            ) : (
              <span className="roadmap-no-deadline">No target date set</span>
            )}
          </div>

          <form className="roadmap-deadline-form" onSubmit={(event) => { event.preventDefault(); handleSaveDeadline(); }}>
            <div className="input-group roadmap-deadline-field">
              <label htmlFor="roadmap-deadline">Target completion date</label>
              <input
                id="roadmap-deadline"
                type="date"
                value={deadlineDraft}
                onChange={(event) => { setDeadlineDraft(event.target.value); setManagementMessage(''); setManagementError(''); }}
              />
            </div>
            <div className="roadmap-deadline-actions">
              <button className="btn btn-primary" type="submit" disabled={managementBusy || !deadlineDraft}>
                {managementBusy ? 'Saving…' : 'Save deadline'}
              </button>
              {roadmap?.deadline && (
                <button className="btn btn-ghost" type="button" disabled={managementBusy} onClick={handleRemoveDeadline}>
                  Remove deadline
                </button>
              )}
            </div>
          </form>
        </section>

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