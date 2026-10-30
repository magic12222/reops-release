import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource/geist-sans/latin-400.css';
import '@fontsource/geist-sans/latin-500.css';
import '@fontsource/geist-sans/latin-600.css';
import '@fontsource/geist-mono/latin-400.css';
import App from './App';
import './styles.css';
import './hero.css';
import './architecture.css';
import './navigation/navigation.css';
import './i18n/i18n.css';
import { initializeRouter } from './navigation/router';

initializeRouter();
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
