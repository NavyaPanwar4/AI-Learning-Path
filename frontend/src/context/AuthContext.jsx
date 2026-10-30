import { useEffect, useState } from 'react';
import { AuthContext } from './authContext';

export function AuthProvider({ children }) {
  const [authenticated, setAuthenticated] = useState(() => Boolean(localStorage.getItem('authenticated')));

  useEffect(() => {
    const handleStorage = () => setAuthenticated(Boolean(localStorage.getItem('authenticated')));
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const signIn = () => {
    localStorage.setItem('authenticated', '1');
    setAuthenticated(true);
  };

  const signOut = () => {
    localStorage.removeItem('authenticated');
    localStorage.removeItem('user');
    sessionStorage.removeItem('access_token');
    setAuthenticated(false);
  };

  return <AuthContext.Provider value={{ authenticated, signIn, signOut }}>{children}</AuthContext.Provider>;
}

