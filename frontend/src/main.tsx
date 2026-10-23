import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import './index.css';
import { SessionProvider } from './state/session';
import { VoiceProvider } from './state/voice';
import { LanguageProvider } from './state/language';

const container = document.getElementById('root');

if (container === null) {
  throw new Error('Root element #root is missing from index.html');
}

// The router wraps the session so that navigating between steps never remounts the
// provider — the answers collected so far have to survive every route change.
createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <LanguageProvider>
          <VoiceProvider>
            <App />
          </VoiceProvider>
        </LanguageProvider>
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>
);
