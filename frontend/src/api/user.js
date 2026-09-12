import api from './axios';

export const getGoals = () =>
  api.get('/users/goals');

export const updateProfile = (data) =>
  api.put('/users/profile', data);

export const extractSkills = (free_text) =>
  api.post('/users/extract-skills', { free_text });

export const getUserSkills = () =>
  api.get('/users/skills');
