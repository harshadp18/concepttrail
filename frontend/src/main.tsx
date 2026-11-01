import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import './index.css';

// Immediately initialize accessibility settings from localStorage on startup
try {
  const savedTextSize = localStorage.getItem('concepttrail_text_size');
  if (savedTextSize) {
    document.documentElement.setAttribute('data-text-size', savedTextSize);
  }
  if (localStorage.getItem('concepttrail_line_spacing') === 'true') {
    document.body.classList.add('accessibility-line-spacing');
  }
  if (localStorage.getItem('concepttrail_high_contrast') === 'true') {
    document.body.classList.add('accessibility-high-contrast');
  }
} catch (e) {
  // localStorage may be unavailable in some sandboxes
}

const rootElement = document.getElementById('root');

if (!rootElement) {
  throw new Error('Failed to find the root element in index.html');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
