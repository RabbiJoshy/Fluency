import './state.js';

// Speak a word in the target language
function speakWord(text, useEnglish = false) {
    if (!speechEnabled || !text || !window.speechSynthesis) return;

    // Cancel any ongoing speech
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    const langCode = useEnglish ? 'en-US' : (speechLangCodes[selectedLanguage] || 'es-ES');
    utterance.lang = langCode;
    utterance.rate = 0.9;

    const voices = window.speechSynthesis.getVoices();
    if (voices.length > 0) {
        const langPrefix = langCode.split('-')[0];
        const matchingVoices = voices.filter(v => v.lang.startsWith(langPrefix));

        // Tier order: Natural/Premium > Google > Enhanced/Microsoft > named macOS voices > any
        const preferredVoice = matchingVoices.find(v =>
            v.name.includes('Natural') || v.name.includes('Premium')
        ) || matchingVoices.find(v =>
            v.name.includes('Google')
        ) || matchingVoices.find(v =>
            v.name.includes('Enhanced') || v.name.includes('Microsoft')
        ) || matchingVoices.find(v =>
            /Ava|Samantha|Karen|Daniel|Paulina|Monica/.test(v.name)
        ) || matchingVoices[0];

        if (preferredVoice) {
            utterance.voice = preferredVoice;
            utterance.lang = preferredVoice.lang;
        }
    }

    window.speechSynthesis.speak(utterance);
}

// Preload voices (they may not be available immediately)
if (window.speechSynthesis) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
        window.speechSynthesis.getVoices();
    };
}

window.speakWord = speakWord;
