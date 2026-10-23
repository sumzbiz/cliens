import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { LanguageContext, type Language, type LanguageContextValue } from './language-context';

const TA: Record<string, string> = {
  Location: 'இடம்', Exposure: 'சூழல் தாக்கம்', Approach: 'முறை', Materials: 'கட்டுமானப் பொருட்கள்', Score: 'மதிப்பீடு',
  'Step 1 of 5': 'படி 1 / 5', 'Step 2 of 5': 'படி 2 / 5', 'Step 3 of 5': 'படி 3 / 5', 'Step 4 of 5': 'படி 4 / 5', 'Step 5 of 5': 'படி 5 / 5',
  'Draw your site': 'உங்கள் தளத்தை வரையுங்கள்',
  'Search an address or PIN code, or zoom in — the view switches to a flat satellite map for close work.': 'முகவரி அல்லது அஞ்சல் குறியீட்டைத் தேடுங்கள், அல்லது பெரிதாக்குங்கள். துல்லியமாகப் பணியாற்ற செயற்கைக்கோள் வரைபடம் திறக்கும்.',
  'Click the first corner of your site.': 'உங்கள் தளத்தின் முதல் மூலையில் சொடுக்குங்கள்.',
  'Keep clicking corners — at least three.': 'குறைந்தது மூன்று மூலைகளைச் சொடுக்கித் தொடருங்கள்.',
  'Click the first corner again to close the shape, or press Enter.': 'வடிவத்தை முடிக்க முதல் மூலையில் மீண்டும் சொடுக்குங்கள் அல்லது Enter அழுத்துங்கள்.',
  'Pick up the pencil, then click around your site to outline it. Zoom out to return to the globe.': 'வரையும் கருவியைத் தேர்ந்து, தளத்தின் எல்லையைச் சுற்றிச் சொடுக்குங்கள். உலகக் கோளுக்குத் திரும்ப சிறிதாக்குங்கள்.',
  Site: 'தளம்', 'Search a place': 'இடத்தைத் தேடுங்கள்', 'Draw boundary': 'எல்லையை வரையுங்கள்', 'Clear site': 'தளத்தை அழிக்கவும்',
  'How does the concrete sit?': 'கான்கிரீட் எந்தச் சூழலில் உள்ளது?',
  'Why this question decides so much': 'இந்தத் தேர்வு ஏன் முக்கியம்?',
  'The code does not set one standard for all concrete. It sorts an element into an exposure class by how much water, salt and air reaches it, then sets a different minimum grade, minimum cement content and maximum water/cement ratio for each class.': 'அனைத்து கான்கிரீட்டுக்கும் ஒரே தரநிலையை விதிமுறை நிர்ணயிப்பதில்லை. நீர், உப்பு மற்றும் காற்றின் தாக்கத்தைப் பொறுத்து வெளிப்பாட்டு வகையைத் தீர்மானித்து, ஒவ்வொரு வகைக்கும் குறைந்தபட்ச தரம், சிமெண்டு அளவு மற்றும் அதிகபட்ச நீர்/சிமெண்டு விகிதத்தை நிர்ணயிக்கிறது.',
  'Your district’s measured humidity, wet hours and distance from the coast are combined with this answer to pick the final class. You are not choosing the class directly.': 'உங்கள் மாவட்டத்தின் ஈரப்பதம், மழை நேரம் மற்றும் கடற்கரையிலிருந்து உள்ள தூரத்துடன் இந்தத் தேர்வையும் சேர்த்து இறுதி வகை கணக்கிடப்படும். வகையை நீங்கள் நேரடியாகத் தேர்ந்தெடுக்கவில்லை.',
  Back: 'பின்செல்', Continue: 'தொடர்க',
  'What do you want to know?': 'நீங்கள் எதைத் தெரிந்துகொள்ள விரும்புகிறீர்கள்?',
  'Both answers use the same measured climate and the same code checks. The difference is only what gets compared against the recommendation.': 'இரண்டு முடிவுகளும் ஒரே அளவிடப்பட்ட காலநிலைத் தரவையும் விதிமுறைச் சரிபார்ப்பையும் பயன்படுத்தும். பரிந்துரையுடன் எதை ஒப்பிடுவது என்பதில்தான் வேறுபாடு.',
  Check: 'சரிபார்', Advise: 'பரிந்துரை', 'I have a specification': 'என்னிடம் விவரக்குறிப்பு உள்ளது',
  'Enter the concrete mix and walling you plan to use. We score it against IS 456 for your district, show every requirement it meets or misses, and show what we would specify instead.': 'நீங்கள் பயன்படுத்தத் திட்டமிட்டுள்ள கான்கிரீட் கலவை மற்றும் சுவர் பொருளை உள்ளிடுங்கள். உங்கள் மாவட்டத்திற்கான IS 456 அடிப்படையில் மதிப்பிட்டு, பூர்த்தி செய்த மற்றும் தவறிய தேவைகளையும் மாற்றுப் பரிந்துரையையும் காட்டுவோம்.',
  'Enter my materials': 'என் பொருட்களை உள்ளிடு', 'Tell me what to use': 'எதைப் பயன்படுத்துவது எனச் சொல்லுங்கள்',
  'Skip the form. We specify a mix and walling that clears the code for your district, and compare it against what typically gets built so you can see the gap.': 'படிவத்தைத் தவிர்க்கவும். உங்கள் மாவட்ட விதிமுறைகளைப் பூர்த்தி செய்யும் கலவை மற்றும் சுவர் பொருளைப் பரிந்துரைத்து, பொதுவாகப் பயன்படுத்தப்படுவதுடன் ஒப்பிடுவோம்.',
  'Recommend a specification': 'விவரக்குறிப்பைப் பரிந்துரைக்கவும்',
  'What are you building with?': 'எந்தப் பொருட்களைக் கொண்டு கட்டுகிறீர்கள்?',
  'Tap any line to change it. These four values are what IS 456 checks against your district’s exposure class.': 'மாற்ற எந்த வரியையும் தட்டுங்கள். இந்த நான்கு மதிப்புகளையும் உங்கள் மாவட்டத்தின் வெளிப்பாட்டு வகைக்கான IS 456 தேவைகளுடன் ஒப்பிடுவோம்.',
  'Concrete grade': 'கான்கிரீட் தரம்', 'Characteristic strength': 'சிறப்பியல்பு வலிமை', 'Cement content': 'சிமெண்டு அளவு',
  'Water / cement ratio': 'நீர் / சிமெண்டு விகிதம்', 'Lower is denser and more durable': 'குறைந்த விகிதம் அதிக அடர்த்தியும் நீடித்த தன்மையும் தரும்',
  Walling: 'சுவர் பொருள்', 'Checked for this climate’s suitability': 'இந்தக் காலநிலைக்கான பொருத்தம் சரிபார்க்கப்படும்',
  'Score this specification': 'இந்த விவரக்குறிப்பை மதிப்பிடு', Cement: 'சிமெண்டு', Done: 'முடிந்தது',
  'The characteristic compressive strength in N/mm² at 28 days.': '28 நாட்களில் N/mm²-ல் அளவிடப்படும் சிறப்பியல்பு அழுத்த வலிமை.',
  'Cement type': 'சிமெண்டு வகை', 'Water to cement ratio': 'நீர் மற்றும் சிமெண்டு விகிதம்',
  'Walling material': 'சுவர் கட்டுமானப் பொருள்', 'Scoring…': 'மதிப்பிடப்படுகிறது…',
  'Checking your specification against IS 456…': 'உங்கள் விவரக்குறிப்பு IS 456-உடன் ஒப்பிடப்படுகிறது…',
  'Go back and change something': 'பின்சென்று மாற்றுங்கள்', 'See the measurements': 'அளவீடுகளைக் காண்க',
  'What we checked': 'நாங்கள் சரிபார்த்தவை', Requirement: 'தேவை', 'Code needs': 'விதிமுறை தேவை', 'You have': 'உங்களிடம் உள்ளது', Result: 'முடிவு',
  Meets: 'பூர்த்தி', Short: 'குறைவு', 'Recommended for this climate': 'இந்தக் காலநிலைக்கான பரிந்துரை',
  'already in your spec': 'உங்கள் விவரக்குறிப்பில் உள்ளது', 'Take this with you': 'இந்த அறிக்கையைப் பெறுங்கள்',
  'A one-page summary you can hand to your contractor, with the specification and the code clause behind each item.': 'ஒவ்வொரு பொருளுக்கான விவரக்குறிப்பும் விதிமுறைப் பிரிவும் கொண்ட ஒரு பக்கச் சுருக்கத்தை ஒப்பந்ததாரரிடம் வழங்கலாம்.',
  'Zoom in': 'பெரிதாக்கு', 'Zoom out': 'சிறிதாக்கு', 'Move the map': 'வரைபடத்தை நகர்த்து', 'Draw your site boundary': 'தள எல்லையை வரையுங்கள்',
  'Choose language': 'மொழியைத் தேர்ந்தெடுக்கவும்', English: 'ஆங்கிலம்', Tamil: 'தமிழ்',
};

function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() =>
    window.localStorage.getItem('climate-lien-language') === 'ta' ? 'ta' : 'en'
  );
  const setLanguage = (next: Language) => {
    window.localStorage.setItem('climate-lien-language', next);
    setLanguageState(next);
  };
  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);
  const value = useMemo<LanguageContextValue>(() => ({
    language,
    setLanguage,
    // Unknown/dynamic copy remains in its source language rather than being
    // incorrectly translated or hidden. Fixed UI copy is covered in this table.
    t: (english) => language === 'ta' ? TA[english] ?? english : english,
  }), [language]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export { LanguageProvider };
