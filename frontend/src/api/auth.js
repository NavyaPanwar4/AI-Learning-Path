import api from './axios';

export const register = (data) =>
  api.post('/auth/register', data);

export const login = (data) =>
  api.post('/auth/login', data);

export const forgotPassword = (email) =>
  api.post('/auth/forgot-password', { email });

export const resetPassword = (token, newPassword) =>
  api.post('/auth/reset-password', { token, new_password: newPassword });