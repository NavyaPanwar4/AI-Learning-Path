import api from './axios';

export const getGoals = () =>
  api.get('/users/goals');

export const updateProfile = (data) =>
  api.put('/users/profile', data);

export const extractSkills = (free_text) =>
  api.post('/users/extract-skills', { free_text });

export const getUserSkills = () =>
  api.get('/users/skills');

export const getMyProfile = () =>
  api.get('/users/me');

export const changePassword = (oldPassword, newPassword) =>
  api.put('/users/change-password', { old_password: oldPassword, new_password: newPassword });

export const getDashboard = () =>
  api.get('/users/dashboard');

export const updatePersonalInfo = (data) =>
  api.put('/users/personal-info', data);

export const logSession = (durationMinutes) =>
  api.post('/users/activity/session', { duration_minutes: durationMinutes });

export const deleteUserSkill = (skillId) =>
  api.delete(`/users/skills/${skillId}`);
