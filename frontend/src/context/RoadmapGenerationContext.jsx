import { useCallback, useEffect, useRef, useState } from 'react';
import { cancelRoadmapGeneration, getRoadmapGenerationJob, startRoadmapGeneration } from '../api/roadmap';
import { useAuth } from './useAuth';

import { RoadmapGenerationContext } from './RoadmapGenerationContext.js';
const STORAGE_KEY = 'traject.roadmapGenerationJob';
const ACTIVE_STATUSES = new Set(['queued', 'running', 'cancel_requested']);

function readStoredJob() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (!value || typeof value.job_id !== 'string') return null;
    if (value.status === 'cancelled' || value.status === 'failed') {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

function persistJob(job) {
  try {
    if (job) localStorage.setItem(STORAGE_KEY, JSON.stringify(job));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable in private/restricted browser contexts.
  }
}

export function RoadmapGenerationProvider({ children }) {
  const { authenticated } = useAuth();
  const [job, setJob] = useState(() => readStoredJob());
  const [isStarting, setIsStarting] = useState(false);
  const [startError, setStartError] = useState('');
  const [isCancelling, setIsCancelling] = useState(false);
  const [cancelError, setCancelError] = useState('');
  const [pollError, setPollError] = useState('');
  const [pollRetryNonce, setPollRetryNonce] = useState(0);
  const jobRef = useRef(job);
  const startPromiseRef = useRef(null);

  useEffect(() => {
    jobRef.current = job;
  }, [job]);

  useEffect(() => {
    if (authenticated) return;
    jobRef.current = null;
    startPromiseRef.current = null;
    setJob(null);
    setIsStarting(false);
    setStartError('');
    persistJob(null);
  }, [authenticated]);

  const updateJob = useCallback((nextJob) => {
    jobRef.current = nextJob;
    setJob(nextJob);
    persistJob(nextJob?.status === 'cancelled' || nextJob?.status === 'failed' ? null : nextJob);
  }, []);

  const startGeneration = useCallback(async () => {
    const existing = jobRef.current;
    if (existing?.job_id && ACTIVE_STATUSES.has(existing.status)) return existing;
    if (startPromiseRef.current) return startPromiseRef.current;

    const pending = (async () => {
      setIsStarting(true);
      setStartError('');
      try {
        const response = await startRoadmapGeneration();
        const startedJob = response.data;
        if (!startedJob?.job_id) {
          throw new Error('The backend did not return a generation job ID.');
        }
        updateJob({ ...startedJob, updated_at: Date.now() });
        return startedJob;
      } catch (error) {
        const detail = error.response?.data?.detail;
        const message = typeof detail === 'string'
          ? detail
          : detail?.message || error.message || 'Could not start roadmap generation.';
        setStartError(message);
        throw error;
      } finally {
        setIsStarting(false);
      }
    })();

    startPromiseRef.current = pending;
    try {
      return await pending;
    } finally {
      startPromiseRef.current = null;
    }
  }, [updateJob]);

  useEffect(() => {
    if (!authenticated || !job?.job_id || !ACTIVE_STATUSES.has(job.status)) return undefined;

    let cancelled = false;
    let timer = null;
    let consecutiveFailures = 0;
    const maxConsecutiveFailures = 6;

    const poll = async () => {
      if (cancelled) return;
      try {
        const response = await getRoadmapGenerationJob(job.job_id);
        if (cancelled) return;
        if (!response?.data?.status) throw new Error('The generation status response was incomplete.');

        consecutiveFailures = 0;
        setPollError('');
        const latest = { ...jobRef.current, ...response.data, updated_at: Date.now() };
        updateJob(latest);
        if (ACTIVE_STATUSES.has(latest.status)) timer = window.setTimeout(poll, 1600);
      } catch (error) {
        if (cancelled) return;
        if (error.response?.status === 404) {
          updateJob(null);
          setPollError('This generation job is no longer available. Start a new roadmap generation if no saved roadmap exists.');
          return;
        }
        consecutiveFailures += 1;
        if (consecutiveFailures >= maxConsecutiveFailures) {
          setPollError('Traject could not check the generation status after 6 attempts. Generation has not been cancelled. Retry the status check to reconnect.');
          return;
        }
        const retryDelay = Math.min(1600 * (2 ** (consecutiveFailures - 1)), 12000);
        timer = window.setTimeout(poll, retryDelay);
      }
    };

    setPollError('');
    poll();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [authenticated, job?.job_id, job?.status, pollRetryNonce, updateJob]);

  const retryPolling = useCallback(() => {
    setPollError('');
    setPollRetryNonce((value) => value + 1);
  }, []);

  const cancelGeneration = useCallback(async () => {
    const current = jobRef.current;
    if (!current?.job_id || !['queued', 'running'].includes(current.status)) return current;

    setIsCancelling(true);
    setCancelError('');
    try {
      const response = await cancelRoadmapGeneration(current.job_id);
      const updated = { ...current, ...response.data, updated_at: Date.now() };
      updateJob(updated);
      return updated;
    } catch (error) {
      const detail = error.response?.data?.detail;
      setCancelError(typeof detail === 'string' ? detail : detail?.message || error.message || 'Could not cancel roadmap generation.');
      throw error;
    } finally {
      setIsCancelling(false);
    }
  }, [updateJob]);

  const dismissJob = useCallback(() => {
    if (jobRef.current && ACTIVE_STATUSES.has(jobRef.current.status)) return;
    updateJob(null);
  }, [updateJob]);

  const value = {
    job,
    isStarting,
    startError,
    isGenerating: Boolean(job?.job_id && ACTIVE_STATUSES.has(job.status)),
    startGeneration,
    cancelGeneration,
    isCancelling,
    cancelError,
    pollError,
    retryPolling,
    dismissJob,
  };

  return (
    <RoadmapGenerationContext.Provider value={value}>
      {children}
    </RoadmapGenerationContext.Provider>
  );
}

