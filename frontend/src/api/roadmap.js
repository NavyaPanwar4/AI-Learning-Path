import api from './axios';

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Roadmap generation can involve several slow LLM/resource calls. Queue it and
// poll the persisted job rather than holding the original request open.
export const generateRoadmap = async ({ onStatus } = {}) => {
  const { data: job } = await api.post('/roadmap/generate-roadmap/async');
  if (!job?.job_id) throw new Error('The backend did not return a generation job ID.');

  const timeoutMs = 8 * 60 * 1000;
  const startedAt = Date.now();
  let lastStatus = job.status || 'queued';
  onStatus?.(lastStatus);

  while (Date.now() - startedAt < timeoutMs) {
    await delay(1200);
    const { data: current } = await api.get(`/roadmap/generation-jobs/${job.job_id}`);
    if (current.status !== lastStatus) {
      lastStatus = current.status;
      onStatus?.(lastStatus);
    }
    if (current.status === 'completed') {
      if (!current.goal_id) throw new Error('Roadmap generation completed without a goal ID.');
      return getSavedRoadmap(current.goal_id);
    }
    if (current.status === 'failed') {
      const failure = new Error(current.error || 'Roadmap generation failed. Please try again.');
      failure.response = { data: { detail: failure.message } };
      throw failure;
    }
  }

  throw new Error('Roadmap generation is taking longer than expected. Refresh Saved Roadmaps to check its status.');
};

export const getSavedRoadmaps = () =>
  api.get('/roadmap/saved');

export const getSavedRoadmap = (goalId) =>
  api.get(`/roadmap/${goalId}`);

export const submitFeedback = (data) =>
  api.post('/roadmap/feedback', data);

export const getUserFeedback = () =>
  api.get('/roadmap/feedback/user');

export const updatePhaseStatus = (goalId, phaseIndex, completed) =>
  api.patch(`/roadmap/${goalId}/phase/${phaseIndex}?completed=${completed}`);

export const completeRoadmap = (goalId) =>
  api.post(`/roadmap/${goalId}/complete`);

export const generateStudyNotes = (goalId, phaseIndex) =>
  api.post(`/roadmap/${goalId}/phase/${phaseIndex}/study-notes`);

export const deleteRoadmap = (goalId) =>
  api.delete(`/roadmap/${goalId}`);

export const generateQuiz = (goalId, phaseIndex) =>
  api.post(`/roadmap/${goalId}/phase/${phaseIndex}/quiz`);

export const downloadLearningReport = (goalId) =>
  api.get(`/roadmap/${goalId}/report`, { responseType: 'blob' });

export const submitQuiz = (goalId, phaseIndex, quizId, answers) =>
  api.post(`/roadmap/${goalId}/phase/${phaseIndex}/quiz/submit`, {
    quiz_id: quizId,
    answers,
  });

export const getRecommendation = (goalId) =>
  api.get(`/roadmap/${goalId}/recommendation`);

export const insertRemedialPhase = (goalId, phaseIndex) =>
  api.post(`/roadmap/${goalId}/phase/${phaseIndex}/insert-remedial`);
