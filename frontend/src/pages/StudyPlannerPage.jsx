import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FiCalendar, FiCheckCircle, FiCopy, FiDownload, FiExternalLink, FiRotateCw, FiTarget, FiTrash2 } from 'react-icons/fi';
import LoadingSpinner from '../components/LoadingSpinner';
import {
  createReminder, createShareLink, deleteReminder, downloadCalendar, getEmailPreferences, getReminders,
  getReviewQueue, getShareLink, revokeShareLink, setEmailPreferences, setReminderCompleted,
} from '../api/learning';
import { getSavedRoadmaps } from '../api/roadmap';

function formatDate(value) {
  if (!value) return 'Date unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function downloadBlob(response, filename) {
  const url = URL.createObjectURL(response.data);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function StudyPlannerPage() {
  const navigate = useNavigate();
  const [reviews, setReviews] = useState([]);
  const [showAllReviews, setShowAllReviews] = useState(false);
  const [reminders, setReminders] = useState([]);
  const [roadmaps, setRoadmaps] = useState([]);
  const [title, setTitle] = useState('');
  const [dueAt, setDueAt] = useState('');
  const [goalId, setGoalId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reminderActionId, setReminderActionId] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [emailPrefs, setEmailPrefs] = useState(null);
  const [shareGoalId, setShareGoalId] = useState('');
  const [shareToken, setShareToken] = useState(null);
  const [shareBusy, setShareBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const loadData = useCallback(async () => {
    setError('');
    const [reviewsResult, remindersResult, roadmapsResult] = await Promise.allSettled([
      getReviewQueue(), getReminders(), getSavedRoadmaps(),
    ]);
    const failures = [];
    if (reviewsResult.status === 'fulfilled') setReviews(reviewsResult.value.data || []);
    else failures.push('review queue');
    if (remindersResult.status === 'fulfilled') setReminders(remindersResult.value.data || []);
    else failures.push('reminders');
    if (roadmapsResult.status === 'fulfilled') setRoadmaps(roadmapsResult.value.data || []);
    else failures.push('saved roadmaps');
    if (failures.length) setError(`Some planner data could not be loaded: ${failures.join(', ')}. Try refreshing the page.`);
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);
  useEffect(() => { getEmailPreferences().then((res) => setEmailPrefs(res.data)).catch(() => setEmailPrefs(null)); }, []);
  useEffect(() => {
    if (!shareGoalId) { setShareToken(null); return; }
    let active = true;
    getShareLink(shareGoalId).then((res) => { if (active) setShareToken(res.data.token); }).catch(() => { if (active) setShareToken(null); });
    return () => { active = false; };
  }, [shareGoalId]);

  const shareUrl = shareToken ? `${window.location.origin}/share/${shareToken}` : '';

  const handleToggleEmails = async () => {
    setError('');
    try {
      const next = !emailPrefs.email_reminders;
      await setEmailPreferences(next);
      setEmailPrefs((current) => ({ ...current, email_reminders: next }));
      setMessage(next ? 'Email reminders turned on.' : 'Email reminders turned off.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update email reminders.');
    }
  };

  const handleCreateShare = async () => {
    setShareBusy(true); setError('');
    try { setShareToken((await createShareLink(shareGoalId)).data.token); setMessage('Sharing is on. Anyone with the link can view your progress.'); }
    catch (err) { setError(err.response?.data?.detail || 'Could not create a share link.'); }
    finally { setShareBusy(false); }
  };

  const handleRevokeShare = async () => {
    setShareBusy(true); setError('');
    try { await revokeShareLink(shareGoalId); setShareToken(null); setMessage('Sharing turned off. The old link no longer works.'); }
    catch (err) { setError(err.response?.data?.detail || 'Could not turn off sharing.'); }
    finally { setShareBusy(false); }
  };

  const handleCopyShare = async () => {
    try { await navigator.clipboard.writeText(shareUrl); setMessage('Link copied.'); }
    catch { setMessage('Copy failed — select the link and copy it manually.'); }
  };

  const handleCreateReminder = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    setMessage('');
    try {
      await createReminder({
        title: title.trim(),
        due_at: new Date(dueAt).toISOString(),
        goal_id: goalId || null,
      });
      setTitle('');
      setDueAt('');
      setMessage('Reminder created.');
      setReminders((await getReminders()).data || []);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Could not create reminder.');
    } finally {
      setSaving(false);
    }
  };

  const handleToggleReminder = async (reminder) => {
    const completed = !reminder.completed;
    setReminderActionId(reminder.id);
    setError('');
    setMessage('');
    try {
      await setReminderCompleted(reminder.id, completed);
      setReminders((current) => current.map((item) => item.id === reminder.id ? { ...item, completed } : item));
      setMessage(completed ? 'Reminder marked complete.' : 'Reminder marked as not completed.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not update this reminder.');
    } finally {
      setReminderActionId(null);
    }
  };

  const handleDeleteReminder = async (reminder) => {
    if (!window.confirm(`Delete the reminder "${reminder.title}"? This cannot be undone.`)) return;
    setReminderActionId(reminder.id);
    setError('');
    setMessage('');
    try {
      await deleteReminder(reminder.id);
      setReminders((current) => current.filter((item) => item.id !== reminder.id));
      setMessage('Reminder deleted.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not delete this reminder.');
    } finally {
      setReminderActionId(null);
    }
  };

  const handleDownloadCalendar = async () => {
    setDownloading(true);
    setError('');
    try {
      const response = await downloadCalendar();
      downloadBlob(response, 'learning-path.ics');
      setMessage('Calendar file downloaded. Import the .ics file into your calendar app.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not download your calendar file.');
    } finally {
      setDownloading(false);
    }
  };

  if (loading) return <LoadingSpinner message="Loading your study planner..." />;

  const visibleReviews = showAllReviews ? reviews : reviews.slice(0, 2);
  // Keep all reminders in one keyed list so the same completion button remains
  // available when a reminder changes state. Active reminders appear first.
  const orderedReminders = [...reminders].sort(
    (a, b) => Number(Boolean(a.completed)) - Number(Boolean(b.completed)),
  );

  return (
    <div className="page">
      <div className="container">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 26 }}>
          <div>
            <h1 style={{ fontSize: '1.9rem', marginBottom: 6 }}>Study Planner</h1>
            <p style={{ color: 'var(--color-text-muted)' }}>Manage reminders and see which skills are due for review.</p>
          </div>
          <button className="btn btn-outline" onClick={handleDownloadCalendar} disabled={downloading}>
            <FiDownload size={16} /> {downloading ? 'Preparing calendar…' : 'Export calendar (.ics)'}
          </button>
        </div>

        {error && <div className="alert alert-error" role="alert" style={{ marginBottom: 16 }}>{error}</div>}
        {message && <div className="alert alert-success" role="status" style={{ marginBottom: 16 }}>{message}</div>}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(290px, 1fr))', gap: 20, alignItems: 'start' }}>
          <section className="card">
            <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '1.1rem', marginBottom: 16 }}><FiCalendar /> Create a reminder</h2>
            <form onSubmit={handleCreateReminder} style={{ display: 'grid', gap: 12 }}>
              <div className="input-group" style={{ marginBottom: 0 }}>
                <label htmlFor="reminder-title">Reminder title</label>
                <input id="reminder-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={160} placeholder="e.g. Revise neural networks" required />
              </div>
              <div className="input-group" style={{ marginBottom: 0 }}>
                <label htmlFor="reminder-due">Date and time</label>
                <input id="reminder-due" type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} required />
              </div>
              <div className="input-group" style={{ marginBottom: 0 }}>
                <label htmlFor="reminder-roadmap">Link to roadmap (optional)</label>
                <select id="reminder-roadmap" value={goalId} onChange={(event) => setGoalId(event.target.value)}>
                  <option value="">General study reminder</option>
                  {roadmaps.map((roadmap) => <option key={roadmap.goal_id} value={roadmap.goal_id}>{roadmap.goal_name || roadmap.goal_id}</option>)}
                </select>
              </div>
              <button className="btn btn-primary" type="submit" disabled={saving || !title.trim() || !dueAt}>{saving ? 'Creating…' : 'Create reminder'}</button>
            </form>
          </section>

          <section className="card">
            <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '1.1rem', marginBottom: 16 }}><FiRotateCw /> Due for review <span className="badge badge-accent">{reviews.length}</span></h2>
            {reviews.length === 0 ? (
              <p style={{ color: 'var(--color-text-muted)', fontSize: '.9rem' }}>Nothing is due for review right now. Quiz results can schedule future reviews.</p>
            ) : (
              <div style={{ display: 'grid', gap: 10 }}>
                {visibleReviews.map((review) => (
                  <div key={review.id} style={{ padding: 12, border: '1px solid var(--color-border)', borderRadius: 10 }}>
                    <strong>{review.skill_name}</strong>
                    <p style={{ color: 'var(--color-text-muted)', fontSize: '.8rem', marginTop: 4 }}>Due {formatDate(review.due_at)} · Last score: {review.last_score ?? '—'}%</p>
                    <button className="btn btn-ghost" style={{ marginTop: 8 }} onClick={() => navigate(`/roadmap/${review.goal_id}`)}><FiExternalLink size={14} /> Open roadmap</button>
                  </div>
                ))}
              </div>
            )}

            {reviews.length > 2 && (
              <div style={{ display: 'flex', justifyContent: 'center', marginTop: 12 }}>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setShowAllReviews((current) => !current)}
                  aria-expanded={showAllReviews}
                >
                  {showAllReviews ? 'Show less' : 'Show more'}
                </button>
              </div>
            )}
          </section>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(290px, 1fr))', gap: 20, alignItems: 'start', marginTop: 20 }}>
          <section className="card">
            <h2 style={{ fontSize: '1.1rem', marginBottom: 10 }}>Email reminders</h2>
            {!emailPrefs ? (
              <p style={{ color: 'var(--color-text-muted)', fontSize: '.9rem' }}>Email settings are unavailable right now.</p>
            ) : (
              <>
                <p style={{ color: 'var(--color-text-muted)', fontSize: '.9rem', marginBottom: 12 }}>Get an email when a reminder is due.</p>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input type="checkbox" checked={emailPrefs.email_reminders} onChange={handleToggleEmails} disabled={!emailPrefs.has_email && !emailPrefs.email_reminders} />
                  Email me when a reminder is due
                </label>
                {!emailPrefs.has_email && <p style={{ color: 'var(--color-text-muted)', fontSize: '.8rem', marginTop: 8 }}>Add an email address to your profile to enable this.</p>}
                {emailPrefs.email_reminders && !emailPrefs.delivery_enabled && (
                  <p style={{ color: 'var(--color-text-muted)', fontSize: '.8rem', marginTop: 8 }}>Saved, but this server is not set up to send email yet, so nothing will arrive.</p>
                )}
              </>
            )}
          </section>

          <section className="card">
            <h2 style={{ fontSize: '1.1rem', marginBottom: 10 }}>Share your progress</h2>
            <p style={{ color: 'var(--color-text-muted)', fontSize: '.9rem', marginBottom: 12 }}>Create a read-only link showing your username, phases, streak and quiz stats. Your email is never shown.</p>
            <select aria-label="Roadmap to share" value={shareGoalId} onChange={(event) => setShareGoalId(event.target.value)} style={{ marginBottom: 12 }}>
              <option value="">Choose a roadmap…</option>
              {roadmaps.map((roadmap) => <option key={roadmap.goal_id} value={roadmap.goal_id}>{roadmap.goal_name || roadmap.goal_id}</option>)}
            </select>
            {shareGoalId && !shareToken && <button className="btn btn-primary" onClick={handleCreateShare} disabled={shareBusy}>{shareBusy ? 'Working…' : 'Create share link'}</button>}
            {shareToken && (
              <div style={{ display: 'grid', gap: 8 }}>
                <input readOnly value={shareUrl} aria-label="Share link" onFocus={(event) => event.target.select()} />
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button className="btn btn-outline" onClick={handleCopyShare}><FiCopy size={14} /> Copy link</button>
                  <button className="btn btn-ghost" onClick={handleRevokeShare} disabled={shareBusy}>Turn off sharing</button>
                </div>
              </div>
            )}
          </section>
        </div>

        <section className="card" style={{ marginTop: 20 }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '1.1rem', marginBottom: 16 }}><FiTarget /> Your reminders</h2>
          {reminders.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted)', fontSize: '.9rem' }}>You do not have any reminders yet. Create one above to start planning study sessions.</p>
          ) : (
            <div style={{ display: 'grid', gap: 8 }}>
              {orderedReminders.map((reminder) => (
                <div key={reminder.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', padding: '12px 0', borderBottom: '1px solid var(--color-border)', color: reminder.completed ? 'var(--color-text-muted)' : 'inherit' }}>
                  <div>
                    <strong style={{ textDecoration: reminder.completed ? 'line-through' : 'none' }}>{reminder.title}</strong>
                    <p style={{ color: 'var(--color-text-muted)', fontSize: '.8rem', marginTop: 3 }}>{formatDate(reminder.due_at)}{reminder.goal_id ? ` · Roadmap ${reminder.goal_id}` : ' · General reminder'}</p>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      className="badge badge-surface"
                      style={{ border: 0, fontFamily: 'inherit', cursor: reminderActionId === reminder.id ? 'wait' : 'pointer', opacity: reminderActionId === reminder.id ? 0.65 : 1 }}
                      onClick={() => handleToggleReminder(reminder)}
                      disabled={reminderActionId === reminder.id}
                      aria-pressed={Boolean(reminder.completed)}
                      aria-label={`${reminder.completed ? 'Mark incomplete' : 'Mark complete'}: ${reminder.title}`}
                      title={reminder.completed ? 'Click to mark this reminder incomplete' : 'Click to mark this reminder complete'}
                    >
                      {reminderActionId === reminder.id ? 'Saving…' : reminder.completed ? 'Completed' : 'Mark complete'}
                    </button>
                    <button className="btn btn-ghost" onClick={() => handleDeleteReminder(reminder)} disabled={reminderActionId === reminder.id} aria-label={`Delete reminder: ${reminder.title}`} title="Delete reminder">
                      <FiTrash2 size={15} /> Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
