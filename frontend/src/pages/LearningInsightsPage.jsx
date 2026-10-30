import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { FiCalendar, FiCheckCircle, FiDownload, FiRotateCw, FiTarget, FiTrash2 } from 'react-icons/fi';
import LoadingSpinner from '../components/LoadingSpinner';
import { createReminder, deleteReminder, downloadCalendar, getLearningAnalytics, getReminders, getReviewQueue, setReminderCompleted } from '../api/learning';

export default function LearningInsightsPage() {
  const { goalId } = useParams();
  const navigate = useNavigate();
  const [analytics, setAnalytics] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [title, setTitle] = useState('');
  const [dueAt, setDueAt] = useState('');
  const [loading, setLoading] = useState(true);
  const [reminderActionId, setReminderActionId] = useState(null);
  const [reminderError, setReminderError] = useState('');
  const [reminderMessage, setReminderMessage] = useState('');

  useEffect(() => {
    let active = true;
    Promise.all([getLearningAnalytics(goalId), getReviewQueue(goalId), getReminders()])
      .then(([analyticsResponse, reviewsResponse, remindersResponse]) => {
        if (!active) return;
        setAnalytics(analyticsResponse.data);
        setReviews(reviewsResponse.data);
        setReminders(remindersResponse.data);
        setLoading(false);
      })
      .catch(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [goalId]);


  const toggleReminder = async (reminder) => {
    const completed = !reminder.completed;
    setReminderActionId(reminder.id);
    setReminderError('');
    setReminderMessage('');
    try {
      await setReminderCompleted(reminder.id, completed);
      setReminders((current) => current.map((item) => item.id === reminder.id ? { ...item, completed } : item));
      setReminderMessage(completed ? 'Reminder marked complete.' : 'Reminder marked as not completed.');
    } catch (err) {
      setReminderError(err.response?.data?.detail || 'Could not update this reminder.');
    } finally {
      setReminderActionId(null);
    }
  };

  const removeReminder = async (reminder) => {
    if (!window.confirm(`Delete the reminder "${reminder.title}"? This cannot be undone.`)) return;
    setReminderActionId(reminder.id);
    setReminderError('');
    setReminderMessage('');
    try {
      await deleteReminder(reminder.id);
      setReminders((current) => current.filter((item) => item.id !== reminder.id));
      setReminderMessage('Reminder deleted.');
    } catch (err) {
      setReminderError(err.response?.data?.detail || 'Could not delete this reminder.');
    } finally {
      setReminderActionId(null);
    }
  };

  const download = async () => {
    const response = await downloadCalendar();
    const url = URL.createObjectURL(response.data);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'learning-path.ics';
    link.click();
    URL.revokeObjectURL(url);
  };

  const addReminder = async (event) => {
    event.preventDefault();
    await createReminder({ title, due_at: new Date(dueAt).toISOString(), goal_id: goalId });
    setTitle('');
    setDueAt('');
    setReminders((await getReminders()).data);
  };

  if (loading) return <LoadingSpinner message="Loading your learning insights..." />;

  return (
    <div className="page"><div className="container">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 28 }}>
        <div><h1>Learning Insights</h1><p style={{ color: 'var(--color-text-muted)' }}>Quiz trends, review timing, and study reminders.</p></div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><button className="btn btn-outline" onClick={() => navigate('/study-planner')}><FiCalendar size={15} /> Open study planner</button><button className="btn btn-outline" onClick={download}><FiDownload size={15} /> Add to calendar</button></div>
      </div>
      <div className="card" style={{ marginBottom: 24 }}>
        <h3 style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16 }}><FiTarget /> Quiz analytics</h3>
        <p style={{ color: 'var(--color-text-muted)', marginBottom: 18 }}>{analytics.total_attempts} quiz attempts recorded.</p>
        <div style={{ display: 'grid', gap: 12 }}>
          {analytics.by_phase.map((phase) => <div key={phase.phase_index} style={{ display: 'grid', gridTemplateColumns: 'minmax(140px, 1fr) 2fr auto', gap: 12, alignItems: 'center' }}>
            <strong style={{ fontSize: '.85rem' }}>{phase.phase_title}</strong>
            <div style={{ height: 8, background: '#e7e6df', borderRadius: 8 }}><div style={{ height: '100%', width: `${phase.average_score || 0}%`, background: 'var(--color-accent)', borderRadius: 8 }} /></div>
            <span style={{ fontSize: '.8rem', color: 'var(--color-text-muted)' }}>{phase.average_score === null ? 'No score' : `${phase.average_score}% avg`}</span>
          </div>)}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, alignItems: 'start' }}>
        <div className="card"><h3 style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14 }}><FiRotateCw /> Review queue</h3>{reviews.length === 0 ? <p style={{ color: 'var(--color-text-muted)' }}>Nothing is due right now.</p> : reviews.map((review) => <div key={review.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--color-border)' }}><strong>{review.skill_name}</strong><div style={{ fontSize: '.78rem', color: 'var(--color-text-muted)' }}>Last score: {review.last_score ?? '—'}%</div></div>)}</div>
        <div className="card">
          <h3 style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 14 }}><FiCalendar /> Reminders</h3>
          {reminderError && <div className="alert alert-error" role="alert" style={{ marginBottom: 10 }}>{reminderError}</div>}
          {reminderMessage && <div className="alert alert-success" role="status" style={{ marginBottom: 10 }}>{reminderMessage}</div>}
          <form onSubmit={addReminder} style={{ display: 'grid', gap: 8, marginBottom: 16 }}><input aria-label="Reminder title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Reminder title" required /><input aria-label="Reminder date and time" type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} required /><button className="btn btn-primary" type="submit">Add reminder</button></form>
          {reminders.length === 0 && <p style={{ color: 'var(--color-text-muted)', fontSize: '.9rem' }}>No reminders yet.</p>}
          {reminders.map((reminder) => <div key={reminder.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, padding: '10px 0', borderBottom: '1px solid var(--color-border)' }}>
            <div><span style={{ textDecoration: reminder.completed ? 'line-through' : 'none' }}>{reminder.title}</span><div style={{ color: 'var(--color-text-muted)', fontSize: '.75rem', marginTop: 3 }}>{new Date(reminder.due_at).toLocaleString()}</div></div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button type="button" className="badge badge-surface" style={{ border: 0, fontFamily: 'inherit', cursor: reminderActionId === reminder.id ? 'wait' : 'pointer', opacity: reminderActionId === reminder.id ? 0.65 : 1 }} disabled={reminderActionId === reminder.id} aria-pressed={Boolean(reminder.completed)} aria-label={`${reminder.completed ? 'Mark incomplete' : 'Mark complete'}: ${reminder.title}`} title={reminder.completed ? 'Click to mark this reminder incomplete' : 'Click to mark this reminder complete'} onClick={() => toggleReminder(reminder)}>{reminderActionId === reminder.id ? 'Saving…' : reminder.completed ? 'Completed' : 'Mark complete'}</button>
              <button className="btn btn-ghost" disabled={reminderActionId === reminder.id} aria-label={`Delete ${reminder.title}`} title="Delete reminder" onClick={() => removeReminder(reminder)}><FiTrash2 /> Delete</button>
            </div>
          </div>)}
        </div>
      </div>
    </div></div>
  );
}
