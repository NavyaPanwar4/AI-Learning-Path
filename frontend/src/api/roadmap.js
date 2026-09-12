import api from './axios';

export const generateRoadmap = () =>
  api.post('/roadmap/generate-roadmap');

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
