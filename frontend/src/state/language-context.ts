import { createContext, useContext } from 'react';

export type Language = 'en' | 'ta';
export type LanguageContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (english: string) => string;
};

export const LanguageContext = createContext<LanguageContextValue>({
  language: 'en',
  setLanguage: () => undefined,
  t: (english) => english,
});

export function useLanguage() {
  return useContext(LanguageContext);
}
