/**
 * Tamil narration text, kept beside the English it mirrors.
 *
 * Every string here is read aloud by the voice agent. They live in one file, not
 * scattered through the pages, so a Tamil speaker can review the whole script in
 * one sitting and check it against what is on screen — and so a wording change
 * cannot land in the audio without someone seeing the translation.
 *
 * The narration deliberately reads the question *and* every option in order. A
 * user who cannot read the screen has to hear the full choice before deciding, so
 * summarising or skipping options would defeat the point.
 *
 * Numbers and grades are spelled out phonetically rather than left as digits —
 * "எம் இருபது" rather than "M20" — because the model reads Latin characters in a
 * Tamil sentence unreliably.
 */

/** Joins a question with its options into one continuous reading. */
export function buildNarration(question: string, options: readonly string[]): string {
  if (options.length === 0) {
    return question;
  }
  // "விருப்பங்கள்" = "the options". Naming them before listing them tells a
  // listener that a list is coming, which a bare run-on sentence does not.
  return `${question} விருப்பங்கள்: ${options.join(', ')}.`;
}

export const TA = {
  /** Step 1 — location. */
  location: {
    question:
      'நீங்கள் எங்கு கட்டப் போகிறீர்கள்? உங்கள் இடத்தைத் தேடுங்கள், அல்லது வரைபடத்தில் பெரிதாக்கி உங்கள் நிலத்தைச் சுற்றி ஒரு பெட்டியை வரையுங்கள்.',
    options: [
      'இடத்தைத் தேட, மேலே உள்ள தேடல் பெட்டியில் ஊர் பெயர், முகவரி அல்லது அஞ்சல் குறியீட்டைத் தட்டச்சு செய்யுங்கள்',
      'நிலத்தை வரைய, பென்சில் பொத்தானை அழுத்தி, வரைபடத்தில் இழுத்து ஒரு பெட்டியை உருவாக்குங்கள்',
      'அல்லது மாவட்டப் பட்டியலிலிருந்து நேரடியாகத் தேர்ந்தெடுக்கலாம்',
    ],
  },

  /** Step 2 — exposure. The single biggest driver of the score. */
  exposure: {
    question:
      'உங்கள் கான்கிரீட் எப்படி அமைந்துள்ளது? இது ஐ. எஸ். நானூற்று ஐம்பத்தாறு விதிமுறையின் வெளிப்பாட்டு வகையைத் தீர்மானிக்கிறது.',
    options: [
      'உட்புறம். வீட்டுக்குள், மழை படாத இடம்',
      'மறைவானது. கூரையின் கீழ், சாதாரண ஈரப்பதம்',
      'வெளிப்படுவது. மழை மற்றும் வெயில் நேரடியாகப் படும் இடம்',
      'புதைக்கப்பட்டது. மண்ணுடன் தொடர்பில் இருப்பது',
      'அலை மண்டலம். கடல் அலை படும் இடம். இதுவே மிகக் கடுமையான நிலை',
    ],
  },

  /** Step 3 — which question the user is asking. */
  mode: {
    question: 'நீங்கள் என்ன தெரிந்து கொள்ள விரும்புகிறீர்கள்?',
    options: [
      'என்னிடம் ஒரு திட்டவிவரம் உள்ளது. நீங்கள் பயன்படுத்தப் போகும் கலவையை உள்ளிடுங்கள், நாங்கள் அதை மதிப்பிடுகிறோம்',
      'எதைப் பயன்படுத்த வேண்டும் என்று சொல்லுங்கள். உங்கள் மாவட்டத்திற்கு ஏற்ற கலவையை நாங்கள் பரிந்துரைக்கிறோம்',
    ],
  },

  /** Step 4 — materials. Each popup narrates separately. */
  grade: {
    question: 'கான்கிரீட் தரம் எது? இது இருபத்தெட்டு நாட்களில் அடையும் வலிமையைக் குறிக்கிறது.',
    options: [
      'எம் பதினைந்து',
      'எம் இருபது',
      'எம் இருபத்தைந்து',
      'எம் முப்பது',
      'எம் முப்பத்தைந்து',
      'எம் நாற்பது',
      'எம் நாற்பத்தைந்து',
    ],
  },

  cement: {
    question:
      'சிமெண்ட் அளவு எவ்வளவு? ஒரு கன மீட்டருக்கு கிலோகிராமில் அளவைக் கொடுங்கள். பொதுவாக இருநூற்று ஐம்பது முதல் நானூற்று ஐம்பது வரை இருக்கும்.',
    options: [
      'ஓ. பி. சி. சாதாரண போர்ட்லாந்து சிமெண்ட். இதுவே இயல்பான தேர்வு',
      'பி. பி. சி. போர்ட்லாந்து பொஸோலானா சிமெண்ட். கலவை சிமெண்ட்',
      'பி. எஸ். சி. போர்ட்லாந்து ஸ்லாக் சிமெண்ட். உப்புத்தன்மைக்கு எதிராக நல்லது',
    ],
  },

  waterCement: {
    question:
      'நீர் சிமெண்ட் விகிதம் என்ன? சிமெண்ட் எடையுடன் ஒப்பிடும்போது நீரின் எடை. இதுவே நீடித்து உழைப்பதைத் தீர்மானிக்கும் மிக முக்கியமான காரணி.',
    options: [
      'குறைவான விகிதம், அதாவது முப்பது சதவீதம், அடர்த்தியானது ஆனால் வேலை செய்வது கடினம்',
      'அதிக விகிதம், அதாவது எழுபது சதவீதம், வேலை செய்ய எளிது ஆனால் நுண்துளைகள் அதிகம்',
      'நழுவியை நகர்த்தி உங்கள் விகிதத்தைத் தேர்ந்தெடுக்கவும்',
    ],
  },

  walling: {
    question: 'சுவருக்கு எந்தப் பொருளைப் பயன்படுத்துகிறீர்கள்?',
    options: [
      'சுட்ட களிமண் செங்கல். இப்பகுதியில் வழக்கமான தேர்வு. ஆனால் அதிக நீரை உறிஞ்சும்',
      'சாம்பல் செங்கல். களிமண்ணை விட அடர்த்தியானது, அளவில் நிலையானது',
      'ஏ. ஏ. சி. கட்டி. இலகுவானது, வெப்பத்தைத் தடுக்கும். ஆனால் மழையிலிருந்து பாதுகாப்பு தேவை',
      'கான்கிரீட் திடக் கட்டி. வலிமையானது, நீரை உறிஞ்சுவது குறைவு. ஆனால் வெப்பத்தைத் தடுக்காது',
      'இன்ஜினியரிங் செங்கல். மிகக் குறைந்த நீர் உறிஞ்சுதல். கடுமையான சூழலுக்கு ஏற்றது',
    ],
  },
} as const;

/** Reads the finished score aloud, built from the live response. */
export function scoreNarration(input: {
  district: string;
  exposureLabel: string;
  proposed: number;
  recommended: number;
  improvement: number;
  compliant: boolean;
}): string {
  const verdict = input.compliant
    ? 'உங்கள் திட்டவிவரம் விதிமுறையை பூர்த்தி செய்கிறது.'
    : 'உங்கள் திட்டவிவரம் விதிமுறையை விட குறைவாக உள்ளது.';

  return [
    `${input.district} பகுதிக்கான உங்கள் மதிப்பெண் தயார்.`,
    `உங்கள் இடத்தின் வெளிப்பாட்டு நிலை: ${input.exposureLabel}.`,
    `உங்கள் திட்டவிவரத்தின் மதிப்பெண் நூற்றுக்கு ${String(Math.round(input.proposed))}.`,
    `நாங்கள் பரிந்துரைக்கும் திட்டவிவரத்தின் மதிப்பெண் நூற்றுக்கு ${String(Math.round(input.recommended))}.`,
    verdict,
    input.improvement > 0
      ? `பரிந்துரைக்கப்பட்ட கலவைக்கு மாறினால் ${String(Math.round(input.improvement))} புள்ளிகள் அதிகரிக்கும்.`
      : 'பரிந்துரை இதை விட மேம்படுத்தாது.',
  ].join(' ');
}
